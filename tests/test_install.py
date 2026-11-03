"""Installer tests: full install into a throwaway home directory, on Windows and Unix.

    python -m unittest discover -s tests -v
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IS_WINDOWS = os.name == "nt"
BLOCKED_PAYLOAD = json.dumps({"tool_name": "Bash", "tool_input": {"command": "git push --force"}})


def tree(root: str) -> dict:
    snapshot = {}
    for folder, dirs, files in os.walk(root):
        for name in dirs + files:
            path = os.path.join(folder, name)
            snapshot[os.path.relpath(path, root)] = os.path.isdir(path)
    return snapshot


def read_file(path: str) -> str:
    with open(path, encoding="utf-8") as handle:
        return handle.read()


class Install(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = os.path.join(self.tmp.name, "home user")  # a space, like many Windows profiles
        os.makedirs(self.home)
        self.harness = os.path.join(self.home, ".agents")
        shutil.copytree(REPO, self.harness, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        self.env = {**os.environ, "HOME": self.home, "USERPROFILE": self.home,
                    "PATH": os.path.dirname(sys.executable) + os.pathsep + os.environ.get("PATH", "")}
        for var in ("CODEX_HOME", "COPILOT_HOME", "XDG_CACHE_HOME"):
            self.env.pop(var, None)

    def tearDown(self):
        self.tmp.cleanup()

    def install(self, *args, harness=None):
        script = os.path.join(harness or self.harness, "lib", "install.py")
        result = subprocess.run([sys.executable, script, "--no-plugins", *args], capture_output=True,
                                env=self.env, timeout=120)
        return result.returncode, result.stdout.decode("utf-8", "replace") + result.stderr.decode("utf-8", "replace")

    def path(self, *parts):
        return os.path.join(self.home, *parts)

    def read_json(self, *parts):
        with open(self.path(*parts), encoding="utf-8") as handle:
            return json.load(handle)

    def read(self, *parts):
        with open(self.path(*parts), encoding="utf-8") as handle:
            return handle.read()

    def test_fresh_install_configures_all_three_agents(self):
        code, out = self.install()
        self.assertEqual(code, 0, out)
        agents_md = self.read(".agents", "AGENTS.md")
        self.assertEqual(self.read(".codex", "AGENTS.md"), agents_md)
        self.assertEqual(self.read(".copilot", "copilot-instructions.md"), agents_md)
        self.assertIn("@~/.agents/AGENTS.md", self.read(".claude", "CLAUDE.md"))
        for skill in os.listdir(os.path.join(self.harness, "skills")):
            linked = self.path(".claude", "skills", skill, "SKILL.md")
            self.assertTrue(os.path.isfile(linked), skill)
            self.assertEqual(os.path.normcase(os.path.realpath(linked)),
                             os.path.normcase(os.path.realpath(os.path.join(self.harness, "skills", skill, "SKILL.md"))))
        claude = self.read_json(".claude", "settings.json")
        self.assertEqual(set(claude["hooks"]), {"PreToolUse", "PostToolUse"})
        self.assertIn("Bash(git push *)", claude["permissions"]["ask"])
        codex = self.read_json(".codex", "hooks.json")
        self.assertEqual(set(codex["hooks"]), {"PreToolUse", "PostToolUse"})
        copilot = self.read_json(".copilot", "hooks", "agents-harness.json")
        self.assertEqual(copilot["version"], 1)
        self.assertEqual(set(copilot["hooks"]), {"PreToolUse", "PostToolUse"})

    def test_rerun_changes_nothing(self):
        self.install()
        before = (self.read(".claude", "settings.json"), self.read(".codex", "hooks.json"))
        code, out = self.install()
        self.assertEqual(code, 0, out)
        self.assertNotIn("back up", out)
        self.assertEqual((self.read(".claude", "settings.json"), self.read(".codex", "hooks.json")), before)

    def test_keeps_user_settings_and_replaces_old_harness_hooks(self):
        os.makedirs(self.path(".claude"))
        old_style = {"type": "command", "command": 'python3 "$HOME/.agents/hooks/guard.py"'}
        user_hook = {"type": "command", "command": "rtk hook"}
        with open(self.path(".claude", "settings.json"), "w", encoding="utf-8") as handle:
            json.dump({"model": "opus", "permissions": {"allow": ["Bash(npm test *)"]},
                       "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [user_hook]},
                                                {"matcher": "Bash", "hooks": [old_style]}]}}, handle)
        self.assertEqual(self.install()[0], 0)
        settings = self.read_json(".claude", "settings.json")
        self.assertEqual(settings["model"], "opus")
        self.assertIn("Bash(npm test *)", settings["permissions"]["allow"])
        commands = [h["command"] for e in settings["hooks"]["PreToolUse"] for h in e["hooks"]]
        self.assertIn("rtk hook", commands)
        self.assertEqual(sum("guard.py" in c for c in commands), 1, commands)
        self.assertNotIn(old_style["command"], commands)

    def test_upgrade_removes_the_retired_verify_hook(self):
        os.makedirs(self.path(".claude"))
        os.makedirs(self.path(".codex"))
        retired = {"hooks": [{"type": "command", "command": 'python3 "$HOME/.agents/hooks/verify.py"'}]}
        user_stop = {"hooks": [{"type": "command", "command": "notify-send done"}]}
        for agent, name in ((".claude", "settings.json"), (".codex", "hooks.json")):
            with open(self.path(agent, name), "w", encoding="utf-8") as handle:
                json.dump({"hooks": {"Stop": [retired, user_stop]}}, handle)
        self.assertEqual(self.install()[0], 0)
        for agent, name in ((".claude", "settings.json"), (".codex", "hooks.json")):
            stop = self.read_json(agent, name)["hooks"].get("Stop", [])
            self.assertEqual(stop, [user_stop], agent)

    def test_backs_up_changed_claude_md_and_keeps_rtk(self):
        os.makedirs(self.path(".claude"))
        with open(self.path(".claude", "CLAUDE.md"), "w", encoding="utf-8") as handle:
            handle.write("@~/.agents/AGENTS.md\n@~/notes/personal.md\n")
        open(self.path(".claude", "RTK.md"), "w").close()
        self.assertEqual(self.install()[0], 0)
        self.assertTrue(self.read(".claude", "CLAUDE.md").rstrip().endswith("@RTK.md"))
        backups = [os.path.join(f, n) for f, _, files in os.walk(self.path(".agents-backup")) for n in files]
        self.assertTrue(any("personal.md" in read_file(b) for b in backups if b.endswith("CLAUDE.md")))

    def test_removes_links_to_skills_dropped_from_the_harness(self):
        self.install()
        gone = os.path.join(self.harness, "skills", "dropped-skill")
        os.makedirs(gone)
        self.install()
        self.assertTrue(os.path.isdir(self.path(".claude", "skills", "dropped-skill")))
        shutil.rmtree(gone)
        code, out = self.install()
        self.assertEqual(code, 0, out)
        self.assertFalse(os.path.lexists(self.path(".claude", "skills", "dropped-skill")), out)

    def test_dry_run_changes_nothing(self):
        before = tree(self.home)
        code, out = self.install("--dry-run")
        self.assertEqual(code, 0, out)
        self.assertIn("would", out)
        self.assertEqual(tree(self.home), before)

    def test_refuses_to_run_outside_home_agents(self):
        elsewhere = os.path.join(self.tmp.name, "elsewhere")
        shutil.copytree(self.harness, elsewhere)
        code, out = self.install(harness=elsewhere)
        self.assertNotEqual(code, 0)
        self.assertIn("must live at", out)

    def run_shell(self, shell: list, command: str) -> int:
        result = subprocess.run(shell + [command], input=BLOCKED_PAYLOAD.encode(), capture_output=True,
                                env=self.env, timeout=60)
        return result.returncode

    def test_rendered_hook_commands_run_in_each_agents_shell(self):
        """Run the exact guard command each agent will run, through that agent's shell."""
        self.assertEqual(self.install()[0], 0)
        claude = next(h for e in self.read_json(".claude", "settings.json")["hooks"]["PreToolUse"]
                      for h in e["hooks"] if "guard.py" in h["command"])
        codex = self.read_json(".codex", "hooks.json")["hooks"]["PreToolUse"][0]["hooks"][0]
        copilot = self.read_json(".copilot", "hooks", "agents-harness.json")["hooks"]["PreToolUse"][0]
        powershell = shutil.which("pwsh") or shutil.which("powershell")
        checks = []
        if IS_WINDOWS:
            self.assertEqual(claude.get("shell"), "powershell")
            checks.append(("claude/powershell", [powershell, "-NoProfile", "-Command"], claude["command"]))
            checks.append(("codex/cmd", ["cmd", "/c"], codex["commandWindows"]))
            checks.append(("copilot/powershell", [powershell, "-NoProfile", "-Command"], copilot["powershell"]))
        else:
            checks.append(("claude/sh", ["sh", "-c"], claude["command"]))
            checks.append(("codex/sh", ["sh", "-c"], codex["command"]))
            checks.append(("copilot/bash", ["bash", "-c"], copilot["bash"]))
            if powershell:
                checks.append(("copilot/pwsh", [powershell, "-NoProfile", "-Command"], copilot["powershell"]))
        for label, shell, command in checks:
            with self.subTest(label):
                self.assertEqual(self.run_shell(shell, command), 2, f"{label}: {command}")

    @unittest.skipIf(IS_WINDOWS, "fake CLIs are shell scripts")
    def test_plugin_step_with_fake_clis(self):
        bin_dir = os.path.join(self.tmp.name, "bin")
        os.makedirs(bin_dir)
        log = os.path.join(self.tmp.name, "calls")
        for cli in ("claude", "codex", "copilot"):
            with open(os.path.join(bin_dir, cli), "w") as handle:
                handle.write(f'#!/bin/sh\necho "{cli} $*" >> "{log}"\n'
                             f'[ "$2" = list ] && grep -q "{cli} plugin install\\|{cli} plugin add" "{log}" '
                             '&& echo mattpocock-skills\nexit 0\n')
            os.chmod(os.path.join(bin_dir, cli), 0o755)
        self.env["PATH"] = bin_dir + os.pathsep + self.env["PATH"]
        script = os.path.join(self.harness, "lib", "install.py")
        for _ in range(2):
            subprocess.run([sys.executable, script], env=self.env, capture_output=True, timeout=120, check=True)
        calls = read_file(log)
        self.assertEqual(calls.count("claude plugin install mattpocock-skills@claude-plugins-official"), 1)
        self.assertEqual(calls.count("codex plugin add mattpocock-skills@mattpocock"), 1)
        self.assertEqual(calls.count("copilot plugin install mattpocock-skills@mattpocock"), 1)


if __name__ == "__main__":
    unittest.main()
