"""Agent harness installer for Claude Code, Codex and GitHub Copilot, on Windows, macOS and Linux.

Run through install.sh (macOS, Linux, WSL, Git Bash) or install.ps1 (Windows PowerShell).
One source of truth in ~/.agents; each agent gets thin links or generated bridges.
Safe to re-run. Anything it replaces is moved to ~/.agents-backup/<timestamp>/.
"""
import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True  # keep ~/.agents free of __pycache__
import time

LIB = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, LIB)
from merge_json import merge, write_json_atomic  # noqa: E402

IS_WINDOWS = os.name == "nt"
# Testing aid: behave like a Windows account without symlink rights (junctions and copies).
NO_SYMLINKS = IS_WINDOWS and os.environ.get("AGENTS_HARNESS_NO_SYMLINKS") == "1"
HARNESS = os.path.dirname(LIB)
HOME = os.path.expanduser("~")
HOOKS = (("PreToolUse", "guard.py", 15), ("PostToolUse", "format.py", 90))
CLAUDE_MATCHERS = {"PreToolUse": "Bash|PowerShell|Edit|Write|MultiEdit|NotebookEdit|Read|Grep",
                   "PostToolUse": "Edit|Write|MultiEdit"}
CODEX_MATCHERS = {"PreToolUse": "^Bash$|^apply_patch$", "PostToolUse": "^apply_patch$"}
PLUGIN = "mattpocock-skills"
MATT_SKILL_NAMES = ("tdd", "grill-me", "to-spec", "code-review")


class Installer:
    def __init__(self, dry_run: bool, plugins: bool):
        self.dry = dry_run
        self.plugins = plugins
        self.backup_dir = os.path.join(HOME, ".agents-backup", time.strftime("%Y%m%d-%H%M%S"))
        self.copied_files = []
        self.python = sys.executable
        self.copilot_home = os.environ.get("COPILOT_HOME") or os.path.join(HOME, ".copilot")

    # ---------- output and filesystem primitives ----------
    def say(self, text: str) -> None:
        print(text, flush=True)

    def act(self, description: str, func, *args) -> None:
        if self.dry:
            self.say(f"  would {description}")
        else:
            func(*args)
            self.say(f"  {description}")

    def backup(self, path: str) -> None:
        if not (os.path.lexists(path)):
            return
        rel = os.path.relpath(path, HOME)
        dest = os.path.join(self.backup_dir, rel)

        def move():
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            if is_link(path):  # keep a note of where the link pointed, then drop the link only
                with open(dest + ".link.txt", "w", encoding="utf-8") as handle:
                    handle.write(link_target(path))
                remove_link(path)
            else:
                shutil.move(path, dest)
        self.act(f"back up {path}", move)

    def snapshot(self, path: str) -> None:
        if os.path.isfile(path) and not self.dry:
            dest = os.path.join(self.backup_dir, os.path.relpath(path, HOME))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy2(path, dest)

    def link_dir(self, target: str, path: str) -> None:
        if is_link(path) and same_path(os.path.realpath(path), target):
            self.say(f"  ok: {path}")
            return
        self.backup(path)
        self.act(f"link {path} -> {target}", make_dir_link, target, path)

    def link_file(self, target: str, path: str) -> None:
        """Symlink a file; on Windows without symlink rights, keep a managed copy instead."""
        if os.path.islink(path) and same_path(os.path.realpath(path), target):
            self.say(f"  ok: {path}")
            return
        if path in self.copied_files or (os.path.isfile(path) and not os.path.islink(path)
                                         and same_content(path, target) and IS_WINDOWS):
            self.copied_files.append(path)
            self.say(f"  ok (copy): {path}")
            return
        self.backup(path)

        def create():
            os.makedirs(os.path.dirname(path), exist_ok=True)
            try:
                if NO_SYMLINKS:
                    raise OSError("symlinks disabled")
                os.symlink(target, path)
            except OSError:
                if not IS_WINDOWS:
                    raise
                shutil.copy2(target, path)
                self.copied_files.append(path)
        self.act(f"link {path} -> {target}", create)

    def write_text(self, path: str, content: str) -> None:
        if os.path.isfile(path) and not os.path.islink(path) and read(path) == content:
            self.say(f"  ok: {path}")
            return
        self.backup(path)

        def create():
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
        self.act(f"write {path}", create)

    def merge_settings(self, path: str, harness: dict) -> None:
        existing = load_json(path)
        merged = merge(existing, harness)
        if merged == existing:
            self.say(f"  ok: {path}")
            return
        self.snapshot(path)
        self.act(f"merge harness settings into {path}", write_json_atomic, path, merged)

    # ---------- hook command rendering ----------
    def script(self, name: str) -> str:
        return os.path.join(HARNESS, "hooks", name)

    def posix_command(self, name: str) -> str:
        return shlex.join([self.python.replace("\\", "/"), self.script(name).replace("\\", "/")])

    def powershell_command(self, name: str) -> str:
        quote = lambda s: "'" + s.replace("'", "''") + "'"  # noqa: E731
        # PowerShell maps a native command's non-zero exit to 1 unless it is passed on explicitly,
        # which would turn the guard's "blocked" (2) into a generic hook error.
        return f"& {quote(self.python)} {quote(self.script(name))}; exit $LASTEXITCODE"

    def windows_command(self, name: str) -> str:
        parts = [self.python, self.script(name)]
        return " ".join(f'"{p}"' if " " in p else p for p in parts)

    def claude_hooks(self) -> dict:
        hooks = {}
        for event, script, timeout in HOOKS:
            handler = {"type": "command", "timeout": timeout}
            if IS_WINDOWS:
                handler.update(command=self.powershell_command(script), shell="powershell")
            else:
                handler["command"] = self.posix_command(script)
            entry = {"hooks": [handler]}
            if event in CLAUDE_MATCHERS:
                entry = {"matcher": CLAUDE_MATCHERS[event], **entry}
            hooks[event] = [entry]
        return hooks

    def codex_hooks(self) -> dict:
        hooks = {}
        for event, script, timeout in HOOKS:
            handler = {"type": "command", "timeout": timeout}
            if IS_WINDOWS:
                handler.update(command=self.windows_command(script), commandWindows=self.windows_command(script))
            else:
                handler["command"] = self.posix_command(script)
            entry = {"hooks": [handler]}
            if event in CODEX_MATCHERS:
                entry = {"matcher": CODEX_MATCHERS[event], **entry}
            hooks[event] = [entry]
        return {"description": "Agent harness hooks. Scripts live in ~/.agents/hooks.", "hooks": hooks}

    def copilot_hooks(self) -> dict:
        hooks = {}
        for event, script, timeout in HOOKS:  # PascalCase names select the Claude-compatible payload
            hooks[event] = [{"type": "command", "bash": self.posix_command(script),
                             "powershell": self.powershell_command(script), "timeoutSec": timeout}]
        return {"version": 1, "hooks": hooks}

    # ---------- per-agent setup ----------
    def check_location(self) -> None:
        if not same_path(HARNESS, os.path.join(HOME, ".agents")):
            sys.exit(f"The harness must live at {os.path.join(HOME, '.agents')} (agents read "
                     f"~/.agents/skills and the hooks are referenced there). It is at {HARNESS}.\n"
                     "Clone it there, then run the installer again.")

    def codex(self) -> None:
        self.say("Codex")
        codex_home = os.environ.get("CODEX_HOME") or os.path.join(HOME, ".codex")
        self.link_file(os.path.join(HARNESS, "AGENTS.md"), os.path.join(codex_home, "AGENTS.md"))
        if os.path.exists(os.path.join(codex_home, "AGENTS.override.md")):
            self.say("  WARNING: AGENTS.override.md exists and replaces AGENTS.md; merge it into ~/.agents/AGENTS.md.")
        self.say("  skills: read natively from ~/.agents/skills")
        self.merge_settings(os.path.join(codex_home, "hooks.json"), self.codex_hooks())

    def claude(self) -> None:
        self.say("Claude Code")
        claude_dir = os.path.join(HOME, ".claude")
        bridge = read(os.path.join(HARNESS, "adapters", "claude", "CLAUDE.md"))
        existing = os.path.join(claude_dir, "CLAUDE.md")
        if os.path.isfile(os.path.join(claude_dir, "RTK.md")) or "\n@RTK.md" in "\n" + read(existing):
            bridge += "@RTK.md\n"
        self.write_text(existing, bridge)
        skills_dir = os.path.join(claude_dir, "skills")
        for name in sorted(os.listdir(os.path.join(HARNESS, "skills"))):
            source = os.path.join(HARNESS, "skills", name)
            if os.path.isdir(source):
                self.link_dir(source, os.path.join(skills_dir, name))
        self.remove_stale_links(skills_dir)
        settings = load_json(os.path.join(HARNESS, "adapters", "claude", "settings.json"))
        settings["hooks"] = self.claude_hooks()
        self.merge_settings(os.path.join(claude_dir, "settings.json"), settings)

    def copilot(self) -> None:
        self.say("GitHub Copilot")
        self.link_file(os.path.join(HARNESS, "AGENTS.md"), os.path.join(self.copilot_home, "copilot-instructions.md"))
        self.say("  skills: read natively from ~/.agents/skills")
        hooks_file = os.path.join(self.copilot_home, "hooks", "agents-harness.json")
        self.write_text(hooks_file, json.dumps(self.copilot_hooks(), indent=2) + "\n")

    def remove_stale_links(self, skills_dir: str) -> None:
        if not os.path.isdir(skills_dir):
            return
        for name in os.listdir(skills_dir):
            path = os.path.join(skills_dir, name)
            if is_link(path) and not os.path.exists(path) and \
                    os.path.join("agents", "skills") in os.path.normcase(link_target(path)):
                self.act(f"remove stale link {path}", remove_link, path)

    # ---------- mattpocock skills plugin ----------
    def install_plugins(self) -> None:
        self.say(f"{PLUGIN} plugin (MIT, github.com/mattpocock/skills)")
        for folder in (os.path.join(HOME, ".claude", "skills"), os.path.join(HOME, ".agents", "skills"),
                       os.path.join(self.copilot_home, "skills")):
            for name in MATT_SKILL_NAMES:
                path = os.path.join(folder, name)
                if os.path.isdir(path) and not is_link(path):
                    self.say(f"  WARNING: {path} looks like a copied mattpocock skill; remove copies so it loads once.")
        steps = {
            "claude": [["plugin", "install", f"{PLUGIN}@claude-plugins-official"]],
            "codex": [["plugin", "marketplace", "add", "mattpocock/skills"], ["plugin", "add", f"{PLUGIN}@mattpocock"]],
            "copilot": [["plugin", "marketplace", "add", "mattpocock/skills"],
                        ["plugin", "install", f"{PLUGIN}@mattpocock"]],
        }
        for cli, commands in steps.items():
            exe = shutil.which(cli)
            if not exe:
                self.say(f"  skip: {cli} not found")
                continue
            if self.installed(exe):
                self.say(f"  ok: {cli} plugin installed")
                continue
            for args in commands:
                if self.dry:
                    self.say(f"  would run: {cli} {' '.join(args)}")
                    continue
                result = subprocess.run([exe, *args], capture_output=True, timeout=300)
                ok = result.returncode == 0 or b"already" in (result.stdout + result.stderr).lower()
                self.say(f"  {'ran' if ok else 'FAILED'}: {cli} {' '.join(args)}")

    def installed(self, exe: str) -> bool:
        try:
            result = subprocess.run([exe, "plugin", "list"], capture_output=True, timeout=60)
            return PLUGIN.encode() in result.stdout
        except (OSError, subprocess.SubprocessError):
            return False

    def run(self) -> None:
        self.check_location()
        self.say(f"Harness: {HARNESS}\nPython for hooks: {self.python}")
        self.codex()
        self.claude()
        self.copilot()
        if self.plugins:
            self.install_plugins()
        self.say("")
        if self.copied_files:
            self.say("Note: this Windows account cannot create file symlinks, so these are copies of "
                     "~/.agents/AGENTS.md; run the installer again after editing or pulling it:")
            for path in self.copied_files:
                self.say(f"  {path}")
            self.say("(Turn on Windows Developer Mode to get real links instead.)")
        self.say("Next: trust the hooks (Codex: /hooks), then restart Claude Code, Codex and Copilot.")
        self.say("Optional, per repository: ask the agent to run the setup-repo skill there.")


# ---------- helpers ----------
def read(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    except OSError:
        return ""


def load_json(path: str) -> dict:
    text = read(path)
    if not text.strip():
        return {}
    data = json.loads(text)
    return data if isinstance(data, dict) else {}


def same_path(a: str, b: str) -> bool:
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def same_content(a: str, b: str) -> bool:
    return read(a) == read(b)


def is_link(path: str) -> bool:
    """True for symlinks and, on Windows, directory junctions."""
    if os.path.islink(path):
        return True
    try:
        os.readlink(path)  # Windows: also succeeds for junctions
        return True
    except (OSError, ValueError, NotImplementedError):
        return False


def link_target(path: str) -> str:
    try:
        return os.readlink(path)
    except OSError:
        return os.path.realpath(path)


def remove_link(path: str) -> None:
    if IS_WINDOWS and os.path.isdir(path):
        os.rmdir(path)  # removes a directory symlink or junction, never the target
    else:
        os.unlink(path)


def make_dir_link(target: str, path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not IS_WINDOWS:
        os.symlink(target, path, target_is_directory=True)
        return
    try:
        if NO_SYMLINKS:
            raise OSError("symlinks disabled")
        os.symlink(target, path, target_is_directory=True)
    except OSError:  # no symlink right: a directory junction needs no special privilege
        import _winapi
        _winapi.CreateJunction(target, path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Install the agent harness for Claude Code, Codex and Copilot.")
    parser.add_argument("--dry-run", action="store_true", help="show what would change without changing it")
    parser.add_argument("--no-plugins", action="store_true", help="skip the mattpocock skills plugin")
    args = parser.parse_args()
    Installer(args.dry_run, not args.no_plugins).run()


if __name__ == "__main__":
    main()
