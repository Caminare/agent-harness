---
name: explore-codebase
description: Map an unfamiliar codebase or area with the code-review-graph MCP tools. Use when asked how the code is structured, where something lives, or how a flow works end to end.
---

# Explore codebase

Requires the code-review-graph MCP tools. If they are not loaded, say so and fall back to file reads and grep.

1. Call `get_minimal_context_tool` with the task description first.
2. Get the shape: `list_graph_stats_tool`, then `get_architecture_overview_tool`.
3. Find the major modules with `list_communities_tool`, then `get_community_tool` for the relevant ones.
4. Locate specific functions or classes with `semantic_search_nodes_tool`.
5. Trace relationships with `query_graph_tool` (`callers_of`, `callees_of`, `imports_of`, `children_of`).
6. Follow execution paths with `list_flows_tool` and `get_flow_tool`.
7. Spot complexity hotspots with `find_large_functions_tool` when relevant.

Rules:
1. Start broad, then narrow. Use `detail_level="minimal"` and escalate only when the answer needs it.
2. Confirm anything you will act on by reading the source file; the graph can be stale. Run `build_or_update_graph_tool` if it is.
3. Answer with file paths and symbol names, plus a Mermaid diagram when a flow has more than three steps.
