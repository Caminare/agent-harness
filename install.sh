#!/usr/bin/env sh
# Agent harness installer for macOS, Linux, WSL and Git Bash.
# Windows PowerShell: use install.ps1. Both run lib/install.py.
#
#   ~/.agents/install.sh [--dry-run] [--no-plugins]
set -eu
here="$(cd "$(dirname "$0")" && pwd)"
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 8))' 2>/dev/null; then
    exec "$candidate" "$here/lib/install.py" "$@"
  fi
done
echo "Python 3.8 or later is required (the hooks run on it). Install it and run this again." >&2
exit 1
