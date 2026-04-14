# src/iris/engine/ — analysis engine (stable)

The DSL parser, AST, executor, cache, type system, and op registry. This
package is **not being restructured** by REVAMP — it already works. The only
changes REVAMP makes here are additive.

## 1. What this dir is for

See [`../CLAUDE.md`](../CLAUDE.md) for the current module map. In short:
`types.py` + `type_system.py` define the data-flow types, `ast.py` + `parser.py`
turn DSL strings into `SourceNode` pipelines, `executor.py` walks them,
`cache.py` handles two-tier caching, `registry.py` + `factory.py` assemble the
op table, and `ops/` holds the 17 hardcoded operations.

## 2. What's changing (REVAMP sweep)

Only two additive hooks:

| Phase | Task | Touch |
|---|---|---|
| 7 | 7.3 | `executor.py` wraps each pipeline invocation in `runs.start_run` / `runs.complete_run` so every execution produces a lineage row in `iris.sqlite`. No executor API change — the wiring is inside `run_pipeline`. |
| 8 | 8.4 | `factory.py` (or a new loader) scans `projects/<name>/ops/<op-name>/v<semver>/` and registers validated, versioned custom ops scoped to the active project. The hardcoded registry is unchanged. |

Ports from SpikeLab land in `ops/` as new handlers — they follow the
six-touchpoint pattern already documented in `../CLAUDE.md` and do not
restructure the package.

## 3. Migration notes

- Nothing to migrate inside `engine/`. The memory rewrite happens around it.
- The engine has no dependency on `iris.projects` today. Phase 7.3 introduces
  a thin one (a single import in `executor.py`); keep it narrow.

## 4. Dependencies

- `numpy`, `scipy`, `matplotlib` (backends), `h5py` (loaders).
- Phase 7.3 adds `iris.projects.runs`.

## 5. Implementation order hints

- Don't refactor the engine alongside a memory task. Engine changes get their
  own commit and their own tests.
- Phase 7.3 is the only place where the engine calls into the new memory
  layer. If you find yourself reaching for `iris.projects.*` elsewhere, stop
  and ask — that's probably a sign a new service module belongs in
  `daemon/services/`.

## See also
- [../CLAUDE.md](../CLAUDE.md) — package overview + op-authoring checklist
- [../../../docs/operations.md](../../../docs/operations.md) — op catalog
- [../../../docs/architecture.md](../../../docs/architecture.md) — DSL, AST, cache semantics
- [../../../REVAMP.md](../../../REVAMP.md) — task ledger
