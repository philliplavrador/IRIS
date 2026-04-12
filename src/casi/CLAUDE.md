# src/casi/ — Python package navigation

The `casi` Python package provides the analysis engine, operation library, project system, and config management. It powers both the CLI and the webapp's Python daemon.

## Module map

| File | What it does |
|---|---|
| [engine_monolith.py](engine_monolith.py) | DSL parser, AST executor, op registry, `PipelineCache`, all 17 op handlers, source loaders, type system. The core of CASI. |
| [cli.py](cli.py) | `casi` CLI entry point. Thin wrapper — parsing + orchestration only. |
| [config.py](config.py) | YAML config loading + path expansion + `apply_project_overrides` for per-project overrides. |
| [sessions.py](sessions.py) | Session directory creation, `manifest.json`, provenance sidecars per plot. |
| [projects.py](projects.py) | Project workspace lifecycle: create, open, list, append_history. Manages `projects/<name>/` and `.casi/active_project`. |
| [plot_backends/](plot_backends/) | Pluggable plot backends: matplotlib, matplotlib_widget, pyqtgraph, pyqplot. |
| [daemon/](daemon/) | FastAPI server (port 3002) — HTTP API for running ops, profiling data, managing projects. Called by the Express backend. |

## Key anchors in engine_monolith.py

- `TYPE_TRANSITIONS` — the op type graph. Input → output types per op name.
- `PipelineCache` — two-tier cache (memory + disk). `cache_dir` points at `<project>/.cache/` for isolation.
- `create_registry()` — assembles op registry + source loaders.
- `run_pipeline()` — top-level executor called by CLI and daemon.

## Adding a new operation (hardcoded)

Six touch points:
1. `engine_monolith.py` — add to `TYPE_TRANSITIONS`
2. `engine_monolith.py` — write the `op_<name>` handler
3. `engine_monolith.py` — `registry.register_op("<name>", op_<name>)` in `create_registry()`
4. `configs/ops.yaml` — defaults entry
5. `docs/operations.md` — documentation section (math, signature, params)
6. `tests/test_op_registry.py` — type-transition test

## Custom per-project ops (planned)

Projects will be able to have `custom_ops/` directories with Python files following a template. These are loaded by the daemon at runtime and scoped to the project — they don't touch the core registry.

## Role in the webapp

The Express backend (`casi-app/server/`) calls the Python daemon for:
- Running DSL pipelines (which produce plots)
- Profiling uploaded data files
- Listing available operations
- Managing project state

The Claude Code agent (running via the SDK in the Express server) can also directly invoke `casi` CLI commands or edit Python files when the user requests new operations.

## See also
- [../../CLAUDE.md](../../CLAUDE.md) — repo root nav
- [../../casi-app/CLAUDE.md](../../casi-app/CLAUDE.md) — webapp
- [../../docs/operations.md](../../docs/operations.md) — op catalog
- [../../docs/architecture.md](../../docs/architecture.md) — DSL, AST, cache semantics
