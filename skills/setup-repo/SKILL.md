---
name: setup-repo
description: Prepare the current repository for coding agents - write or update its AGENTS.md from the real code, create a fast .agents/verify.sh pass/fail check, and migrate any CLAUDE.md. Use when the user asks to set up, onboard, or initialize a repo for agents.
disable-model-invocation: true
---

# Set up a repository for agents

Optional and per repository. The personal harness already works everywhere; this adds the project facts and the verification check that make agents reliable in this repo. Change nothing before the user approves the proposal in step 3.

## 1. Read the repository, do not guess
1. Find the stack and entry points: solution and project files, `pubspec.yaml`, `package.json`, `Makefile`, CI workflow files, README, docker compose files.
2. Find the real commands: build, full test run, single test, lint or analyze, format. CI files are the most reliable source. Run each command once to confirm it works and how long it takes.
3. Note what an agent could not infer: services that must be running, environment setup (variable names only, never values), generated or vendored code, applied migrations, conventions that differ from defaults, known traps.
4. Check for existing instruction files: `AGENTS.md`, `CLAUDE.md`, `.claude/CLAUDE.md`, `CLAUDE.local.md`, `.cursorrules`, `.github/copilot-instructions.md`.

## 2. Draft the files
1. **`AGENTS.md`** at the repo root, following `~/.agents/templates/project/AGENTS.md`: commands, architecture (only what folder names do not say), conventions, boundaries, pitfalls. Under about 150 lines. No personal preferences; those live in `~/.agents/AGENTS.md`.
2. **`.agents/verify.sh`**, executable, starting from `~/.agents/templates/project/.agents/verify.sh` but with this repo's real commands. It must exit non-zero on failure and finish well under 280 seconds; prefer build, analyzers, and the fast or affected test projects over the full suite. If nothing can be verified, say so instead of writing an empty check.
3. **Migration:** a project `CLAUDE.md`, `.claude/CLAUDE.md` or `CLAUDE.local.md` makes Claude Code ignore `AGENTS.md`. Move their project facts into `AGENTS.md` and propose deleting them. Fold other tools' rule files in the same way.
4. **Project skills, if any:** Codex reads `.agents/skills/`, Claude Code reads `.claude/skills/`. Keep the real folder in `.agents/skills/<name>` and add a relative symlink `.claude/skills/<name> -> ../../.agents/skills/<name>`.

## 3. Propose, then apply
Show the drafted files (or diffs against existing ones) and the time `verify.sh` took, and wait for approval. After applying, run `.agents/verify.sh` once and report the result. Do not commit; propose a commit message per the Git rules.

## 4. Hand off to the mattpocock setup
If the mattpocock skills are installed and the repo has not been configured for them, offer to run `setup-matt-pocock-skills` next. It sets the issue tracker, triage labels, and docs layout that `to-spec`, `to-tickets`, `triage`, and `grill-with-docs` rely on.
