---
name: setup-repo
description: Prepare the current repository for coding agents - write or update its AGENTS.md from the real code, with verified build and test commands, and migrate any CLAUDE.md or other agents' instruction files. Use when the user asks to set up, onboard, or initialize a repo for agents.
disable-model-invocation: true
---

# Set up a repository for agents

Optional and per repository. The personal harness already works everywhere; this adds the project facts that make agents reliable in this repo. Change nothing before the user approves the proposal in step 3.

## 1. Read the repository, do not guess
1. Find the stack and entry points: solution and project files, `pubspec.yaml`, `package.json`, `Makefile`, CI workflow files, README, docker compose files.
2. Find the real commands: build, full test run, single test, lint or analyze, format. CI files are the most reliable source. Run each command once to confirm it works and how long it takes.
3. Note what an agent could not infer: services that must be running, environment setup (variable names only, never values), generated or vendored code, applied migrations, conventions that differ from defaults, known traps.
4. Check for existing instruction files: `AGENTS.md`, `CLAUDE.md`, `.claude/CLAUDE.md`, `CLAUDE.local.md`, `.github/copilot-instructions.md`, `.github/instructions/`, `.cursorrules`.
5. Note which systems contributors use (Windows, macOS, Linux); give commands that work on each, or both forms.

## 2. Draft the files
1. **`AGENTS.md`** at the repo root, following `~/.agents/templates/project/AGENTS.md`: commands, architecture (only what folder names do not say), conventions, boundaries, pitfalls. Under about 150 lines. No personal preferences; those live in `~/.agents/AGENTS.md`.
2. **Migration:** a project `CLAUDE.md`, `.claude/CLAUDE.md` or `CLAUDE.local.md` makes Claude Code ignore `AGENTS.md`, and Copilot reads both and combines them, so duplicates conflict. Move their project facts into `AGENTS.md` and propose deleting them. Do the same for `.github/copilot-instructions.md` and other tools' rule files; keep `.github/instructions/*.instructions.md` only for path-specific rules.
3. **Project skills, if any:** keep them in `.agents/skills/<name>`, which Codex and Copilot read. Claude Code reads only `.claude/skills/`, so add a relative symlink `.claude/skills/<name> -> ../../.agents/skills/<name>`. Windows clones need `git config core.symlinks true` (and Developer Mode) for that link; say so in `AGENTS.md`.

## 3. Propose, then apply
Show the drafted files (or diffs against existing ones) and how long each command took, and wait for approval. Do not commit; propose a commit message per the Git rules.

## 4. Hand off to the mattpocock setup
If the mattpocock skills are installed and the repo has not been configured for them, offer to run `setup-matt-pocock-skills` next. It sets the issue tracker, triage labels, and docs layout that `to-spec`, `to-tickets`, `triage`, and `grill-with-docs` rely on.
