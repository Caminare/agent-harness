"""Hook tests with Claude Code, Codex and GitHub Copilot payloads. Runs on Windows and Unix.

    python -m unittest discover -s tests -v
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

HOOKS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hooks")
IS_WINDOWS = os.name == "nt"


def call(hook: str, payload, env=None):
    data = payload if isinstance(payload, str) else json.dumps(payload)
    result = subprocess.run([sys.executable, os.path.join(HOOKS, hook)], input=data.encode("utf-8"),
                            capture_output=True, env={**os.environ, **(env or {})}, timeout=60)
    return result.returncode, result.stdout.decode("utf-8", "replace"), result.stderr.decode("utf-8", "replace")


def shell(cmd: str, tool: str = "Bash"):
    return {"tool_name": tool, "tool_input": {"command": cmd}}


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def new_repo(base: str, name: str) -> str:
    path = os.path.join(base, name)
    os.makedirs(os.path.join(path, ".agents"))
    git(path, "init", "-q")
    git(path, "config", "user.email", "t@example.com")
    git(path, "config", "user.name", "t")
    git(path, "config", "core.autocrlf", "false")
    return path


def write(path: str, text: str, executable: bool = False) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    if executable:
        os.chmod(path, 0o755)


class Guard(unittest.TestCase):
    def assertBlocked(self, payload, label=""):
        code, _, err = call("guard.py", payload)
        self.assertEqual(code, 2, f"should block {label or payload}: {err}")

    def assertAllowed(self, payload, label=""):
        code, _, err = call("guard.py", payload)
        self.assertEqual(code, 0, f"should allow {label or payload}: {err}")

    def test_blocks_destructive_unix_commands(self):
        for cmd in ["git push --force origin main", "git push -f", "git push origin +main",
                    "git push --force-with-lease", "git reset --hard HEAD~1", "git clean -fd",
                    "git branch -D feature", "rm -rf /", "rm -rf ~", "rm -fr *", "cd x && git reset --hard",
                    "rm -rf /*", "rm -rf ~/*", "rm -Rf ~", "rm -r -f /", "rm -rf -- ~", 'rm -rf "$HOME"',
                    "git -C repo push --force", "sudo rm -rf /", "git push origin main --force",
                    "git branch --delete --force x", "echo X > .env", "cp .env backup.txt",
                    "grep KEY .env.production", "cat .env", "cat src/.env.local", "code-review-graph build"]:
            with self.subTest(cmd=cmd):
                self.assertBlocked(shell(cmd), cmd)

    def test_allows_routine_unix_commands(self):
        for cmd in ["git push origin feature", "git reset HEAD file", "git branch -d merged", "rm -rf build",
                    "rm -rf ./node_modules", "git clean -n", "git commit -m 'fix: x'", "git log --format=%f",
                    "git checkout -b clean-up -f", "git commit -m 'docs: explain reset --hard'",
                    "grep -rn code-review-graph docs", "echo .env >> .gitignore", "cp .env.example .env",
                    "docker compose --env-file .env up", "dotnet test --filter Cart", "flutter test",
                    "cat .env.example", "pipx install code-review-graph && code-review-graph install --platform codex",
                    "echo 'unbalanced"]:
            with self.subTest(cmd=cmd):
                self.assertAllowed(shell(cmd), cmd)

    def test_blocks_destructive_powershell(self):
        for cmd in ["Remove-Item -Recurse -Force C:\\", "Remove-Item C:\\* -Recurse", "rm -r -fo $HOME",
                    "Remove-Item -Path $env:USERPROFILE -Recurse -Force", "ri ~ -Recurse",
                    "cmd /c rd /s /q C:\\", "rd /s /q %USERPROFILE%", "Get-Content .env",
                    "gc .\\config\\.env.production", "Copy-Item .env C:\\temp\\x.txt", "git push --force"]:
            with self.subTest(cmd=cmd):
                self.assertBlocked(shell(cmd, "powershell"), cmd)

    def test_allows_routine_powershell(self):
        for cmd in ["Remove-Item -Recurse -Force .\\bin", "Remove-Item -Force *.log", "rm .\\obj -Recurse",
                    "Get-Content .env.example", "dotnet test", "Copy-Item .env.example .env",
                    "Remove-Item -Force C:\\temp\\file.txt"]:
            with self.subTest(cmd=cmd):
                self.assertAllowed(shell(cmd, "powershell"), cmd)

    def test_secret_files_in_edit_and_read_tools(self):
        self.assertBlocked({"tool_name": "Edit", "tool_input": {"file_path": "/repo/.env"}})
        self.assertBlocked({"tool_name": "Write", "tool_input": {"file_path": "/repo/certs/server.pem"}})
        self.assertBlocked({"tool_name": "Read", "tool_input": {"file_path": "/repo/.env.production"}})
        self.assertBlocked({"tool_name": "Edit", "tool_input": {"file_path": "C:\\repo\\.env"}})
        self.assertAllowed({"tool_name": "Write", "tool_input": {"file_path": "/repo/.env.example"}})
        self.assertAllowed({"tool_name": "Write", "tool_input": {"file_path": "/repo/id_rsa.pub"}})
        self.assertAllowed({"tool_name": "Read", "tool_input": {"file_path": "/repo/src/env.ts"}})

    def test_codex_apply_patch(self):
        patch = "*** Begin Patch\n*** Update File: config/.env\n@@\n-A=1\n+A=2\n*** End Patch"
        self.assertBlocked({"tool_name": "apply_patch", "tool_input": {"command": patch}})
        self.assertAllowed({"tool_name": "apply_patch",
                            "tool_input": {"command": "*** Begin Patch\n*** Update File: src/app.ts\n*** End Patch"}})

    def test_copilot_payload_shapes(self):
        self.assertBlocked({"toolName": "bash", "toolArgs": json.dumps({"command": "git reset --hard"})})
        self.assertBlocked({"toolName": "powershell", "toolArgs": {"command": "Remove-Item -Recurse C:\\"}})
        self.assertBlocked({"tool_name": "edit", "tool_input": {"path": "/repo/.env"}})
        self.assertBlocked({"tool_name": "view", "tool_input": {"path": "/repo/.env"}})
        self.assertBlocked({"tool_name": "create", "tool_input": {"path": "/repo/key.pem"}})
        self.assertAllowed({"toolName": "bash", "toolArgs": json.dumps({"command": "git status"})})
        self.assertAllowed({"tool_name": "edit", "tool_input": {"path": "/repo/src/a.ts"}})

    def test_tolerates_odd_payloads(self):
        for payload in ["not json", "[1,2]", json.dumps({"tool_name": "Bash", "tool_input": 5}),
                        json.dumps({"toolName": "bash", "toolArgs": "rm -rf /"})]:
            with self.subTest(payload=payload):
                code, _, _ = call("guard.py", payload)
                self.assertIn(code, (0, 2))
        self.assertEqual(call("guard.py", "not json")[0], 0)


class Format(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = {"XDG_CACHE_HOME": os.path.join(self.tmp.name, "cache")}
        self.repo = new_repo(self.tmp.name, "repo")
        os.makedirs(os.path.join(self.repo, "src"))
        self.file = os.path.join(self.repo, "src", "a.txt")
        write(self.file, "x\n")

    def tearDown(self):
        self.tmp.cleanup()

    def payload(self, tool="Write", **extra):
        key = "path" if tool in ("edit", "create") else "file_path"
        return {"cwd": self.repo, "session_id": "s1", "tool_name": tool, "tool_input": {key: self.file}, **extra}

    def formatter(self, body_sh: str, body_ps1: str):
        write(os.path.join(self.repo, ".agents", "format.sh"), "#!/usr/bin/env bash\n" + body_sh, True)
        write(os.path.join(self.repo, ".agents", "format.ps1"), body_ps1)

    def test_repo_formatter_runs_for_each_agent_shape(self):
        self.formatter('for f in "$@"; do echo formatted >> "$f"; done\n',
                       'foreach ($f in $args) { Add-Content -Path $f -Value formatted }\n')
        patch = {"cwd": self.repo, "session_id": "s1", "tool_name": "apply_patch",
                 "tool_input": {"command": "*** Begin Patch\n*** Update File: src/a.txt\n*** End Patch"}}
        for payload in [self.payload("Write"), patch, self.payload("edit")]:
            self.assertEqual(call("format.py", payload, self.env)[0], 0)
        with open(self.file, encoding="utf-8") as handle:
            self.assertGreaterEqual(handle.read().count("formatted"), 1)

    def test_failing_formatter_feeds_back(self):
        self.formatter('echo "parse error" >&2; exit 1\n', 'Write-Error "parse error"; exit 1\n')
        code, _, err = call("format.py", self.payload("Edit"), self.env)
        self.assertEqual(code, 2)
        self.assertIn("parse error", err)

    def test_no_formatter_is_silent(self):
        self.assertEqual(call("format.py", self.payload("Edit"), self.env)[0], 0)


class Verify(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = {"XDG_CACHE_HOME": os.path.join(self.tmp.name, "cache")}
        self.repo = new_repo(self.tmp.name, "v")
        self.file = os.path.join(self.repo, "f.txt")
        write(self.file, "a\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "init")
        self.stop = {"session_id": "s1", "cwd": self.repo, "hook_event_name": "Stop", "stop_hook_active": False}
        self.runs = os.path.join(self.tmp.name, "runs")

    def tearDown(self):
        self.tmp.cleanup()

    def check(self, sh: str, ps1: str):
        write(os.path.join(self.repo, ".agents", "verify.sh"), "#!/usr/bin/env bash\n" + sh, True)
        write(os.path.join(self.repo, ".agents", "verify.ps1"), ps1)

    def count_runs(self) -> int:
        with open(self.runs, encoding="utf-8") as handle:
            return handle.read().count("ran")

    def agent_edits(self, text="b\n"):
        with open(self.file, "a", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        payload = {"session_id": "s1", "cwd": self.repo, "tool_name": "Edit", "tool_input": {"file_path": self.file}}
        self.assertEqual(call("format.py", payload, self.env)[0], 0)

    def decision(self, payload=None):
        code, out, err = call("verify.py", payload or self.stop, self.env)
        self.assertEqual(code, 0, err)
        return json.loads(out) if out.strip() else None

    def test_failing_check_keeps_agent_working(self):
        self.check('echo "1 test failed: CartTotal"; exit 1\n', 'Write-Output "1 test failed: CartTotal"; exit 1\n')
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "check")
        self.assertIsNone(self.decision(), "clean tree is skipped")
        with open(self.file, "a", encoding="utf-8") as handle:
            handle.write("user edit\n")
        self.assertIsNone(self.decision(), "user's own edits do not arm the check")
        self.agent_edits()
        self.assertIsNone(self.decision({**self.stop, "session_id": "other"}), "other sessions unaffected")
        result = self.decision()
        self.assertEqual(result["decision"], "block")
        self.assertIn("CartTotal", result["reason"])
        self.assertIsNone(self.decision({**self.stop, "stop_hook_active": True}), "no loop")
        self.assertIsNone(self.decision({**self.stop, "stopHookActive": True}), "no loop, camelCase")

    def test_passing_check_is_cached_until_tree_changes(self):
        log = self.runs.replace("\\", "/")
        self.check(f'echo ran >> "{log}"; exit 0\n', f'Add-Content -Path "{log}" -Value ran; exit 0\n')
        self.agent_edits()
        self.assertIsNone(self.decision())
        self.assertIsNone(self.decision())
        self.assertEqual(self.count_runs(), 1)
        self.agent_edits("c\n")
        self.assertIsNone(self.decision())
        self.assertEqual(self.count_runs(), 2)

    def test_timeout_kills_lingering_children(self):
        self.check("sleep 60 &\nsleep 60\n",
                   "Start-Process -NoNewWindow powershell -ArgumentList '-Command','Start-Sleep 60'; Start-Sleep 60\n")
        self.agent_edits()
        start = time.time()
        code, out, err = call("verify.py", self.stop, {**self.env, "AGENTS_VERIFY_TIMEOUT": "3"})
        self.assertEqual(code, 0, err)
        self.assertIn("timed out", json.loads(out)["reason"])
        self.assertLess(time.time() - start, 30)

    def test_no_check_or_bad_input_passes(self):
        self.assertIsNone(self.decision())
        self.assertEqual(call("verify.py", "not json", self.env)[0], 0)


if __name__ == "__main__":
    unittest.main()
