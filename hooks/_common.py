"""Shared helpers for the harness hooks (Claude Code, Codex, GitHub Copilot; Windows and Unix).

Each agent sends a JSON event on stdin. The field names differ slightly:
Claude Code and Codex use tool_name/tool_input; Copilot uses the same with
PascalCase event names, or toolName/toolArgs (sometimes a JSON string) with
camelCase ones. normalize_event() maps all of them to one shape.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

IS_WINDOWS = os.name == "nt"
CACHE_DIR = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"),
                         "agents-harness")

SHELL_TOOLS = {"bash", "powershell", "pwsh", "shell", "run_in_terminal", "runinterminal",
               "exec_command", "terminal"}
POWERSHELL_TOOLS = {"powershell", "pwsh"}
EDIT_TOOLS = {"edit", "write", "multiedit", "create", "str_replace", "str_replace_editor",
              "notebookedit", "write_file", "edit_file", "create_file", "replace_string_in_file"}
READ_TOOLS = {"read", "view", "read_file", "grep", "search"}
PATCH_TOOLS = {"apply_patch"}
PATH_KEYS = ("file_path", "path", "filePath", "notebook_path", "filename")
PATCH_FILE_LINE = re.compile(r"^\*\*\* (?:(?:Add|Update|Delete) File|Move to): (.+)$", re.M)


def read_event():
    """Read the hook event from stdin as UTF-8 regardless of the console code page."""
    try:
        raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
        event = json.loads(raw)
    except (ValueError, OSError, AttributeError):
        return None
    return event if isinstance(event, dict) else None


def normalize_event(event: dict) -> dict:
    """Return {kind, tool, input, cwd, session_id, stop_hook_active} for any agent's payload."""
    tool = event.get("tool_name") or event.get("toolName") or ""
    tool_input = event.get("tool_input", event.get("toolArgs"))
    if isinstance(tool_input, str):
        try:
            tool_input = json.loads(tool_input)
        except ValueError:
            tool_input = {"command": tool_input}
    if not isinstance(tool_input, dict):
        tool_input = {}
    name = str(tool).lower()
    if name in PATCH_TOOLS:
        kind = "patch"
    elif name in SHELL_TOOLS:
        kind = "shell"
    elif name in EDIT_TOOLS:
        kind = "edit"
    elif name in READ_TOOLS:
        kind = "read"
    else:
        kind = "other"
    return {
        "kind": kind,
        "tool": name,
        "input": tool_input,
        "cwd": event.get("cwd") or os.getcwd(),
        "session_id": str(event.get("session_id") or event.get("sessionId") or ""),
        "stop_hook_active": bool(event.get("stop_hook_active") or event.get("stopHookActive")),
    }


def input_paths(tool_input: dict) -> list:
    return [str(tool_input[k]) for k in PATH_KEYS if tool_input.get(k)]


def patch_paths(patch: str, include_deleted: bool = True) -> list:
    paths = []
    for line in PATCH_FILE_LINE.finditer(patch):
        if include_deleted or not line.group(0).startswith("*** Delete"):
            paths.append(line.group(1).strip())
    return paths


def run(cmd: list, cwd: str, timeout: float, env=None):
    """Run a command, decode output as UTF-8, kill the whole process tree on timeout.

    Returns (exit_code or None on timeout, combined output).
    """
    kwargs = {"cwd": cwd, "stdout": subprocess.PIPE, "stderr": subprocess.STDOUT,
              "stdin": subprocess.DEVNULL, "env": env}
    if IS_WINDOWS:
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    try:
        process = subprocess.Popen(cmd, **kwargs)
    except OSError as error:
        return 127, str(error)
    try:
        out, _ = process.communicate(timeout=timeout)
        return process.returncode, out.decode("utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        kill_tree(process.pid)
        process.communicate()
        return None, ""


def kill_tree(pid: int) -> None:
    try:
        if IS_WINDOWS:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True, timeout=30)
        else:
            import signal
            os.killpg(pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        pass


def git(args: list, cwd: str) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace"))
    return result.stdout.decode("utf-8", errors="replace")


def repo_root(cwd: str):
    try:
        return os.path.normpath(git(["rev-parse", "--show-toplevel"], cwd).strip())
    except (RuntimeError, OSError, subprocess.SubprocessError):
        return None


def find_bash():
    """Git Bash on Windows (never the WSL launcher in System32), bash elsewhere."""
    if not IS_WINDOWS:
        return shutil.which("bash")
    candidates = [os.environ.get("CLAUDE_CODE_GIT_BASH_PATH", "")]
    for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                 os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                 os.path.expandvars(r"%LOCALAPPDATA%\Programs")):
        candidates.append(os.path.join(base, "Git", "bin", "bash.exe"))
    found = shutil.which("bash")
    if found and "system32" not in found.lower():
        candidates.append(found)
    return next((c for c in candidates if c and os.path.isfile(c)), None)


def find_powershell():
    return shutil.which("pwsh") or (shutil.which("powershell") if IS_WINDOWS else None)


def repo_script(root: str, name: str):
    """Command for the repository's `.agents/<name>.sh` or `.agents/<name>.ps1`, or None.

    Windows prefers the .ps1; Unix prefers the .sh. Either runs on either OS when
    its interpreter (Git Bash or PowerShell) is available.
    """
    sh = os.path.join(root, ".agents", f"{name}.sh")
    ps1 = os.path.join(root, ".agents", f"{name}.ps1")
    options = []
    if os.path.isfile(sh):
        options.append(("sh", sh))
    if os.path.isfile(ps1):
        options.append(("ps1", ps1))
    if IS_WINDOWS:
        options.sort(key=lambda item: item[0] != "ps1")
    for kind, path in options:
        if kind == "sh":
            bash = find_bash()
            if bash:
                return [bash, path]
        else:
            pwsh = find_powershell()
            if pwsh:
                return [pwsh, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", path]
    return None


def edit_marker(session_id: str, root: str) -> str:
    key = hashlib.sha256(f"{session_id}\0{os.path.normcase(root)}".encode()).hexdigest()[:24]
    return os.path.join(CACHE_DIR, f"edited-{key}")
