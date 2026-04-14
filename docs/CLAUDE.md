# docs/ — documentation index

## Current (read these)

| Doc | When to read |
|---|---|
| [operations.md](operations.md) | Authoritative op catalog. Every op's math, type signature, params, and citations. |
| [architecture.md](architecture.md) | DSL, AST, executor, cache, type system, bank vectorization. Refreshed at REVAMP Phase 10. |
| [projects.md](projects.md) | Project workspace contract: directory layout, storage substrates. Refreshed at REVAMP Phase 10 to match the post-rewrite layout. |
| [getting-started.md](getting-started.md) | Install + first analysis. |
| [sessions.md](sessions.md) | Plot-session directory layout + sidecar JSON schema. |
| [data-format.md](data-format.md) | Expected data file formats (MEA .h5, calcium .npz, RT-Sort model). |
| [development.md](development.md) | Contributor setup, tests, conventions. |
| [op-proposal-template.md](op-proposal-template.md) | Template for proposing a new operation. |

## Planned (REVAMP Phase 10)

| Doc | Purpose |
|---|---|
| `memory.md` | Authoritative overview of the memory layer — three substrates, five memory-entry types, extraction pipeline, retrieval, slice builder. Replaces the deleted `iris-memory.md`. |

## Removed (REVAMP Phase 0)

The following legacy design docs were deleted in Task 0.2; do not cite them:
`iris-memory.md`, `iris-behavior.md`, `agent-guide.md`, `refactoring-plan.md`,
`analysis-assistant.md`, `IRIS_BEHAVIOR_PLAN.md`.

For the ongoing rewrite, read
[`memory-restructure.md`](memory-restructure.md) (spec) and
[`REVAMP.md`](REVAMP.md) (task ledger) instead.

## See also
- [../CLAUDE.md](../CLAUDE.md) — repo root nav
- [REVAMP.md](REVAMP.md) — task ledger
