# <Project name>

<One or two sentences: what this repository is and who uses it.>

<!-- Keep this file under ~150 lines. Only facts an agent cannot derive from the code:
     commands, conventions that differ from defaults, pitfalls, boundaries.
     Personal preferences live in ~/.agents/AGENTS.md, not here. -->

## Commands
1. Build: `<command>`
2. Test (all): `<command>`
3. Test (one): `<command filtering by name>`
4. Lint / analyze: `<command>`
5. Verify before done: `.agents/verify.sh` (runs automatically when an agent finishes a turn)

## Architecture
1. <Where things live, one line each, only what is not obvious from folder names.>

## Conventions
1. <Rules that differ from language or framework defaults.>

## Boundaries
1. Never edit: <generated code, applied migrations, vendored files>.
2. Ask before: <adding dependencies, changing public contracts, touching infrastructure>.

## Pitfalls
1. <Things that cost time before: env traps, services that must be running, naming mismatches.>
