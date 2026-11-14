"""Agent harness installer for Claude Code, Codex, GitHub Copilot and opencode, on Windows, macOS and Linux.

Run through install.sh (macOS, Linux, WSL, Git Bash) or install.ps1 (Windows PowerShell).
One source of truth in ~/.agents; each agent gets thin links or generated bridges.
Safe to re-run. Anything it replaces is moved to ~/.agents-backup/<timestamp>/.
"""
import argparse
import copy
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True  # keep ~/.agents free of __pycache__
import time
import urllib.request

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
# opencode has no mattpocock plugin; the skills CLI copies the files. --copy keeps them out of
# ~/.agents/skills (its default "canonical" folder), which Codex and Copilot also read.
OPENCODE_SKILLS_CMD = ["skills@1", "add", "mattpocock/skills", "--global", "--agent", "opencode",
                       "--skill", "*", "--copy", "--yes"]
# Per-machine state and generated files; gitignored.
LOCAL = os.path.join(HARNESS, "local")
CHOICES_FILE = os.path.join(LOCAL, "choices.json")
MEMORY_LAYERS = {
    "none": "no memory layer",
    "ai-memory": "ai-memory: hooks, MCP and automatic handoffs (install ai-memory yourself first)",
    "optmem": "OptMem: lightweight, one prompt and one script; the installer fetches it",
}
CACHE_MODES = {
    "default": "each agent's default prompt-cache lifetime",
    "long": "longer cache: 1 hour for Claude Code and Anthropic models in opencode, 12 hours for OpenAI "
            "models in opencode; cache writes cost more",
    "warm": "keep the default cache warm during pauses (opencode only; sends extra small requests)",
}
# OptMem has no license file, so the harness does not copy it; it fetches this exact commit and checks it.
OPTMEM_COMMIT = "1fb164cf39028047781f72ac3bb1e5a691c1dcb0"
OPTMEM_SHA256 = "3dc120d01be3115ef6267eab4103e7909fc830d6227b549f20991ba999ee9ffb"
OPTMEM_URL = f"https://raw.githubusercontent.com/VictorTaelin/OptMem/{OPTMEM_COMMIT}/memo"


class Installer:
    def __init__(self, dry_run: bool, plugins: bool, memory: str = None, cache: str = None,
                 reconfigure: bool = False):
        self.dry = dry_run
        self.plugins = plugins
        try:
            saved = load_json(CHOICES_FILE)
        except ValueError:
            saved = {}
        self.applied = dict(saved.get("applied", {}))  # settings the harness wrote, so it can undo them
        self.memory = memory or (None if reconfigure else saved.get("memory"))
        self.cache = cache or (None if reconfigure else saved.get("cache"))
        self.agents_md = os.path.join(HARNESS, "AGENTS.md")
        self.optmem_home = os.path.join(HOME, ".optmem")
        self.backup_dir = os.path.join(HOME, ".agents-backup", time.strftime("%Y%m%d-%H%M%S"))
        self.copied_files = []
        self.python = sys.executable
        self.copilot_home = os.environ.get("COPILOT_HOME") or os.path.join(HOME, ".copilot")
        self.opencode_home = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.join(HOME, ".config"),
                                          "opencode")

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

    def write_text(self, path: str, content: str, keep_old: bool = True) -> None:
        if os.path.isfile(path) and not os.path.islink(path) and read(path) == content:
            self.say(f"  ok: {path}")
            return
        if keep_old:
            self.backup(path)

        def create():
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
        self.act(f"write {path}", create)

    def merge_settings(self, path: str, harness: dict, agent: str = "", managed: dict = None) -> None:
        existing = load_json(path)
        merged = merge(existing, harness)
        if managed:
            merged = self.manage(copy.deepcopy(merged), agent, managed)
        if merged == existing:
            self.say(f"  ok: {path}")
            return
        self.snapshot(path)
        self.act(f"merge harness settings into {path}", write_json_atomic, path, merged)

    def manage(self, data: dict, agent: str, wanted: dict) -> dict:
        """Set or undo settings the harness owns. `wanted` maps a dotted key to a value, or to None
        to remove a value the harness set earlier (a value you changed yourself is left alone)."""
        for dotted, value in wanted.items():
            key, path = f"{agent}:{dotted}", dotted.split(".")
            if value is not None:
                set_path(data, path, value)
                self.applied[key] = value
            elif key in self.applied:
                if get_path(data, path) == self.applied[key]:
                    del_path(data, path)
                del self.applied[key]
        return data

    # ---------- choices: memory layer and prompt cache ----------
    def choose(self, current: str, options: dict, default: str, title: str, flag: str) -> str:
        if current in options:
            return current
        if sys.stdin.isatty() and sys.stdout.isatty():
            names = list(options)
            self.say(f"{title} (change later with {flag}):")
            for number, name in enumerate(names, 1):
                self.say(f"  {number}. {options[name]}{'  [default]' if name == default else ''}")
            answer = input("Choose a number: ").strip()
            if answer.isdigit() and 1 <= int(answer) <= len(names):
                return names[int(answer) - 1]
        return default

    def resolve_choices(self) -> None:
        detected = ("ai-memory" if shutil.which("ai-memory") else
                    "optmem" if os.path.isfile(os.path.join(self.optmem_home, "memo")) else "none")
        self.memory = self.choose(self.memory, MEMORY_LAYERS, detected, "Memory layer", "--memory")
        self.cache = self.choose(self.cache, CACHE_MODES, "default", "Prompt cache", "--cache")
        self.say(f"Memory layer: {self.memory}\nPrompt cache: {self.cache}")

    def save_choices(self) -> None:
        if not self.dry:
            write_json_atomic(CHOICES_FILE, {"memory": self.memory, "cache": self.cache, "applied": self.applied})

    # ---------- memory layer ----------
    def instructions(self) -> None:
        """Pick the file agents load. With a memory layer, Codex, Copilot and opencode get a generated
        AGENTS.md plus the layer; Claude Code imports the layer next to AGENTS.md instead."""
        self.say("Memory layer")
        layer_file, combined = os.path.join(LOCAL, "memory.md"), os.path.join(LOCAL, "AGENTS.md")
        layer = self.memory_layer()
        if layer is None:
            for path in (layer_file, combined):
                if os.path.isfile(path):
                    self.act(f"remove {path}", os.remove, path)
            self.say("  none: agents load ~/.agents/AGENTS.md only")
            return
        self.write_text(layer_file, layer, keep_old=False)
        self.write_text(combined, read(self.agents_md).rstrip("\n") + "\n\n" + layer, keep_old=False)
        self.agents_md = combined

    def memory_layer(self):
        if self.memory == "ai-memory":
            if not shutil.which("ai-memory"):
                self.say("  note: ai-memory is not on PATH yet; install it (README, step 9) for these rules to work")
            return read(os.path.join(HARNESS, "memory", "ai-memory.md"))
        if self.memory == "optmem":
            return self.optmem_layer()
        return None

    def optmem_layer(self) -> str:
        placeholder = "## Memory\n\n(the OptMem block that `memo init` prints)\n"
        memo = os.path.join(self.optmem_home, "memo")
        store = os.path.expanduser(os.environ.get("MEMORY_DIR") or os.path.join(self.optmem_home, "memory"))
        if not os.path.isfile(memo):
            if self.dry:
                self.say(f"  would download OptMem {OPTMEM_COMMIT[:7]} to {memo}")
                return placeholder
            self.download_optmem(memo)
        else:
            self.say(f"  ok: {memo} (update OptMem with its own installer)")
        if self.dry and not os.path.isdir(store):
            self.say(f"  would run: memo init (creates {store})")
            return placeholder
        result = subprocess.run([self.python, memo, "init"], capture_output=True, timeout=60)
        out = result.stdout.decode("utf-8", "replace").replace("\r\n", "\n")
        start = out.find("## Memory")
        if result.returncode != 0 or start < 0:
            sys.exit(f"OptMem's `memo init` failed:\n{out}{result.stderr.decode('utf-8', 'replace')}")
        block = out[start:].rstrip() + "\n"
        if IS_WINDOWS:  # the script has no .exe; run it through Python in every shell
            tool = block.split("`", 2)[1]
            block = block.replace(f"`{tool}", f'`python "{memo.replace(os.sep, "/")}"')
        return block

    def download_optmem(self, memo: str) -> None:
        url = os.environ.get("AGENTS_HARNESS_OPTMEM_URL", OPTMEM_URL)
        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                data = response.read()
        except (OSError, ValueError) as error:
            sys.exit(f"Could not download OptMem from {url}: {error}\n"
                     "Install it with its own installer (github.com/VictorTaelin/OptMem), then run this again.")
        if hashlib.sha256(data).hexdigest() != OPTMEM_SHA256:
            sys.exit(f"The OptMem download from {url} does not match the pinned checksum; nothing was installed.")
        os.makedirs(os.path.dirname(memo), exist_ok=True)
        with open(memo + ".new", "wb") as handle:
            handle.write(data)
        os.replace(memo + ".new", memo)
        os.chmod(memo, 0o755)
        self.say(f"  download OptMem {OPTMEM_COMMIT[:7]} to {memo}")

    # ---------- prompt cache ----------
    def no_cache_setting(self, agent: str) -> None:
        if self.cache != "default":
            self.say(f"  cache: {agent} has no client setting for this; the provider manages the cache lifetime")

    def opencode_cache(self) -> None:
        wanted = {"providers.anthropic.settings.cache.ttl": "1h" if self.cache == "long" else None,
                  "providers.openai.settings.cache.ttl": "12h" if self.cache == "long" else None,
                  "warming": True if self.cache == "warm" else None}
        if self.cache == "default" and not any(k.startswith("opencode:") for k in self.applied):
            return
        if self.cache != "default":
            version = opencode_version()
            if version is None:
                self.say("  cache: skip, opencode not found")
                return
            if version < 2:
                self.say(f"  cache: skip, cache lifetime and warming settings need opencode 2 or later (found {version})")
                return
        path = os.path.join(self.opencode_home, "opencode.json")
        snippet = {}
        for dotted, value in wanted.items():
            if value is not None:
                set_path(snippet, dotted.split("."), value)
        manual = f"  cache: add this to your opencode config by hand: {json.dumps(snippet)}" if snippet else \
            "  cache: remove the harness cache settings from your opencode config by hand"
        if os.path.isfile(os.path.join(self.opencode_home, "opencode.jsonc")):
            self.say("  cache: opencode.jsonc may hold comments, so the installer leaves it alone.")
            self.say(manual)
            return
        try:
            existing = load_json(path)
        except ValueError:
            self.say(f"  cache: could not parse {path}.")
            self.say(manual)
            return
        merged = self.manage(copy.deepcopy(existing), "opencode", wanted)
        if merged == existing:
            self.say(f"  ok: {path}")
            return
        if not existing:
            merged = {"$schema": "https://opencode.ai/config.json", **merged}
        self.snapshot(path)
        self.act(f"set prompt-cache options in {path}", write_json_atomic, path, merged)

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
        self.link_file(self.agents_md, os.path.join(codex_home, "AGENTS.md"))
        if os.path.exists(os.path.join(codex_home, "AGENTS.override.md")):
            self.say("  WARNING: AGENTS.override.md exists and replaces AGENTS.md; merge it into ~/.agents/AGENTS.md.")
        self.say("  skills: read natively from ~/.agents/skills")
        self.merge_settings(os.path.join(codex_home, "hooks.json"), self.codex_hooks())
        self.no_cache_setting("Codex")

    def claude(self) -> None:
        self.say("Claude Code")
        claude_dir = os.path.join(HOME, ".claude")
        bridge = read(os.path.join(HARNESS, "adapters", "claude", "CLAUDE.md"))
        existing = os.path.join(claude_dir, "CLAUDE.md")
        if self.memory != "none":
            bridge += "@~/.agents/local/memory.md\n"
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
        self.merge_settings(os.path.join(claude_dir, "settings.json"), settings, "claude",
                            {"promptCacheTtl": "1h" if self.cache == "long" else None})
        if self.cache == "warm":
            self.say("  cache: Claude Code has no cache warming; subscriptions already get a 1-hour cache, "
                     "and --cache long sets it for API keys")

    def copilot(self) -> None:
        self.say("GitHub Copilot")
        self.link_file(self.agents_md, os.path.join(self.copilot_home, "copilot-instructions.md"))
        self.say("  skills: read natively from ~/.agents/skills")
        hooks_file = os.path.join(self.copilot_home, "hooks", "agents-harness.json")
        self.write_text(hooks_file, json.dumps(self.copilot_hooks(), indent=2) + "\n")
        self.no_cache_setting("GitHub Copilot")

    def opencode_plugin(self) -> str:
        template = read(os.path.join(HARNESS, "adapters", "opencode", "agents-harness.js"))
        return (template.replace("__PYTHON__", json.dumps(self.python))
                .replace("__HOOKS__", json.dumps(os.path.join(HARNESS, "hooks"))))

    def opencode(self) -> None:
        self.say("opencode")
        self.link_file(self.agents_md, os.path.join(self.opencode_home, "AGENTS.md"))
        self.say("  skills: read natively from ~/.agents/skills")
        self.write_text(os.path.join(self.opencode_home, "plugins", "agents-harness.js"), self.opencode_plugin())
        self.opencode_cache()

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
        self.install_opencode_skills()

    def install_opencode_skills(self) -> None:
        if not shutil.which("opencode"):
            self.say("  skip: opencode not found")
            return
        if os.path.isdir(os.path.join(self.opencode_home, "skills", "tdd")):
            self.say("  ok: opencode skills copied (update with: npx skills update --global)")
            return
        npx = shutil.which("npx")
        command = " ".join(f"'{a}'" if a == "*" else a for a in ["npx", *OPENCODE_SKILLS_CMD])
        if not npx:
            self.say(f"  skip: npx not found; for opencode run: {command}")
            return
        if self.dry:
            self.say(f"  would run: {command}")
            return
        try:
            result = subprocess.run([npx, "--yes", *OPENCODE_SKILLS_CMD], capture_output=True,
                                    stdin=subprocess.DEVNULL, timeout=600)
            ok = result.returncode == 0
        except (OSError, subprocess.SubprocessError):
            ok = False
        self.say(f"  {'ran' if ok else 'FAILED'}: {command}")

    def installed(self, exe: str) -> bool:
        try:
            result = subprocess.run([exe, "plugin", "list"], capture_output=True, timeout=60)
            return PLUGIN.encode() in result.stdout
        except (OSError, subprocess.SubprocessError):
            return False

    def run(self) -> None:
        self.check_location()
        self.say(f"Harness: {HARNESS}\nPython for hooks: {self.python}")
        self.resolve_choices()
        self.instructions()
        self.codex()
        self.claude()
        self.copilot()
        self.opencode()
        if self.plugins:
            self.install_plugins()
        self.save_choices()
        self.say("")
        if self.copied_files:
            self.say("Note: this Windows account cannot create file symlinks, so these are copies of "
                     f"{self.agents_md}; run the installer again after editing or pulling AGENTS.md:")
            for path in self.copied_files:
                self.say(f"  {path}")
            self.say("(Turn on Windows Developer Mode to get real links instead.)")
        if self.memory != "none":
            self.say(f"Note: with a memory layer, Codex, Copilot and opencode load {self.agents_md}, "
                     "generated from AGENTS.md and the layer; run the installer again after editing AGENTS.md.")
        self.say("Next: trust the hooks (Codex: /hooks), then restart Claude Code, Codex, Copilot and opencode.")
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


def get_path(data: dict, path: list):
    for key in path:
        if not isinstance(data, dict) or key not in data:
            return None
        data = data[key]
    return data


def set_path(data: dict, path: list, value) -> None:
    for key in path[:-1]:
        if not isinstance(data.get(key), dict):
            data[key] = {}
        data = data[key]
    data[path[-1]] = value


def del_path(data: dict, path: list) -> None:
    """Remove a nested key, then any parents it leaves empty."""
    parents = []
    for key in path[:-1]:
        parents.append((data, key))
        data = data[key]
    del data[path[-1]]
    for parent, key in reversed(parents):
        if parent[key]:
            break
        del parent[key]


def opencode_version():
    exe = shutil.which("opencode")
    if not exe:
        return None
    try:
        result = subprocess.run([exe, "--version"], capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    digits = result.stdout.decode("utf-8", "replace").strip().lstrip("v").split(".")[0]
    return int(digits) if digits.isdigit() else None


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
    parser = argparse.ArgumentParser(description="Install the agent harness for Claude Code, Codex, Copilot and opencode.")
    parser.add_argument("--dry-run", action="store_true", help="show what would change without changing it")
    parser.add_argument("--no-plugins", action="store_true", help="skip the mattpocock skills plugin")
    parser.add_argument("--memory", choices=list(MEMORY_LAYERS), help="memory layer (remembered for later runs)")
    parser.add_argument("--cache", choices=list(CACHE_MODES), help="prompt-cache mode (remembered for later runs)")
    parser.add_argument("--reconfigure", action="store_true", help="ask again for the remembered choices")
    args = parser.parse_args()
    Installer(args.dry_run, not args.no_plugins, args.memory, args.cache, args.reconfigure).run()


if __name__ == "__main__":
    main()
