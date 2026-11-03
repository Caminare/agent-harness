#!/usr/bin/env python3
"""Stop hook for Claude Code, Codex and GitHub Copilot: the verification loop.

When the agent tries to finish a turn, run the repository's `.agents/verify.sh`
or `.agents/verify.ps1`, but only if the agent edited files in this repository
during this session (recorded by format.py) and the working tree changed since
the last passing run. On failure it prints {"decision": "block", "reason": ...}
on stdout, which all three agents read as "keep working on this". On success it
prints nothing.
"""
import hashlib
import json
import os
import sys

sys.dont_write_bytecode = True  # keep ~/.agents free of __pycache__

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import (CACHE_DIR, edit_marker, git, normalize_event, read_event,  # noqa: E402
                     repo_root, repo_script, run)

TIMEOUT_SECONDS = int(os.environ.get("AGENTS_VERIFY_TIMEOUT", "280"))
# .NET build servers inherit the output pipes and outlive `dotnet build`; disable them.
CHILD_ENV = {**os.environ, "MSBUILDDISABLENODEREUSE": "1", "DOTNET_CLI_USE_MSBUILD_SERVER": "0",
             "DOTNET_CLI_TELEMETRY_OPTOUT": "1", "CI": os.environ.get("CI", "1")}


def tree_fingerprint(root: str) -> str:
    digest = hashlib.sha256(git(["diff", "HEAD", "--binary"], root).encode())
    for path in sorted(git(["ls-files", "--others", "--exclude-standard"], root).splitlines()):
        full = os.path.join(root, path)
        digest.update(path.encode())
        if os.path.isfile(full):
            with open(full, "rb") as handle:
                digest.update(hashlib.sha256(handle.read()).digest())
    return digest.hexdigest()


def keep_working(reason: str) -> None:
    sys.stdout.write(json.dumps({"decision": "block", "reason": reason}))
    sys.exit(0)


def main() -> None:
    event = read_event()
    if event is None:
        sys.exit(0)
    e = normalize_event(event)
    if e["stop_hook_active"]:
        sys.exit(0)

    root = repo_root(e["cwd"])
    if not root:
        sys.exit(0)
    command = repo_script(root, "verify")
    if not command or not os.path.exists(edit_marker(e["session_id"], root)):
        sys.exit(0)  # no check in this repo, or the agent has not edited it this session
    try:
        if not git(["status", "--porcelain"], root).strip():
            sys.exit(0)
        fingerprint = tree_fingerprint(root)
    except (RuntimeError, OSError):
        sys.exit(0)

    os.makedirs(CACHE_DIR, exist_ok=True)
    cache_file = os.path.join(CACHE_DIR, "verified-" + hashlib.sha256(
        os.path.normcase(root).encode()).hexdigest()[:16])
    try:
        with open(cache_file, encoding="utf-8") as handle:
            if handle.read().strip() == fingerprint:
                sys.exit(0)
    except OSError:
        pass

    code, output = run(command, root, TIMEOUT_SECONDS, env=CHILD_ENV)
    if code is None:
        keep_working(f"The repository check (.agents/verify) timed out after {TIMEOUT_SECONDS}s. "
                     "Make it faster (only affected tests) or tell the user it could not run.")
    if code == 0:
        with open(cache_file, "w", encoding="utf-8") as handle:
            handle.write(fingerprint)
        sys.exit(0)

    tail = "\n".join(output.strip().splitlines()[-60:])
    keep_working(f"The repository check (.agents/verify) failed with exit code {code}. Fix the cause "
                 f"before finishing, or tell the user why you cannot. Last output:\n{tail}")


if __name__ == "__main__":
    main()
