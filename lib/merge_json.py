#!/usr/bin/env python3
"""Merge harness settings into an existing agent settings file without losing anything.

Usage: merge_json.py <existing.json> <harness.json> [--dry-run]

1. Permission lists (allow, ask, deny) are unioned, keeping existing order.
2. Hook entries are appended per event only when their command is not already present.
3. Other top-level keys from the harness are added only when missing; existing values win.
"""
import json
import os
import sys
import tempfile


def commands(entries: list) -> set:
    return {hook.get("command") for entry in entries for hook in entry.get("hooks", [])}


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
            for event, entries in value.items():
                current = list(hooks.get(event, []))
                known = commands(current)
                current += [e for e in entries if not commands([e]) <= known]
                hooks[event] = current
            result["hooks"] = hooks
        elif key not in result:
            result[key] = value
    return result


def main() -> None:
    target, source = sys.argv[1], sys.argv[2]
    dry_run = "--dry-run" in sys.argv[3:]
    with open(target) as handle:
        existing = json.load(handle)
    with open(source) as handle:
        harness = json.load(handle)
    merged = merge(existing, harness)
    if merged == existing:
        print(f"  unchanged: {target}")
        return
    if dry_run:
        print(f"  would merge harness settings into {target}")
        return
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(target)), suffix=".tmp")
    with os.fdopen(fd, "w") as handle:
        json.dump(merged, handle, indent=2)
        handle.write("\n")
    os.replace(tmp, target)
    print(f"  merged harness settings into {target}")


if __name__ == "__main__":
    main()
