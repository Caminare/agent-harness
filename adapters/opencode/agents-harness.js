// Agent harness plugin for opencode: runs the shared guard and format hooks in ~/.agents/hooks.
//
// The installer renders this template into ~/.config/opencode/plugins/agents-harness.js,
// filling in the Python interpreter and hooks folder. Edit the template, not the copy.
//
// It supports both opencode plugin APIs in one default export, as the opencode docs
// recommend: `server` (V1, opencode 1.18.29 and later) and `setup` (V2). No package
// import is needed; Plugin.define() only returns its argument. There are deliberately
// no named exports: older opencode releases call every exported function as a plugin.
import { spawn } from "node:child_process"
import { join } from "node:path"

const PYTHON = __PYTHON__
const HOOKS = __HOOKS__
const GUARD_TIMEOUT_MS = 15000
const FORMAT_TIMEOUT_MS = 90000

const SHELL_TOOLS = new Set(["bash", "shell"])
const EDIT_TOOLS = new Set(["edit", "write", "multiedit"])
const PATCH_TOOLS = new Set(["patch", "apply_patch"])
// V2 permission actions mapped to the tool they guard.
const ACTIONS = { shell: "bash", read: "read", edit: "edit" }

// Translate an opencode tool call into the Claude-style event the shared hooks read.
function toEvent(tool, args, cwd) {
  const input = args && typeof args === "object" ? args : {}
  if (PATCH_TOOLS.has(tool)) {
    const patch = input.patchText ?? input.patch ?? input.input ?? ""
    return { tool_name: "apply_patch", tool_input: { command: String(patch) }, cwd }
  }
  let name = tool
  if (SHELL_TOOLS.has(tool)) name = "Bash"
  else if (EDIT_TOOLS.has(tool)) name = "Edit"
  else if (tool === "read") name = "Read"
  else if (tool === "grep") name = "Grep"
  return { tool_name: name, tool_input: input, cwd: input.workdir || cwd }
}

// Run one hook script; resolves { code, stderr }. A missing Python or a timeout never blocks.
function runHook(script, event, timeoutMs) {
  return new Promise((resolve) => {
    let child
    try {
      child = spawn(PYTHON, [join(HOOKS, script)], { stdio: ["pipe", "ignore", "pipe"], windowsHide: true })
    } catch {
      resolve({ code: null, stderr: "" })
      return
    }
    let stderr = ""
    const timer = setTimeout(() => child.kill(), timeoutMs)
    child.stderr.on("data", (chunk) => (stderr += chunk))
    child.on("error", () => {
      clearTimeout(timer)
      resolve({ code: null, stderr: "" })
    })
    child.on("close", (code) => {
      clearTimeout(timer)
      resolve({ code, stderr: stderr.trim() })
    })
    child.stdin.on("error", () => {})
    child.stdin.end(JSON.stringify(event))
  })
}

const isEdit = (tool) => EDIT_TOOLS.has(tool) || PATCH_TOOLS.has(tool)

// V1: hooks returned from server(); throwing in tool.execute.before blocks the call.
async function server(input) {
  const directory = input?.directory || process.cwd()
  return {
    "tool.execute.before": async (info, output) => {
      const result = await runHook("guard.py", toEvent(info.tool, output?.args, directory), GUARD_TIMEOUT_MS)
      if (result.code === 2) throw new Error(result.stderr || "Blocked by harness guard.")
    },
    "tool.execute.after": async (info, output) => {
      if (!isEdit(info.tool)) return
      const result = await runHook("format.py", toEvent(info.tool, info.args, directory), FORMAT_TIMEOUT_MS)
      if (result.code === 2 && output && typeof output.output === "string") {
        output.output += `\n\n${result.stderr}`
      }
    },
  }
}

// V2: blocking goes through the permission "evaluate" hook; formatting through tool "execute.after".
async function setup(ctx) {
  const directory = ctx?.location?.directory || process.cwd()
  const registrations = []
  registrations.push(
    await ctx.permission.hook("evaluate", async (event) => {
      const tool = ACTIONS[event.action]
      if (!tool) return
      for (const resource of event.resources ?? []) {
        const args = tool === "bash" ? { command: resource } : { filePath: resource }
        const result = await runHook("guard.py", toEvent(tool, args, directory), GUARD_TIMEOUT_MS)
        if (result.code === 2) {
          event.effect = "deny"
          event.message = result.stderr || "Blocked by harness guard."
          return
        }
      }
    }),
  )
  registrations.push(
    await ctx.tool.hook("execute.after", async (event) => {
      if (event.status !== "completed" || !isEdit(event.tool)) return
      await runHook("format.py", toEvent(event.tool, event.input, directory), FORMAT_TIMEOUT_MS)
    }),
  )
  return async () => {
    for (const registration of registrations) await registration?.dispose?.()
  }
}

export default { id: "agents-harness", setup, server }
