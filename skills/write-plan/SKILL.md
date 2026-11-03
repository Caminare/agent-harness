---
name: write-plan
description: Turn an agreed design into a reviewable, resumable implementation plan saved in docs/plans/. Use before multi-step features or changes touching several files, after the requirements are clear, or when the user asks for a plan.
---

# Write plan

A plan is a file, not a chat message, so it survives the session, can be reviewed, and can be executed by any agent.

## 1. Agree on the goal first
If requirements are not clear, interview the user one question at a time until they are. Read the relevant code (or the code-review-graph) before planning; never plan against imagined code.

## 2. Write `docs/plans/YYYY-MM-DD-<slug>.md`
```markdown
# <Feature> plan

**Goal:** <one sentence>  ·  **Tickets:** <keys>  ·  **Status:** draft

## Context
<what exists today, constraints, decisions already made, alternatives rejected and why>

## Tasks
- [ ] 1. <small task, 2 to 15 minutes of work>
  - Files: `<path>` (create | change)
  - Test first: <the failing test that proves the behavior>
  - Done when: <command and expected result, e.g. `dotnet test --filter X` passes>
- [ ] 2. ...

## Risks and open questions
## Out of scope
```

Rules:
1. Every task names exact files, a test written before the code, and a check that produces pass or fail.
2. Order tasks so each leaves the build green. Mark tasks that can run in parallel.
3. Keep tasks small enough that one commit per task makes sense.
4. Put anything you are unsure about under open questions instead of guessing.

## 3. Review and execute
Show the plan and wait for approval. When executing, tick tasks off in the file as each one passes its check, and update the plan when reality differs from it. For large plans, run independent tasks in separate git worktrees.
