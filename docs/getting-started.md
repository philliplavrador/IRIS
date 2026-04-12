# Getting started with IRIS

This walkthrough takes you from a fresh clone to your first plot via the three supported entry points: the Claude Code agent, the `iris` CLI, and the example Jupyter notebook.

## Prerequisites

- Python **3.11+**
- [`uv`](https://github.com/astral-sh/uv) (or fall back to `pip`):
  ```bash
  pip install uv
  ```
- For the optional `rt_detect` op: a working install of `braindance`
- For the optional `pyqplot` backend: the C++ `qplot` binary on your `PATH` (download from https://github.com/wagenadl/qplot/releases)

## 1. Install

```bash
git clone https://github.com/philliplavrador/IRIS
cd IRIS
uv sync                      # core deps only
```

Optional extras:

```bash
uv sync --extra dev          # pytest + ruff + pre-commit
uv sync --extra publication  # pyqplot (still needs qplot binary on PATH)
```

`braindance` is not on PyPI. To enable the `rt_detect` op:

```bash
pip install --no-deps git+https://github.com/braingeneers/braindance
```

## 2. Configure paths

IRIS is configured via three YAML files in `configs/`:

- [`configs/paths.yaml`](../configs/paths.yaml) — file paths to your data, model weights, and output directories
- [`configs/ops.yaml`](../configs/ops.yaml) — defaults for all 17 operation parameters
- [`configs/globals.yaml`](../configs/globals.yaml) — execution and plot backend settings

Edit `paths.yaml` to point at your recording. The defaults reference the legacy Test-B recording at `legacy/data/alignment-data/Test-B/`. Paths can be absolute, relative to the project root, or use `~` and `${ENV_VAR}`.

Verify the configuration loaded correctly:

```bash
iris config show
```

This prints a summary of all three files and flags any missing input files. If everything is `OK`, you're ready to run.

## 3. Choose a plot backend

Set `plot_backend` in [`configs/globals.yaml`](../configs/globals.yaml) (or override per-run with `iris run --backend ...`):

| Backend | When to use |
|---|---|
| `matplotlib` | Default. Static PNG. Headless-safe. Works everywhere. |
| `matplotlib_widget` | Inside a Jupyter notebook with `ipympl`. Hover, zoom, pan. |
| `pyqtgraph` | Standalone Qt window. Best for exploring long recordings. |
| `pyqplot` | Publication-quality PDF/PNG/SVG. Requires the qplot binary. |

## 4. Run your first analysis

### Option A — Claude Code agent (recommended)

```bash
claude
> /iris-start
```

The agent verifies your config, resumes the active project (if any), asks you to confirm, then waits for natural-language plot requests. See [`docs/agent-guide.md`](agent-guide.md) for the full workflow.

### Option B — `iris` CLI

```bash
# optional: create a durable project workspace for this analysis
iris project new first-test --description "smoke test" --open

# run a single DSL expression (lands in the active project's output/ if set)
iris run "mea_trace(861).butter_bandpass.spectrogram" --window full

# inspect what got saved
iris session list
iris project list
```

An active project is required for all runs. Output lives in `projects/<name>/output/<date>_session_NNN[_label]/`. Every saved plot has a `.json` sidecar next to it containing the full DSL, expanded params, and source-file fingerprints.

### Option C — Jupyter notebook

```bash
jupyter notebook examples/pipeline.ipynb
```

The notebook loads `configs/` via `iris.config.load_configs`, builds the registry, and runs `iris.engine.run_pipeline`. Edit the `pipeline_cfg` list to add or remove pipeline sections.

## 5. Where outputs go

Every run creates (or appends to) a session directory under `projects/<name>/output/`:

```
projects/first-test/output/
└── 2026-04-10_session_001/
    ├── manifest.json                                       (full config snapshot)
    ├── plot_001_mea_trace_861_butter_bandpass_spectrogram_0.png
    └── plot_001_mea_trace_861_butter_bandpass_spectrogram_0.png.json
```

The sidecar JSON has the structure documented in [`docs/sessions.md`](sessions.md). You can replay any plot from its sidecar even if the parent session manifest is lost. See [`docs/projects.md`](projects.md) for the full project workspace contract.

## Troubleshooting

**`error: missing input files`** — Run `iris config show` and check the paths flagged `[MISSING]`. Either edit `configs/paths.yaml` (or run `iris config edit paths mea_h5 /your/path.h5`) or move your data to where the config expects it.

**`ImportError: pyqplot backend requires...`** — You set `plot_backend: pyqplot` but don't have the optional extra installed. Run `uv sync --extra publication` and make sure the `qplot` binary is on your PATH.

**`braindance` not found** — Required only for the `rt_detect` op. Install separately with `pip install --no-deps git+https://github.com/braingeneers/braindance`.

**Cache returning stale results after I edited my data file** — That can't actually happen: cache keys include file mtimes. If you suspect cache corruption, delete `cache/` (or pass `disk_cache: false` in `globals.yaml`).

**pyqtgraph window closes immediately when run from a script** — In a non-interactive script, call `iris.plot_backends.pyqtgraph_backend.run_event_loop()` after your pipeline runs. In Jupyter, use `%gui qt`.
