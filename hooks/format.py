#!/usr/bin/env python3
"""PostToolUse hook for Claude Code, Codex and GitHub Copilot: format edited files.

Formats the touched files. A repository owns formatting by providing
`.agents/format.sh` or `.agents/format.ps1`, which receives the file paths.
Without one, a built-in formatter runs only where the repository already opts
in: dart format for Dart, prettier when a prettier config exists, csharpier
when it is a configured dotnet tool. Missing formatters are silent; a
formatter that fails (the file may not parse) exits 2 so the agent sees it.
"""
import glob
import json
import os
import shutil
import sys

sys.dont_write_bytecode = True  # keep ~/.agents free of __pycache__

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import (IS_WINDOWS, input_paths, normalize_event, patch_paths, read_event,  # noqa: E402
                     repo_root, repo_script, run)

TIMEOUT_SECONDS = 60


def touched_files(e: dict) -> list:
    if e["kind"] == "edit":
        return input_paths(e["input"])
    if e["kind"] == "patch":
        return patch_paths(str(e["input"].get("command", "") or ""), include_deleted=False)
    return []


def has_prettier_config(root: str) -> bool:
    if glob.glob(os.path.join(root, ".prettierrc*")) or glob.glob(os.path.join(root, "prettier.config.*")):
        return True
    try:
        with open(os.path.join(root, "package.json"), encoding="utf-8") as handle:
            return "prettier" in json.load(handle)
    except (OSError, ValueError):
        return False


def has_csharpier(root: str) -> bool:
    try:
        with open(os.path.join(root, ".config", "dotnet-tools.json"), encoding="utf-8") as handle:
            return "csharpier" in handle.read()
    except OSError:
        return False


def builtin_command(path: str, root: str):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".dart":
        dart = shutil.which("dart")
        if dart:
            return [dart, "format", path]
    if ext in (".ts", ".tsx", ".js", ".jsx", ".json", ".css", ".scss") and has_prettier_config(root):
        bin_dir = os.path.join(root, "node_modules", ".bin")
        for name in (("prettier.cmd", "prettier") if IS_WINDOWS else ("prettier",)):
            candidate = os.path.join(bin_dir, name)
            if os.path.isfile(candidate):
                return [candidate, "--write", path]
    if ext == ".cs" and has_csharpier(root):
        dotnet = shutil.which("dotnet")
        if dotnet:
            return [dotnet, "csharpier", "format", path]
    return None


def main() -> None:
    event = read_event()
    if event is None:
        sys.exit(0)
    e = normalize_event(event)
    cwd = e["cwd"]
    files = [f if os.path.isabs(f) else os.path.join(cwd, f) for f in touched_files(e) if f]
    files = [os.path.normpath(f) for f in files if os.path.isfile(f)]
    root = repo_root(cwd)
    if not files or not root:
        sys.exit(0)

    owned = repo_script(root, "format")
    commands = [owned + files] if owned else [c for c in (builtin_command(f, root) for f in files) if c]

    failures = []
    for cmd in commands:
        code, output = run(cmd, root, TIMEOUT_SECONDS)
        if code not in (0, None, 127):
            failures.append(f"$ {' '.join(cmd)}\n{output[-2000:]}")
    if failures:
        sys.stderr.write("Formatter failed; the edited file may not parse:\n" + "\n".join(failures) + "\n")
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
