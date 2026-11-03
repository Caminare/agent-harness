#!/usr/bin/env bash
# Hook tests with Claude Code and Codex style payloads. Run: bash tests/test_hooks.sh
set -uo pipefail
HOOKS="$(cd "$(dirname "$0")/../hooks" && pwd)"
pass=0; fail=0

expect() { # expect <exit-code> <hook> <json> <label>
  local want="$1" hook="$2" json="$3" label="$4" got
  printf '%s' "$json" | python3 "$HOOKS/$hook" >/dev/null 2>"$TMP/err"; got=$?
  if [ "$got" -eq "$want" ]; then pass=$((pass+1)); else
    fail=$((fail+1)); echo "FAIL [$label] want $want got $got: $(cat "$TMP/err")"; fi
}
bash_cmd() { python3 -c 'import json,sys;print(json.dumps({"tool_name":"Bash","tool_input":{"command":sys.argv[1]}}))' "$1"; }

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
export XDG_CACHE_HOME="$TMP/cache"

# guard: destructive git and rm
for c in "git push --force origin main" "git push -f" "git push origin +main" "git push --force-with-lease" \
         "git reset --hard HEAD~1" "git clean -fd" "git branch -D feature" "rm -rf /" "rm -rf ~" "rm -fr *" \
         "cd x && git reset --hard" "rm -rf /*" "rm -rf ~/*" "rm -Rf ~" "rm -r -f /" "rm -rf -- ~" 'rm -rf "$HOME"' \
         "git -C repo push --force" "sudo rm -rf /" "git push origin main --force" "git branch --delete --force x" \
         "echo X > .env" "cp .env backup.txt" "grep KEY .env.production"; do
  expect 2 guard.py "$(bash_cmd "$c")" "block: $c"
done
for c in "git push origin feature" "git reset HEAD file" "git branch -d merged" "rm -rf build" "rm -rf ./node_modules" \
         "git clean -n" "git commit -m 'fix: x'" "git log --format=%f" "git checkout -b clean-up -f" \
         "git commit -m 'docs: explain reset --hard'" "grep -rn code-review-graph docs" "echo .env >> .gitignore" \
         "cp .env.example .env" "docker compose --env-file .env up" "dotnet test --filter Cart" "flutter test"; do
  expect 0 guard.py "$(bash_cmd "$c")" "allow: $c"
done
# guard: code-review-graph CLI
expect 2 guard.py "$(bash_cmd "code-review-graph build")" "block graph build"
expect 0 guard.py "$(bash_cmd "pipx install code-review-graph && code-review-graph install --platform codex")" "allow graph install"
# guard: secrets
expect 2 guard.py "$(bash_cmd "cat .env")" "block cat .env"
expect 2 guard.py "$(bash_cmd "cat src/.env.local")" "block cat .env.local"
expect 0 guard.py "$(bash_cmd "cat .env.example")" "allow .env.example"
expect 2 guard.py '{"tool_name":"Edit","tool_input":{"file_path":"/repo/.env"}}' "block Edit .env"
expect 2 guard.py '{"tool_name":"Write","tool_input":{"file_path":"/repo/certs/server.pem"}}' "block Write pem"
expect 0 guard.py '{"tool_name":"Write","tool_input":{"file_path":"/repo/.env.example"}}' "allow Write .env.example"
expect 0 guard.py '{"tool_name":"Write","tool_input":{"file_path":"/repo/id_rsa.pub"}}' "allow pub key"
expect 2 guard.py '{"tool_name":"apply_patch","tool_input":{"command":"*** Begin Patch\n*** Update File: config/.env\n@@\n-A=1\n+A=2\n*** End Patch"}}' "block Codex patch .env"
expect 0 guard.py '{"tool_name":"apply_patch","tool_input":{"command":"*** Begin Patch\n*** Update File: src/app.ts\n*** End Patch"}}' "allow Codex patch"
expect 0 guard.py 'not json' "tolerate bad input"
expect 0 guard.py '[1,2]' "tolerate array payload"
expect 0 guard.py '{"tool_name":"Bash","tool_input":"rm -rf /"}' "tolerate string tool_input"
expect 0 guard.py "$(bash_cmd "echo 'unbalanced")" "tolerate unbalanced quotes"
expect 2 guard.py '{"tool_name":"Read","tool_input":{"file_path":"/repo/.env.production"}}' "block Read .env.production"
expect 0 guard.py '{"tool_name":"Read","tool_input":{"file_path":"/repo/src/env.ts"}}' "allow Read normal file"

# format: repo-owned formatter, success and failure
R="$TMP/repo"; mkdir -p "$R/.agents" "$R/src"; git -C "$R" init -q
printf 'x\n' > "$R/src/a.txt"
printf '#!/usr/bin/env bash\nfor f in "$@"; do echo formatted >> "$f"; done\n' > "$R/.agents/format.sh"; chmod +x "$R/.agents/format.sh"
expect 0 format.py "{\"cwd\":\"$R\",\"tool_name\":\"Write\",\"tool_input\":{\"file_path\":\"$R/src/a.txt\"}}" "format Claude Write"
grep -q formatted "$R/src/a.txt" && pass=$((pass+1)) || { fail=$((fail+1)); echo "FAIL format did not run"; }
expect 0 format.py "{\"cwd\":\"$R\",\"tool_name\":\"apply_patch\",\"tool_input\":{\"command\":\"*** Begin Patch\\n*** Update File: src/a.txt\\n*** End Patch\"}}" "format Codex patch"
printf '#!/usr/bin/env bash\necho "parse error" >&2; exit 1\n' > "$R/.agents/format.sh"
expect 2 format.py "{\"cwd\":\"$R\",\"tool_name\":\"Edit\",\"tool_input\":{\"file_path\":\"$R/src/a.txt\"}}" "format failure feeds back"
rm "$R/.agents/format.sh"
expect 0 format.py "{\"cwd\":\"$R\",\"tool_name\":\"Edit\",\"tool_input\":{\"file_path\":\"$R/src/a.txt\"}}" "no formatter is silent"

# verify: Stop loop
V="$TMP/v"; mkdir -p "$V/.agents"; git -C "$V" init -q; git -C "$V" config user.email t@t; git -C "$V" config user.name t
printf 'a\n' > "$V/f.txt"; git -C "$V" add -A; git -C "$V" commit -qm init
STOP="{\"session_id\":\"s1\",\"cwd\":\"$V\",\"hook_event_name\":\"Stop\",\"stop_hook_active\":false}"
expect 0 verify.py "$STOP" "no verify.sh: pass through"
printf '#!/usr/bin/env bash\necho "1 test failed: CartTotal" ; exit 1\n' > "$V/.agents/verify.sh"; chmod +x "$V/.agents/verify.sh"
git -C "$V" add -A; git -C "$V" commit -qm verify
expect 0 verify.py "$STOP" "clean tree: skip"
printf 'b\n' >> "$V/f.txt"
expect 0 verify.py "$STOP" "user's own uncommitted edits: agent did not edit, skip"
expect 0 format.py "{\"session_id\":\"s1\",\"cwd\":\"$V\",\"tool_name\":\"Edit\",\"tool_input\":{\"file_path\":\"$V/f.txt\"}}" "agent edit recorded"
expect 0 verify.py "{\"session_id\":\"other\",\"cwd\":\"$V\",\"stop_hook_active\":false}" "other session not affected"
expect 2 verify.py "$STOP" "dirty tree + failing check blocks stop"
grep -q CartTotal "$TMP/err" && pass=$((pass+1)) || { fail=$((fail+1)); echo "FAIL failure output not fed back"; }
expect 0 verify.py "{\"cwd\":\"$V\",\"stop_hook_active\":true}" "stop_hook_active prevents loop"
out="$(printf '%s' "$STOP" | python3 "$HOOKS/verify.py" 2>/dev/null)"; [ -z "$out" ] && pass=$((pass+1)) || { fail=$((fail+1)); echo "FAIL stdout not empty"; }
printf '#!/usr/bin/env bash\necho ran >> "%s/runs"; exit 0\n' "$TMP" > "$V/.agents/verify.sh"
expect 0 verify.py "$STOP" "passing check lets stop through"
expect 0 verify.py "$STOP" "unchanged tree is cached"
[ "$(wc -l < "$TMP/runs")" -eq 1 ] && pass=$((pass+1)) || { fail=$((fail+1)); echo "FAIL cache did not skip rerun"; }
printf 'c\n' >> "$V/f.txt"
expect 0 verify.py "$STOP" "changed tree re-verifies"
[ "$(wc -l < "$TMP/runs")" -eq 2 ] && pass=$((pass+1)) || { fail=$((fail+1)); echo "FAIL changed tree not re-verified"; }

# verify: timeout kills lingering children (e.g. build servers holding the pipe)
printf '#!/usr/bin/env bash\nsleep 60 &\nsleep 60\n' > "$V/.agents/verify.sh"; printf 'd\n' >> "$V/f.txt"
start=$(date +%s); AGENTS_VERIFY_TIMEOUT=2 expect 2 verify.py "$STOP" "timeout reported"
[ $(( $(date +%s) - start )) -lt 10 ] && pass=$((pass+1)) || { fail=$((fail+1)); echo "FAIL timeout did not kill children"; }

echo "hooks: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
