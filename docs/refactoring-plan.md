# CASI Repo Refactoring Plan

## Context

CASI is a local AI-powered data analysis webapp, but the repo carries ~91GB of legacy data, a 2,461-line monolithic engine file mixing six concerns, three plot backends when only one is used, empty top-level directories, and duplicate type definitions from an abandoned partial refactor. The goal is to strip the repo down to what actually serves the webapp-first direction, split the monolith into clean modules, and consolidate the two serving surfaces (CLI vs daemon).

---

## Phase 0 — Remove Dead Weight

Pure deletion. Zero behavioral change.

### 0a: Delete `legacy/`
- Delete the entire `legacy/` directory (~91GB of old data, notebooks, engine.py, models, writing)
- Remove references to `legacy/` in root `CLAUDE.md` (the table row pointing to it)
- Remove `legacy` from ruff's `extend-exclude` in `pyproject.toml` if present

### 0b: Delete unused plot backends
- Delete `src/casi/plot_backends/pyqtgraph_backend.py` (533 LOC)
- Delete `src/casi/plot_backends/pyqplot_backend.py` (442 LOC)
- Simplify `src/casi/plot_backends/__init__.py`: remove `elif` branches for pyqtgraph/pyqplot, reduce `VALID_BACKENDS` to `("matplotlib", "matplotlib_widget")`
- Remove `params_text_block()` from `_common.py` if only used by deleted backends (verify first)

### 0c: Delete stale engine split artifacts
- Delete `src/casi/engine/types.py` (dead duplicate, never imported by anything real)
- `engine/type_system.py` stays for now — consumed in Phase 1

### 0d: Clean up empty/stale top-level directories
- Delete `cache/` and `outputs/` (both empty)
- Delete `examples/` (2 notebooks — these are legacy-era pipeline demos, superseded by the webapp)
- Evaluate `scripts/check_op_registered.py` — if its logic is covered by tests, delete `scripts/` too

### Net effect: ~975 LOC deleted, ~91GB freed, zero behavioral change

---

## Phase 1 — Split the Engine Monolith

Decompose `engine_monolith.py` (2,461 LOC) into focused modules under `src/casi/engine/`. The `engine/__init__.py` re-exports the same public names throughout, so all callers (CLI, daemon, tests, plot backends) keep working without changes.

### Target structure
```
src/casi/engine/
  __init__.py       Re-exports (same public API surface)
  types.py          16 data type dataclasses (~230 LOC)
  type_system.py    TYPE_TRANSITIONS, DIRECT_BANK_OPS, DataType enum (~40 LOC)
  registry.py       OpRegistry class (~55 LOC)
  ast.py            SourceNode, OpNode, ExprNode, WindowDirective, OverlayGroup (~50 LOC)
  parser.py         DSLParser class (~190 LOC)
  cache.py          PipelineCache class (~160 LOC)
  executor.py       PipelineExecutor + run_pipeline (~400 LOC)
  loaders.py        Source loaders + module-level caches + helpers (~220 LOC)
  helpers.py        Pure signal processing helpers (~80 LOC)
  margins.py        Margin calculators for filter ops (~15 LOC)
  factory.py        create_registry() assembler (~50 LOC)
  ops/
    __init__.py
    filtering.py    butter_bandpass, notch_filter, amp_gain_correction
    detection.py    sliding_rms, constant_rms, rt_detect, rt_thresh, sigmoid
    analysis.py     spike_pca, spike_curate, baseline_correction
    simulation.py   gcamp_sim + _build_gcamp_kernel
    correlation.py  x_corr + cross_correlate_pair
    spectral.py     spectrogram, freq_traces
    saturation.py   saturation_mask, saturation_survey
```

### Execution order (each step = one commit, tests pass after each)

1. **types.py** — Cut dataclasses from monolith lines 43-270. Zero internal deps.
2. **type_system.py** — Overwrite existing with TYPE_TRANSITIONS + DataType. Imports only `types`.
3. **registry.py** — OpRegistry class. Imports `type_system`.
4. **ast.py** — AST node dataclasses. Standalone.
5. **parser.py** — DSLParser. Imports `ast`.
6. **cache.py** — PipelineCache. Imports `ast`.
7. **helpers.py** — Pure functions (detect_spikes_*, cross_correlate_pair). Only numpy/scipy.
8. **ops/** — 7 files grouping 17 handlers. Import from `types` and `helpers`.
9. **loaders.py** — Source loaders + caches. Imports `types`.
10. **margins.py** — Two margin calculators. Imports `types`.
11. **executor.py** — PipelineExecutor + run_pipeline. Imports types, type_system, registry, ast, cache.
12. **factory.py** — create_registry(). Imports ops/*, margins, loaders, plot_backends.
13. **`__init__.py`** — Rewrite to import from new modules instead of `from casi.engine_monolith import *`.
14. **Delete `engine_monolith.py`**.

### Import dependency graph (acyclic)
```
types <- type_system <- registry
ast <- parser
ast <- cache
types <- ops/*
       <- helpers
types <- loaders
types <- margins
types, type_system, registry, ast, cache <- executor
ops/*, margins, loaders, plot_backends <- factory
```

### Critical rule
`engine/__init__.py` must re-export the same public names at every step. Run `uv run pytest -x -q` after each commit. Existing tests in `test_dsl_parser.py`, `test_cache.py`, `test_op_registry.py` exercise the public API.

---

## Phase 2 — Strengthen the Daemon, Thin the CLI

The daemon is the webapp's Python interface but is weaker than the CLI. Fix that.

### 2a: Port CLI validation into daemon routes
- `daemon/routes/pipeline.py` (currently 43 LOC) needs:
  - Active project resolution + config overrides
  - Session creation + provenance
  - Plot cache dedup (`find_cached_plots` from projects.py)
  - Window directive parsing
  - Backend override support
  - Proper error responses (not bare try/except)

### 2b: Add missing daemon endpoints
- `GET /api/ops/{name}` — single op with param schema
- `GET /api/sources` — available source types
- `POST /api/sessions/create` — new session
- `GET /api/sessions/{name}` — session detail
- `POST /api/projects/history/add` — append history entry
- `GET /api/projects/find-plot` — plot dedup lookup

### 2c: Fix webapp agent-bridge issues
- **Per-project sessions**: Change `sessionId` (global singleton on line 32 of `casi-app/server/agent-bridge.ts`) to `Map<string, string>` keyed by project name
- **Hardcoded path**: The `D:\\Apps\\Git\\bin\\bash.exe` fallback list is fine as-is (already behind env var check), but add `which bash` as first attempt before the static list

### 2d: Wire up TODO service stubs
- `casi-app/server/services/` has 3 TODO stub files (conversation-log.ts, prompt-builder.ts, project-memory.ts). Either implement or delete — stubs add confusion.

---

## Phase 3 — Tests

Additive only. No risk.

### 3a: Engine module tests
- `tests/test_engine_types.py` — dataclass construction, trimmed_data property
- `tests/test_engine_executor.py` — mock registry, test prefix reuse
- `tests/test_engine_ops.py` — one test per op using existing `tests/synthetic_data.py`

### 3b: Daemon endpoint tests
- `tests/test_daemon.py` — FastAPI TestClient for each route (valid + invalid inputs)

### 3c: Webapp tests
- `casi-app/src/renderer/__tests__/lib/message-parser.test.ts` — the most complex frontend logic

---

## Phase 4 — Documentation & Cleanup

### 4a: Update CLAUDE.md files
- Root `CLAUDE.md`: update architecture diagram, remove legacy references
- `src/casi/CLAUDE.md`: replace monolith references with new module map, update "Adding a new operation" checklist (6 touch points now span specific files instead of all being in engine_monolith.py)
- `casi-app/CLAUDE.md`: update pending work list

### 4b: Webapp placeholders
- Remove SlidesViewer and ProjectSettings tabs from WorkspaceTabs until implemented (dead UI)

---

## Verification

After each phase:
- `uv run pytest -x -q` — all Python tests pass
- `uv run ruff check src tests` — no lint errors
- `cd casi-app && npm run dev` — webapp starts, chat works, plots render
- Manually test: create project -> upload data -> run a DSL string -> see plot

---

## Files summary

| Phase | Delete | Create | Modify |
|-------|--------|--------|--------|
| 0 | `legacy/`, 2 plot backends, `engine/types.py`, `cache/`, `outputs/`, `examples/` | — | `plot_backends/__init__.py`, `CLAUDE.md` |
| 1 | `engine_monolith.py` | 14 new modules under `engine/` | `engine/__init__.py` |
| 2 | — | missing daemon routes | `daemon/routes/pipeline.py`, `agent-bridge.ts`, service stubs |
| 3 | — | 4-5 test files | — |
| 4 | — | — | 3 CLAUDE.md files, `WorkspaceTabs.tsx` |
