---
name: refactor-safely
description: Plan and execute a behavior-preserving refactor (rename, extract, dead code removal, decomposition) using code-review-graph dependency analysis. Use when asked to refactor, rename across the codebase, or remove unused code.
---

# Refactor safely

1. Confirm the scope with the user and that tests pass before you start.
2. Check the blast radius with `get_impact_radius_tool` and the critical paths with `get_affected_flows_tool`.
3. Find candidates as needed: `refactor_tool` with mode `suggest`, `dead_code`, or `find_large_functions_tool`.
4. For renames, run `refactor_tool` with mode `rename` to preview every affected location, show the preview, then apply with `apply_refactor_tool` and the returned `refactor_id`.
5. After changes, run `detect_changes_tool` and the test suite to confirm behavior is unchanged.

Rules:
1. Always preview before applying.
2. One refactor per commit; never mix it with behavior changes.
3. If a step would change behavior, stop and ask.
