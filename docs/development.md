# Development

## Setup

```bash
git clone https://github.com/philliplavrador/CASI
cd CASI
uv sync --extra dev
```

This installs the core deps plus `pytest`, `pytest-cov`, `ruff`, and `pre-commit`.

Optional extras:

```bash
uv sync --extra publication   # adds pyqplot
uv sync --extra dev --extra publication   # both
```

Activate the venv as needed:

```bash
# bash / zsh
source .venv/bin/activate

# Windows (PowerShell)
.venv\Scripts\Activate.ps1
```

## Running tests

```bash
uv run pytest
```

The test suite uses synthetic signals (in `tests/synthetic_data.py`) and never touches the real Maxwell recording, so it runs in a few seconds and works in CI without any data dependencies. Tests that need the optional extras (`pyqplot`, `braindance`) skip themselves automatically with `pytest.importorskip`.

Coverage:

```bash
uv run pytest --cov=src --cov-report=term-missing
```

## Linting and formatting

CASI uses [`ruff`](https://docs.astral.sh/ruff/) for both linting and formatting.

```bash
uv run ruff check src tests           # lint
uv run ruff check --fix src tests     # auto-fix
uv run ruff format src tests          # format
uv run ruff format --check src tests  # check formatting without modifying files
```

The CI workflow at `.github/workflows/ci.yml` runs `ruff check`, `ruff format --check`, and `pytest` on every push and pull request.

## Pre-commit hooks

```bash
uv run pre-commit install
```

The hooks in `.pre-commit-config.yaml` run `ruff` on every commit, plus a few baseline checks (trailing whitespace, large files, merge conflicts).

## Code organization

```
src/casi/
├── engine.py            DSL parser, AST, executor, two-tier cache, op handlers, source loaders, registry factory
├── config.py            YAML config loader + validator
├── sessions.py          Session directories + provenance sidecar writer
├── cli.py               `mea` command
└── plot_backends/
    ├── __init__.py      Backend selector (register_for_backend)
    ├── _common.py       Shared params panel + time-axis helpers
    ├── matplotlib_backend.py
    ├── pyqtgraph_backend.py
    └── pyqplot_backend.py
```

`engine.py` is intentionally one large file with eight ordered sections (data types → DSL parser → cache → executor → top-level API → module-level data caches → MEA/CA/RTSort helpers → source loaders → signal processing helpers → op handlers → margin calculators → registry factory). New ops, source loaders, and helpers should go into `engine.py` in the appropriate section. New plot handlers go into the relevant backend file under `plot_backends/`.

## Conventions

- **Minimal in-place edits.** When fixing a bug or adding a feature, don't refactor surrounding code, don't add docstrings/type annotations to unchanged code, don't reformat unrelated lines.
- **No dict-config syntax in `pipeline_cfg`** — use plain lists of DSL strings (this matters for the example notebooks; configuration of op defaults goes in `configs/ops.yaml`).
- **DSL strings stay canonical.** The two-tier cache keys on the full DSL chain. The Claude Code agent translates natural language into DSL and runs it via `casi run`; it does not maintain a parallel API for individual ops. This is for both speed (cache hits) and clarity (one source of truth for what was executed).
- **Branch-cut decisions.** When porting matplotlib plots to a new backend, prefer to mirror axis labels, titles, and color schemes verbatim. Only deviate when the underlying primitive doesn't exist (e.g., pyqplot has no native `secondary_yaxis`).

## Adding a new operation

1. Define the dataclass for its output type at the top of `engine.py` (skip if it returns an existing type).
2. Add a row to `TYPE_TRANSITIONS` mapping its name to its `{input_type: output_type}` dict.
3. Write the op handler function (`def op_my_new_op(input, ctx, **params) -> output`) somewhere in the OP HANDLERS section.
4. Register it in `create_registry()` with `registry.register_op("my_new_op", op_my_new_op)`.
5. If it requires a data margin (e.g., it's an IIR filter), write a margin calculator and register it.
6. Add a default parameters dict to `configs/ops.yaml`.
7. Document the math in `docs/operations.md`.
8. Add a unit test to `tests/test_op_registry.py` covering the type transition.

## Adding a new plot backend

1. Create `src/casi/plot_backends/my_backend.py`.
2. Implement one handler per dataclass (mirror the matplotlib backend's signatures).
3. Implement a `register(registry: OpRegistry)` function that calls `registry.register_plot(...)` for each handler and `registry.register_overlay_plot(plot_overlay)`.
4. Add a branch to `register_for_backend` in `src/casi/plot_backends/__init__.py`.
5. Add the backend name to `VALID_BACKENDS`.
6. Document it in the `globals.yaml` comment block.

## File-permissions guidance for AI assistants

Earlier in development, the CLAUDE.md at the project root scoped Claude's read/write access to `notebooks/`. That constraint no longer applies — the public repo has the standard layout, and the `mea` agent operates only via the `mea` CLI (Bash + Read tools, no direct Python imports). The CLAUDE.md file at `legacy/CLAUDE.md` is preserved for historical reference but should not be followed for the new layout.

## Releasing

```bash
# bump version in pyproject.toml and src/casi/__init__.py
# update CITATION.cff date-released
git tag -a v0.2.0 -m "v0.2.0"
git push origin v0.2.0
# build sdist + wheel
uv build
# upload to PyPI (when ready)
uv publish
```
