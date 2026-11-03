---
name: review-changes
description: Risk-scored review of the current changes using code-review-graph change detection and impact analysis. Use for a quick structural review of a diff, blast radius, or test coverage gaps. For a hostile multi-persona review, use adversarial-reviewer instead.
---

# Review changes

Requires the code-review-graph MCP tools. If they are not loaded, say so and review from `git diff` instead.

1. Call `get_minimal_context_tool` with the task description.
2. Run `detect_changes_tool` for risk-scored change analysis.
3. Run `get_affected_flows_tool` to find impacted execution paths.
4. For each high-risk function, run `query_graph_tool` with pattern `tests_for` to check coverage.
5. Run `get_impact_radius_tool` for the blast radius.
6. Use `get_review_context_tool` for anything that needs more surrounding code.

Output, grouped by risk (high, medium, low):
1. What changed and why it matters.
2. Test coverage status, with specific test cases to add for untested changes.
3. Suggested improvements.
4. Overall merge recommendation.

Use `detail_level="minimal"` by default and escalate only when needed.
