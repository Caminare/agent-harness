---
name: work-context
description: Write a cross-repo handoff document capturing what was built, the contracts the next work consumes, how to run it, gotchas, and what it unblocks. Use when the user asks for a context file, handoff doc, or context for another team, repo, or ticket. For an automatic next-session handoff in the same repo, ai-memory already covers it.
---

# Work context (handoff document)

Produce one self-contained markdown file that lets a fresh session, possibly in another repository, continue without re-deriving anything. The reader has no memory of this conversation.

## 1. Scope (ask only what you cannot infer)
1. What work is captured: tickets, feature name.
2. Which repository the file lives in: where the follow-on work happens, not necessarily where this work was done.
3. What it unblocks: the next tasks.

## 2. Gather facts from code, not memory
1. Repos touched: `git -C <repo> remote get-url origin`, branch, key paths, one line of role each.
2. Tickets: fetch done and follow-on tickets with the Atlassian tool. Summarize, do not paste.
3. Contracts: HTTP verb and full route, auth or permission, request field names with exact casing, response shape, status codes, message contracts, DB schema or seeds, deep-link formats, enum encodings.
4. Run and test prerequisites: services, migrations, seeds, indexes, credentials (names only, never values).
5. Gotchas: what cost time in this session.

## 3. Write `<consumer-repo>/docs/context/YYYY-MM-DD-<slug>.md`
```markdown
# <Feature> - Work Context (<TICKETS>)

**Date:** <YYYY-MM-DD> · **Status:** <state> · **For:** <the follow-on task>

## TL;DR
## Repos and projects
| Repo | Path or project | Role |
## What was built
## Contracts the next work consumes
## How to run and test
## Gotchas and lessons learned
## Next steps
## References
```

Rules:
1. Self-contained: no "see our earlier chat".
2. Contracts are exact. Mark anything you did not verify as unverified.
3. State deferred or unimplemented behavior and known bugs plainly.
4. One file unless the audience genuinely splits.

## 4. Report
Give the path and offer to copy it into the other repository.
