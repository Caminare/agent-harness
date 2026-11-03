#!/usr/bin/env python3
"""Stop hook shared by Claude Code and Codex: the verification loop.

When the agent tries to finish a turn, run the repository's executable
`.agents/verify.sh`, but only if the agent edited files in this repository
during this session (recorded by format.py) and the working tree changed
since the last passing run. On failure, exit 2 with the tail of the output
so the agent keeps working on the fix. Prints nothing on success (Codex
rejects plain stdout from Stop hooks).
"""
import hashlib
import json
import os
import signal
import subprocess
import sys

TIMEOUT_SECONDS = int(os.environ.get("AGENTS_VERIFY_TIMEOUT", "280"))
CACHE_DIR = os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")),
                         "agents-harness")
# .NET build servers inherit the output pipes and outlive `dotnet build`; disable them.
CHILD_ENV = {**os.environ, "MSBUILDDISABLENODEREUSE": "1", "DOTNET_CLI_USE_MSBUILD_SERVER": "0",
             "DOTNET_CLI_TELEMETRY_OPTOUT": "1", "CI": os.environ.get("CI", "1")}


def edit_marker(session_id: str, root: str) -> str:
    key = hashlib.sha256(f"{session_id}\0{root}".encode()).hexdigest()[:24]
    return os.path.join(CACHE_DIR, f"edited-{key}")


def git(args: list, cwd: str) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode(errors="replace"))
    return result.stdout.decode(errors="replace")


def tree_fingerprint(root: str) -> str:
    digest = hashlib.sha256(git(["diff", "HEAD", "--binary"], root).encode())
    for path in sorted(git(["ls-files", "--others", "--exclude-standard"], root).splitlines()):
        full = os.path.join(root, path)
        digest.update(path.encode())
        if os.path.isfile(full):
            with open(full, "rb") as handle:
                digest.update(hashlib.sha256(handle.read()).digest())
    return digest.hexdigest()


def run_verify(script: str, root: str):
    process = subprocess.Popen([script], cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               stdin=subprocess.DEVNULL, text=True, env=CHILD_ENV,
                               start_new_session=True)
    try:
        output, _ = process.communicate(timeout=TIMEOUT_SECONDS)
        return process.returncode, output
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            pass
        process.communicate()
        return None, ""


def main() -> None:
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)
    if not isinstance(event, dict) or event.get("stop_hook_active"):
        sys.exit(0)

    try:
        root = git(["rev-parse", "--show-toplevel"], event.get("cwd") or os.getcwd()).strip()
        script = os.path.join(root, ".agents", "verify.sh")
        if not os.access(script, os.X_OK):
            sys.exit(0)
        if not os.path.exists(edit_marker(str(event.get("session_id", "")), root)):
            sys.exit(0)  # the agent has not edited this repo in this session
        if not git(["status", "--porcelain"], root).strip():
            sys.exit(0)
        fingerprint = tree_fingerprint(root)
    except (RuntimeError, OSError, subprocess.SubprocessError):
        sys.exit(0)

    os.makedirs(CACHE_DIR, exist_ok=True)
    cache_file = os.path.join(CACHE_DIR, "verified-" + hashlib.sha256(root.encode()).hexdigest()[:16])
    if os.path.exists(cache_file) and open(cache_file).read().strip() == fingerprint:
        sys.exit(0)

    code, output = run_verify(script, root)
    if code is None:
        sys.stderr.write(f".agents/verify.sh timed out after {TIMEOUT_SECONDS}s. "
                         "Make it faster (only affected tests) or tell the user it could not run.\n")
        sys.exit(2)
    if code == 0:
        with open(cache_file, "w") as handle:
            handle.write(fingerprint)
        sys.exit(0)

    tail = "\n".join(output.strip().splitlines()[-60:])
    sys.stderr.write(f".agents/verify.sh failed (exit {code}). Fix the cause before finishing, "
                     f"or tell the user why you cannot. Last output:\n{tail}\n")
    sys.exit(2)


if __name__ == "__main__":
    main()
