#!/usr/bin/env bash
# Agent harness installer: one source of truth in ~/.agents, thin links per agent.
# Run once per machine (and again after pulling updates). Repositories need no
# install step; ask the agent to run the setup-repo skill inside one instead.
#
#   ~/.agents/install.sh [--dry-run] [--no-plugins]
#
# Also installs the mattpocock skills plugin for Claude Code and Codex
# (MIT, https://github.com/mattpocock/skills); --no-plugins skips that.
#
# Safe to re-run. Anything it replaces is moved to ~/.agents-backup/<timestamp>/.
set -euo pipefail

HARNESS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="$HOME/.agents-backup/$STAMP"
DRY=0
PLUGINS=1

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1 ;;
    --no-plugins) PLUGINS=0 ;;
    -h|--help) sed -n '2,11p' "$0"; exit 0 ;;
    *) echo "Unknown argument: $1 (supported: --dry-run, --no-plugins)"; exit 1 ;;
  esac
  shift
done

say() { printf '%s\n' "$*"; }
run() { if [ "$DRY" -eq 1 ]; then say "  would run: $*"; else "$@"; fi; }

backup() { # move an existing path out of the way, preserving its relative location
  local path="$1"
  [ -e "$path" ] || [ -L "$path" ] || return 0
  local rel="${path#"$HOME"/}"
  run mkdir -p "$BACKUP/$(dirname "$rel")"
  run mv "$path" "$BACKUP/$rel"
  [ "$DRY" -eq 1 ] || say "  backed up $path"
}

snapshot() { # copy a file into the backup folder without moving it
  local path="$1" rel="${1#"$HOME"/}"
  [ -f "$path" ] || return 0
  run mkdir -p "$BACKUP/$(dirname "$rel")"
  run cp -p "$path" "$BACKUP/$rel"
}

link() { # link <target> <link-path>
  local target="$1" path="$2"
  if [ -L "$path" ] && [ "$(readlink "$path")" = "$target" ]; then
    say "  ok: $path"
    return
  fi
  backup "$path"
  run mkdir -p "$(dirname "$path")"
  run ln -s "$target" "$path"
  [ "$DRY" -eq 1 ] || say "  linked $path -> $target"
}

plugins() {
  say "mattpocock skills plugin"
  for dir in "$HOME/.claude/skills" "$HOME/.agents/skills"; do # loose copies would duplicate the plugin
    for name in tdd grill-me to-spec code-review; do
      if [ -d "$dir/$name" ] && [ ! -L "$dir/$name" ]; then
        say "  WARNING: $dir/$name looks like a copied mattpocock skill; remove copies so each skill loads once."
      fi
    done
  done
  if command -v claude >/dev/null; then
    if claude plugin list 2>/dev/null | grep -q mattpocock-skills; then
      say "  ok: Claude Code plugin installed"
    else
      run claude plugin install mattpocock-skills@claude-plugins-official \
        || say "  WARNING: could not install the Claude Code plugin; run: claude plugin install mattpocock-skills@claude-plugins-official"
    fi
  else
    say "  skip: claude not found"
  fi
  if command -v codex >/dev/null; then
    run codex plugin marketplace add mattpocock/skills || true
    run codex plugin add mattpocock-skills@mattpocock \
      || say "  WARNING: could not install the Codex plugin; run: codex plugin marketplace add mattpocock/skills && codex plugin add mattpocock-skills@mattpocock"
  else
    say "  skip: codex not found"
  fi
}

user_setup() {
  if [ "$HARNESS" != "$HOME/.agents" ]; then
    say "The harness must live at ~/.agents (Codex reads ~/.agents/skills, hooks use \$HOME/.agents)."
    say "Move or clone it there, then re-run: ~/.agents/install.sh"
    exit 1
  fi
  command -v python3 >/dev/null || { say "python3 is required for the hooks."; exit 1; }
  run chmod +x "$HARNESS"/hooks/*.py "$HARNESS"/lib/*.py "$HARNESS"/templates/project/.agents/verify.sh

  say "Codex"
  link "$HARNESS/AGENTS.md" "$HOME/.codex/AGENTS.md"
  if [ -e "$HOME/.codex/AGENTS.override.md" ]; then
    say "  WARNING: ~/.codex/AGENTS.override.md exists and replaces AGENTS.md. Remove it or merge it into ~/.agents/AGENTS.md."
  fi
  say "  skills: read natively from ~/.agents/skills"
  if [ -f "$HOME/.codex/hooks.json" ]; then
    snapshot "$HOME/.codex/hooks.json"
    run python3 "$HARNESS/lib/merge_json.py" "$HOME/.codex/hooks.json" "$HARNESS/adapters/codex/hooks.json" $([ "$DRY" -eq 1 ] && echo --dry-run)
  else
    run mkdir -p "$HOME/.codex"
    run cp "$HARNESS/adapters/codex/hooks.json" "$HOME/.codex/hooks.json"
    [ "$DRY" -eq 1 ] || say "  created ~/.codex/hooks.json"
  fi

  say "Claude Code"
  local shim="$HOME/.claude/CLAUDE.md" keep_rtk=0
  if [ -f "$HOME/.claude/RTK.md" ] || { [ -f "$shim" ] && grep -q '^@RTK.md' "$shim"; }; then keep_rtk=1; fi
  local expected; expected="$(cat "$HARNESS/adapters/claude/CLAUDE.md"; if [ "$keep_rtk" -eq 1 ]; then printf '@RTK.md\n'; fi)"
  if [ -f "$shim" ] && [ "$(cat "$shim")" = "$expected" ]; then
    say "  ok: $shim"
  elif [ "$DRY" -eq 1 ]; then
    [ -f "$shim" ] && say "  would back up $shim"
    say "  would write $shim (imports ~/.agents/AGENTS.md$([ "$keep_rtk" -eq 1 ] && echo ' and @RTK.md'))"
  else
    backup "$shim"
    mkdir -p "$HOME/.claude"
    cp "$HARNESS/adapters/claude/CLAUDE.md" "$shim"
    if [ "$keep_rtk" -eq 1 ]; then printf '@RTK.md\n' >> "$shim"; fi
    say "  wrote $shim"
  fi
  for skill in "$HARNESS"/skills/*/; do
    link "${skill%/}" "$HOME/.claude/skills/$(basename "$skill")"
  done
  for path in "$HOME"/.claude/skills/*; do # drop links to skills removed from the harness
    if [ -L "$path" ] && [ ! -e "$path" ]; then
      case "$(readlink "$path")" in
        "$HARNESS"/skills/*) run rm "$path"; [ "$DRY" -eq 1 ] || say "  removed stale link $path" ;;
      esac
    fi
  done
  if [ -f "$HOME/.claude/settings.json" ]; then
    snapshot "$HOME/.claude/settings.json"
    run python3 "$HARNESS/lib/merge_json.py" "$HOME/.claude/settings.json" "$HARNESS/adapters/claude/settings.json" $([ "$DRY" -eq 1 ] && echo --dry-run)
  else
    run cp "$HARNESS/adapters/claude/settings.json" "$HOME/.claude/settings.json"
    [ "$DRY" -eq 1 ] || say "  created ~/.claude/settings.json"
  fi

  if [ "$PLUGINS" -eq 1 ]; then plugins; fi

  say ""
  say "Next: open Codex and run /hooks to trust the three harness hooks; restart Claude Code."
  say "Optional, per repository: ask the agent to run the setup-repo skill there."
}

user_setup
