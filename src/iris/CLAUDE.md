# src/iris/ — Python package navigation

The `iris` Python package powers both the CLI and the webapp daemon. It owns
the analysis engine, operation library, project + memory system, and config
loader.

## Module map

| Path | What it does |
|---|---|
| [engine/](engine/) | Analysis engine — types, AST, parser, cache, executor, ops, registry. Stable; not restructured by REVAMP. See [engine/CLAUDE.md](engine/CLAUDE.md). |
| [projects/](projects/) | Project workspace lifecycle + the full memory system (SQLite + content-addressed FS + curated Markdown). **Under active rewrite** — see [projects/CLAUDE.md](projects/CLAUDE.md) and [../../docs/REVAMP.md](../../docs/REVAMP.md). |
| [daemon/](daemon/) | FastAPI backend (port 4002) that exposes engine + memory over HTTP. See [daemon/CLAUDE.md](daemon/CLAUDE.md). |
| [cli.py](cli.py) | `iris` CLI entry point (argparse + orchestration). |
| [config.py](config.py) | TOML config loader (single `configs/config.toml`) + per-project overrides. |
| [sessions.py](sessions.py) | Plot-session directories + `manifest.json` + per-plot sidecars. **Renamed to `plot_sessions.py` in Task 2.3** to free the `sessions` name for memory-layer sessions. |
| [plot_backends/](plot_backends/) | Plot backends: matplotlib, matplotlib_widget. |

## projects/ layout (target state, post-REVAMP)

The full per-file map with spec §s and task numbers lives in
[projects/CLAUDE.md](projects/CLAUDE.md). High-level summary:

- `schema.sql`, `db.py`, `__init__.py` (Phase 1, **done**) — SQLite + lifecycle.
- `events.py`, `sessions.py` (Phase 2) — event log + memory sessions.
- `messages.py`, `tool_calls.py` (Phase 3) — chat + tool records + FTS5.
- `memory_entries.py`, `extraction.py`, `markdown_sync.py` (Phase 4) —
  unified L3 store + session-end extraction + bidirectional Markdown sync.
- `artifacts.py` (Phase 5) — content-addressed output store.
- `datasets.py`, `transformations.py`, `profile.py` (Phase 6).
- `runs.py` (Phase 7) — lineage DAG; engine writes rows here.
- `operations_store.py` (Phase 8).
- `retrieval.py`, `slice_builder.py` (Phase 9).
- V2: `migrations/v2.sql`, `embeddings.py`, `embedding_worker.py`,
  `reflection.py`, `summarization.py`, `op_validation.py`, `contradictions.py`,
  `staleness.py` (Phases 11–17).

## Engine package structure

```
engine/
  __init__.py       Re-exports (same public API surface — always import from iris.engine)
  types.py          16 data type dataclasses (PipelineContext, MEATrace, SpikeTrain, etc.)
  type_system.py    TYPE_TRANSITIONS, DIRECT_BANK_OPS, DataType enum
  registry.py       OpRegistry class
  ast.py            SourceNode, OpNode, ExprNode, WindowDirective, OverlayGroup
  parser.py         DSLParser class
  cache.py          PipelineCache class (two-tier: memory + disk)
  executor.py       PipelineExecutor + run_pipeline top-level API
  loaders.py        Source loaders (MEA, calcium, RTSort) + data caches
  helpers.py        Pure signal processing helpers
  margins.py        Margin calculators for filter ops
  factory.py        create_registry() assembler
  ops/
    filtering.py    butter_bandpass, notch_filter, amp_gain_correction
    detection.py    sliding_rms, constant_rms, rt_detect, rt_thresh, sigmoid
    analysis.py     spike_pca, spike_curate, baseline_correction
    simulation.py   gcamp_sim
    correlation.py  x_corr
    spectral.py     spectrogram, freq_traces
    saturation.py   saturation_mask, saturation_survey
```

## Adding a new operation (hardcoded)

Six touch points:
1. `engine/type_system.py` — add to `TYPE_TRANSITIONS`
2. `engine/ops/<category>.py` — write the `op_<name>` handler
3. `engine/factory.py` — `registry.register_op("<name>", op_<name>)` in `create_registry()`
4. `configs/config.toml` — `[ops.<name>]` defaults table
5. `docs/operations.md` — documentation section (math, signature, params)
6. `tests/test_op_registry.py` — type-transition test

Custom per-project ops (Phase 8) live under `projects/<name>/ops/<op>/v<semver>/`
and are loaded by the daemon at runtime, scoped to the active project.

## Role in the webapp

The Express backend (`iris-app/server/`) calls the Python daemon for:
- Running DSL pipelines (which produce plots)
- Profiling uploaded data files
- Listing operations + project CRUD
- (Phase 2+) Memory reads and writes

The Claude Code agent running in the Express server can also invoke the
`iris` CLI or edit Python files when the user asks for new ops.

## See also
- [../../CLAUDE.md](../../CLAUDE.md) — repo root nav
- [../../iris-app/CLAUDE.md](../../iris-app/CLAUDE.md) — webapp
- [../../docs/REVAMP.md](../../docs/REVAMP.md) — memory rewrite ledger
- [../../docs/memory-restructure.md](../../docs/memory-restructure.md) — design spec
- [../../docs/operations.md](../../docs/operations.md) — op catalog
- [../../docs/architecture.md](../../docs/architecture.md) — DSL, AST, cache
