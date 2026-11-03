---
name: debug-issue
description: Systematically debug a bug, failing test, or unexpected behavior using code-review-graph navigation. Use when asked why something breaks or to find the root cause of an error.
---

# Debug issue

1. Reproduce first. Get the exact error, failing test, or steps; if you cannot reproduce it, say so before theorizing.
2. Call `get_minimal_context_tool` with the symptom.
3. Find related code with `semantic_search_nodes_tool`.
4. Trace call chains with `query_graph_tool` (`callers_of` and `callees_of`).
5. Follow the full execution path with `get_flow_tool` to find the entry point that triggers the bug.
6. Run `detect_changes_tool` to check whether recent changes caused it; recent changes are the most common source.
7. Run `get_impact_radius_tool` on the suspected files to see what else is affected.
8. State the root cause with evidence, then fix it with a failing test first. Address the cause, not the symptom; never suppress the error.

Without the graph tools, do the same steps with grep, file reads, and `git log -p` on the suspected files.
