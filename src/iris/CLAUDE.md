# src/iris/ — Python package navigation

The `iris` Python package provides the analysis engine, operation library, project system, and config management. It powers both the CLI and the webapp's Python daemon.

## Module map

| File | What it does |
|---|---|
| [engine/](engine/) | Modular engine package — types, AST, parser, cache, executor, ops, registry, factory. |
| [cli.py](cli.py) | `iris` CLI entry point. Thin wrapper — parsing + orchestration only. |
| [config.py](config.py) | YAML config loading + path expansion + `apply_project_overrides` for per-project overrides. |
| [sessions.py](sessions.py) | Session directory creation, `manifest.json`, provenance sidecars per plot. |
| [projects.py](projects.py) | Project workspace lifecycle: create, open, list, append_history. Manages `projects/<name>/` and `.iris/active_project`. |
| [plot_backends/](plot_backends/) | Plot backends: matplotlib, matplotlib_widget. |
| [daemon/](daemon/) | FastAPI server (port 4002) — HTTP API for running ops, profiling data, managing projects. Called by the Express backend. |

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
  helpers.py        Pure signal processing helpers (spike detection, cross-correlation)
  margins.py        Margin calculators for filter ops
  factory.py        create_registry() assembler
  ops/
    filtering.py    butter_bandpass, notch_filter, amp_gain_correction
    detection.py    sliding_rms, constant_rms, rt_detect, rt_thresh, sigmoid
    analysis.py     spike_pca, spike_curate, baseline_correction
    simulation.py   gcamp_sim + _build_gcamp_kernel
    correlation.py  x_corr
    spectral.py     spectrogram, freq_traces
    saturation.py   saturation_mask, saturation_survey
```

## Adding a new operation (hardcoded)

Six touch points:
1. `engine/type_system.py` — add to `TYPE_TRANSITIONS`
2. `engine/ops/<category>.py` — write the `op_<name>` handler
3. `engine/factory.py` — `registry.register_op("<name>", op_<name>)` in `create_registry()`
4. `configs/ops.yaml` — defaults entry
5. `docs/operations.md` — documentation section (math, signature, params)
6. `tests/test_op_registry.py` — type-transition test

## Custom per-project ops (planned)

Projects will be able to have `custom_ops/` directories with Python files following a template. These are loaded by the daemon at runtime and scoped to the project — they don't touch the core registry.

## Role in the webapp

The Express backend (`iris-app/server/`) calls the Python daemon for:
- Running DSL pipelines (which produce plots)
- Profiling uploaded data files
- Listing available operations
- Managing project state

The Claude Code agent (running via the SDK in the Express server) can also directly invoke `iris` CLI commands or edit Python files when the user requests new operations.

## See also
- [../../CLAUDE.md](../../CLAUDE.md) — repo root nav
- [../../iris-app/CLAUDE.md](../../iris-app/CLAUDE.md) — webapp
- [../../docs/operations.md](../../docs/operations.md) — op catalog
- [../../docs/architecture.md](../../docs/architecture.md) — DSL, AST, cache semantics
