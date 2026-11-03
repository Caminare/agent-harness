"""Merge harness settings into an agent's settings without losing the user's own entries.

1. Permission lists (allow, ask, deny) are unioned, keeping existing order.
2. Hook entries the harness owns (any command that runs a script from
   ~/.agents/hooks) are replaced, so re-running the installer after an update
   never duplicates them. Everyone else's hooks are kept as they are.
3. Other top-level keys from the harness are added only when missing; existing values win.
"""
import json
import os
import tempfile

HOOK_COMMAND_KEYS = ("command", "args", "bash", "powershell", "commandWindows", "command_windows")


def is_owned(hook: dict) -> bool:
    text = json.dumps([hook.get(key) for key in HOOK_COMMAND_KEYS]).replace("\\\\", "/")
    return ".agents/hooks/" in text


def entry_is_owned(entry: dict) -> bool:
    hooks = entry.get("hooks") if isinstance(entry.get("hooks"), list) else [entry]
    return any(is_owned(h) for h in hooks if isinstance(h, dict))


def merge(existing: dict, harness: dict) -> dict:
    result = dict(existing)
    for key, value in harness.items():
        if key == "permissions":
            perms = dict(result.get("permissions", {}))
            for kind, rules in value.items():
                current = list(perms.get(kind, []))
                current += [rule for rule in rules if rule not in current]
                perms[kind] = current
            result["permissions"] = perms
        elif key == "hooks":
            hooks = dict(result.get("hooks", {}))
            for event in set(hooks) | set(value):
                kept = [e for e in hooks.get(event, []) if not entry_is_owned(e)]
                merged = kept + list(value.get(event, []))
                if merged:
                    hooks[event] = merged
                else:
                    hooks.pop(event, None)
            result["hooks"] = hooks
        elif key not in result:
            result[key] = value
    return result


def write_json_atomic(path: str, data: dict) -> None:
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")
    os.replace(tmp, path)
