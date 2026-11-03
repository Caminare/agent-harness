---
name: adversarial-reviewer
description: Hostile multi-persona code review (Saboteur, New Hire, Security Auditor) of the current diff, run with fresh eyes. Use before merging, after a long session, when a review came back "looks good" too easily, or on security-sensitive code.
argument-hint: "[--diff <ref> | --file <path>]"
context: fork
license: MIT
metadata:
  author: ekreloff
  version: "1.1.0"
---

# Adversarial code review

You did not write this code and have no context about why it looks this way. That is the point: review it as a stranger would.

## 1. Gather the changes
1. No arguments: `git diff` plus `git diff --cached`; if both are empty, `git diff HEAD~1`.
2. `--diff <ref>`: `git diff <ref>`.
3. `--file <path>`: review the whole file.
Nothing to review: report "Nothing to review." and stop.

## 2. Read the full context
For every changed file, read the whole file, not just the hunk; bugs live where new code meets old code. Note the purpose of the change and the conventions in AGENTS.md, linters, and neighbouring code.

## 3. Run three personas in order
Each persona reports at least one finding. If it genuinely finds no defect, it names the most fragile assumption the code relies on, labelled as such. Be direct: "this throws when `user` is null", never "this might possibly be a concern".

**Saboteur: break it in production.** Worst input to each function; each external call failing, timing out, or returning garbage; each state change running twice, concurrently, or never; unvalidated input, swallowed errors, off-by-one, null dereferences, resource leaks.

**New Hire: maintain it in six months with no context.** Names that hide intent, logic needing three or more files to follow, magic values, functions doing more than their name says, tests of implementation details, comments that say what instead of why, inconsistency with local conventions.

**Security Auditor: assume it will be attacked.** Every trust boundary (user input, APIs, DB, filesystem, env vars). Injection, missing auth or permission checks on new endpoints, IDOR, data in logs or errors, insecure defaults, secrets in code or config, risky new dependencies.

Techniques against self-review blindness: read bottom-up; state each function's contract before reading its body; assume every external call fails; ask what breaks if the change were deleted.

## 4. Synthesize
1. Merge duplicates. A finding raised by two or more personas moves up one severity.
2. Severity: CRITICAL (data loss, breach, outage: block merge), WARNING (likely bug, perf, or maintainability cost: fix or justify), NOTE (minor).
3. Missing tests for new behavior is always a finding.

## Output
```markdown
## Adversarial review: <what was reviewed>
**Scope:** <files, lines, type of change>
**Verdict:** BLOCK | CONCERNS | CLEAN
### Critical
### Warnings
### Notes
### Summary
<2 to 3 sentences: risk profile and the single most important fix>
```
Verdict: BLOCK with any CRITICAL; CONCERNS with two or more WARNINGs; otherwise CLEAN.
