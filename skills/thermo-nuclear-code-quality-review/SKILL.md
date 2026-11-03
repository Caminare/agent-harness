---
name: thermo-nuclear-code-quality-review
description: Extremely strict maintainability review of the current branch for abstraction quality, giant files, and spaghetti-condition growth. Use only when the user explicitly asks for a thermo-nuclear, thermonuclear, deep code quality audit, or especially harsh maintainability review.
disable-model-invocation: true
context: fork
---

# Thermo-nuclear code quality review

An unusually strict review focused on implementation quality, maintainability, abstraction quality, and codebase health. Be ambitious about structure: look for "code judo" moves, restructurings that preserve behavior while making the implementation dramatically simpler, smaller, and more direct.

Scope: the current branch's changes against its base (`git diff <base>...HEAD`). Ask for the base branch if it is not obvious. Read whole files, not just hunks.

## Core prompt
Perform a deep code quality audit of the current branch's changes. Rethink how to structure and implement them to meaningfully improve code quality without changing behavior. Improve abstractions and modularity, reduce spaghetti code, improve succinctness and legibility. Be ambitious: if a clear path to a better implementation involves restructuring some of the codebase, propose it. Measure twice, cut once.

## Non-negotiable standards
0. **Be ambitious about structural simplification.** Look for reframings where whole branches, helpers, modes, conditionals, or layers disappear. Prefer the solution that feels inevitable in hindsight. Push to delete complexity, not rearrange it.
1. **No file crosses 1,000 lines because of this PR** without a very strong reason. If it does, ask whether to decompose first.
2. **No random spaghetti growth.** New ad-hoc conditionals, scattered special cases, or one-off branches in unrelated flows are design problems, not nits. Prefer a dedicated abstraction, helper, state machine, policy object, or module.
3. **Clean the design, do not just accept working code.** If behavior can stay the same while the structure gets meaningfully cleaner, push for it. Prefer removing moving pieces over spreading them around.
4. **Direct, boring code over hacky or magical code.** Flag brittle magic, generic mechanisms hiding simple data shapes, and thin pass-through wrappers.
5. **Clean types and boundaries.** Question unnecessary optionality, `any`, `unknown`, `dynamic`, casts, and silent fallbacks that hide an unclear invariant. Prefer explicit typed models and shared contracts.
6. **Logic in the canonical layer, reuse existing helpers.** Call out feature logic leaking into shared paths, implementation details leaking through APIs, and bespoke near-duplicates of canonical utilities.
7. **No needless sequential orchestration or non-atomic updates** when a cleaner parallel or atomic structure is obvious. Do not chase micro-optimizations.

## Questions for every meaningful change
1. Is there a code judo move that makes this dramatically simpler?
2. Can it be reframed with fewer concepts, branches, or helper layers?
3. Does it improve or worsen the local architecture and the layer it lives in?
4. Did it add branching where a better abstraction, model, or helper should exist?
5. Did a cohesive module become more coupled, stateful, or harder to scan, or a file grow past a healthy size?
6. Is each abstraction earning its keep, or is it a wrapper?
7. Did casts, optionality, or ad-hoc object shapes obscure the real invariant?
8. Is orchestration more sequential or less atomic than it needs to be?

## Preferred remedies
Delete a layer of indirection rather than polish it; reframe the state model so conditionals disappear; move ownership so the feature extends an existing abstraction; turn special cases into a default flow; extract pure functions; split large files; replace condition chains with a typed model or dispatcher; separate orchestration from business logic; reuse the canonical helper; make type boundaries explicit. Do not settle for "maybe rename this" when the issue is structural, or for a cleaner version of the same messy idea when a much simpler idea is plausible.

## Tone
Direct, serious, demanding, never rude. Examples: "this pushes the file past 1k lines, can we decompose this first?", "this adds another special-case branch to an already busy flow, can it live behind its own abstraction?", "this moves complexity around but does not delete it, can the model itself be simpler?"

## Output
Prioritize, in order: structural regressions; missed dramatic simplifications; spaghetti and branching growth; boundary, abstraction, and type-contract problems; file size and decomposition; modularity; legibility. Prefer a few high-conviction findings over many nits.

## Approval bar
Do not approve merely because behavior seems correct. Presumptive blockers unless clearly justified:
1. A plausible code judo move that would delete significant incidental complexity is ignored.
2. A file goes from under 1,000 lines to over 1,000.
3. Ad-hoc branching tangles an existing flow, or feature checks are scattered across shared code.
4. An unnecessary abstraction, wrapper, or cast-heavy contract makes the design more indirect.
5. An existing helper is duplicated or logic lands in the wrong layer when a canonical home exists.
Otherwise leave explicit, actionable feedback and push for the cleaner decomposition.
