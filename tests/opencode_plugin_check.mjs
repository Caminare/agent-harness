// Exercises the rendered opencode plugin with fake opencode contexts (V1 and V2 APIs).
// Run by tests/test_install.py: node opencode_plugin_check.mjs <plugin.js> <git repo>
import assert from "node:assert/strict"
import { chmodSync, readFileSync, writeFileSync } from "node:fs"
import { join } from "node:path"
import { pathToFileURL } from "node:url"

const [pluginPath, repo] = process.argv.slice(2)
const mod = await import(pathToFileURL(pluginPath).href)
const plugin = mod.default

assert.deepEqual(Object.keys(mod), ["default"], "no named exports (older opencode calls them as plugins)")
assert.equal(plugin.id, "agents-harness")

const file = join(repo, "src", "a.txt")
function formatter(fails) {
  const sh = fails ? 'echo "parse error" >&2; exit 1\n' : 'for f in "$@"; do echo formatted >> "$f"; done\n'
  const ps1 = fails ? 'Write-Error "parse error"; exit 1\n' : "foreach ($f in $args) { Add-Content -Path $f -Value formatted }\n"
  writeFileSync(join(repo, ".agents", "format.sh"), "#!/usr/bin/env bash\n" + sh)
  chmodSync(join(repo, ".agents", "format.sh"), 0o755)
  writeFileSync(join(repo, ".agents", "format.ps1"), ps1)
}

// ---------- V1: server() hooks ----------
const hooks = await plugin.server({ directory: repo })
const before = (tool, args) => hooks["tool.execute.before"]({ tool, sessionID: "s", callID: "c" }, { args })

await assert.rejects(before("bash", { command: "git push --force" }), /Blocked by harness guard: force push/)
await assert.rejects(before("bash", { command: "git reset --hard HEAD~1" }), /reset --hard/)
await assert.rejects(before("read", { filePath: join(repo, ".env") }), /secrets file/)
await assert.rejects(before("write", { filePath: "certs/server.pem", content: "x" }), /secrets file/)
await assert.rejects(
  before("apply_patch", { patchText: "*** Begin Patch\n*** Update File: config/.env\n*** End Patch" }),
  /secrets file/,
)
await before("bash", { command: "git status" })
await before("bash", { command: "rm -rf build", workdir: repo })
await before("read", { filePath: join(repo, ".env.example") })
await before("edit", { filePath: file, oldString: "x", newString: "y" })
await before("glob", { pattern: "**/*.ts" })
await before("bash", undefined)

formatter(true)
const output = { title: "", output: "Edit applied.", metadata: {} }
await hooks["tool.execute.after"]({ tool: "edit", sessionID: "s", callID: "c", args: { filePath: file } }, output)
assert.match(output.output, /Edit applied\.\n\nFormatter failed/, "format failure is shown to the model")
const untouched = { title: "", output: "listing", metadata: {} }
await hooks["tool.execute.after"]({ tool: "bash", sessionID: "s", callID: "c", args: { command: "ls" } }, untouched)
assert.equal(untouched.output, "listing")

// ---------- V2: setup(ctx) hooks ----------
const registered = {}
let disposed = 0
const domain = (name) => ({
  hook: async (event, callback) => {
    registered[`${name}.${event}`] = callback
    return { dispose: async () => void disposed++ }
  },
})
const cleanup = await plugin.setup({ location: { directory: repo }, permission: domain("permission"), tool: domain("tool") })
const evaluate = async (action, resources) => {
  const event = { sessionID: "s", action, resources, effect: "allow" }
  await registered["permission.evaluate"](event)
  return event
}

let event = await evaluate("shell", ["git status", "git branch -D feature"])
assert.equal(event.effect, "deny")
assert.match(event.message, /branch -D/)
event = await evaluate("read", ["config/.env.production"])
assert.equal(event.effect, "deny")
event = await evaluate("edit", ["src/a.txt"])
assert.equal(event.effect, "allow")
event = await evaluate("shell", ["ls -la"])
assert.equal(event.effect, "allow")
event = await evaluate("webfetch", ["https://example.com/.env"])
assert.equal(event.effect, "allow", "unrelated actions are not guarded")

formatter(false)
await registered["tool.execute.after"]({ tool: "write", status: "completed", input: { filePath: file } })
assert.match(readFileSync(file, "utf8"), /formatted/, "V2 execute.after formats the edited file")

await cleanup()
assert.equal(disposed, 2, "cleanup disposes both registrations")
console.log("opencode plugin checks passed")
