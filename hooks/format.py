#!/usr/bin/env python3
"""PostToolUse hook shared by Claude Code and Codex: format edited files.

1. Records that the agent edited files in this repository during this
   session, so the Stop hook (verify.py) only verifies the agent's own work.
2. Formats the touched files. A repository owns formatting by providing an
   executable `.agents/format.sh` that receives the file paths. Without it,
   a built-in formatter runs only where the repository already opts in:
   dart format for Dart, prettier when a prettier config exists, csharpier
   when it is a configured dotnet tool. Missing formatters are silent; a
   formatter that fails (the file may not parse) exits 2 so the agent sees it.
"""
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

PATCH_FILE_LINE = re.compile(r"^\*\*\* (?:(?:Add|Update) File|Move to): (.+)$", re.M)
TIMEOUT_SECONDS = 60
CACHE_DIR = os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")),
                         "agents-harness")


def edit_marker(session_id: str, root: str) -> str:
    key = hashlib.sha256(f"{session_id}\0{root}".encode()).hexdigest()[:24]
    return os.path.join(CACHE_DIR, f"edited-{key}")


def touched_files(tool: str, tool_input: dict) -> list:
    if tool in ("Edit", "Write", "MultiEdit"):
        return [str(tool_input.get("file_path", ""))]
    if tool == "apply_patch":
        return [p.strip() for p in PATCH_FILE_LINE.findall(str(tool_input.get("command", "") or ""))]
    return []


def repo_root(cwd: str):
    try:
        out = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=cwd,
                             capture_output=True, text=True, timeout=5)
        return out.stdout.strip() if out.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def has_prettier_config(root: str) -> bool:
    if glob.glob(os.path.join(root, ".prettierrc*")) or glob.glob(os.path.join(root, "prettier.config.*")):
        return True
    try:
        with open(os.path.join(root, "package.json")) as handle:
            return "prettier" in json.load(handle)
    except (OSError, ValueError):
        return False


def has_csharpier(root: str) -> bool:
    try:
        with open(os.path.join(root, ".config", "dotnet-tools.json")) as handle:
            return "csharpier" in handle.read()
    except OSError:
        return False


def builtin_command(path: str, root: str):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".dart" and shutil.which("dart"):
        return ["dart", "format", path]
    if ext in (".ts", ".tsx", ".js", ".jsx", ".json", ".css", ".scss") and has_prettier_config(root):
        prettier = os.path.join(root, "node_modules", ".bin", "prettier")
        if os.access(prettier, os.X_OK):
            return [prettier, "--write", path]
    if ext == ".cs" and has_csharpier(root) and shutil.which("dotnet"):
        return ["dotnet", "csharpier", "format", path]
    return None


def run(cmd: list, cwd: str):
    try:
        result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                                timeout=TIMEOUT_SECONDS, stdin=subprocess.DEVNULL)
        return result.returncode, (result.stdout + result.stderr).strip()
    except subprocess.TimeoutExpired:
        return 0, ""
    except OSError as error:
        return 0, str(error)


def main() -> None:
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)
    if not isinstance(event, dict) or not isinstance(event.get("tool_input"), dict):
        sys.exit(0)

    cwd = event.get("cwd") or os.getcwd()
    files = [f if os.path.isabs(f) else os.path.join(cwd, f)
             for f in touched_files(event.get("tool_name", ""), event["tool_input"]) if f]
    files = [f for f in files if os.path.isfile(f)]
    root = repo_root(cwd)
    if not files or not root:
        sys.exit(0)

    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        open(edit_marker(str(event.get("session_id", "")), root), "a").close()
    except OSError:
        pass

    repo_formatter = os.path.join(root, ".agents", "format.sh")
    commands = ([[repo_formatter, *files]] if os.access(repo_formatter, os.X_OK)
                else [c for c in (builtin_command(f, root) for f in files) if c])

    failures = []
    for cmd in commands:
        code, output = run(cmd, root)
        if code != 0:
            failures.append(f"$ {' '.join(cmd)}\n{output[-2000:]}")
    if failures:
        sys.stderr.write("Formatter failed; the edited file may not parse:\n" + "\n".join(failures) + "\n")
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
