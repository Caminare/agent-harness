#!/usr/bin/env bash
# Pass/fail check that agents run before finishing a turn (via the harness
# Stop hook) and before calling a task done. Keep it fast: the hook times out
# after 280 seconds by default (AGENTS_VERIFY_TIMEOUT).
#
# This starter auto-detects .NET, Flutter/Dart and npm projects up to three
# folders deep. Replace it with this repository's real commands once known,
# for example only the affected test project instead of the whole solution.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

ran=0
find_first() { find . -maxdepth 3 -not -path '*/node_modules/*' -not -path '*/.dart_tool/*' -name "$1" -print -quit; }

solution="$(find_first '*.sln')"; [ -n "$solution" ] || solution="$(find_first '*.slnx')"
if [ -n "$solution" ]; then
  dotnet build "$solution" --nologo -v q -nodeReuse:false
  dotnet test "$solution" --nologo -v q --no-build
  ran=1
fi

pubspec="$(find_first pubspec.yaml)"
if [ -n "$pubspec" ]; then
  (
    cd "$(dirname "$pubspec")"
    targets=(); for d in lib test bin; do if [ -d "$d" ]; then targets+=("$d"); fi; done
    if [ "${#targets[@]}" -gt 0 ]; then dart format --output=none --set-exit-if-changed "${targets[@]}"; fi
    if grep -q 'sdk: flutter' pubspec.yaml; then
      flutter analyze --no-fatal-infos
      if [ -d test ]; then flutter test; fi
    else
      dart analyze --no-fatal-warnings
      if [ -d test ]; then dart test; fi
    fi
  )
  ran=1
fi

if [ -f package.json ] && grep -q '"test"[[:space:]]*:' package.json; then
  npm test --silent
  ran=1
fi

if [ "$ran" -eq 0 ]; then
  echo "verify.sh: no known stack detected, nothing verified. Edit .agents/verify.sh for this repo." >&2
fi
exit 0
