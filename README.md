# CASI

> **Calcium-Assisted Spike Identity** — a config-driven analysis pipeline and Claude Code agent for simultaneous calcium imaging + multi-electrode array recordings.

[![License: BSD-3-Clause](https://img.shields.io/badge/License-BSD--3--Clause-blue.svg)](LICENSE)
[![Python: 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)

CASI provides a DSL pipeline for MEA signal processing, calcium trace analysis, and cross-modal alignment — driven by a Claude Code agent that lets you run the whole thing from natural language inside a persistent project workspace. For the scientific motivation, see [`docs/proposal.pdf`](docs/proposal.pdf).

---

## Quickstart

### Install

```bash
git clone https://github.com/philliplavrador/CASI
cd CASI
uv sync                                          # core install
uv sync --extra dev                              # add pytest + ruff for development
uv sync --extra dev --extra publication          # add pyqplot (also needs C++ qplot binary)
```

If you don't have [`uv`](https://github.com/astral-sh/uv): `pip install uv`.

`braindance` (required for the `rt_detect` op) is not on PyPI. Install it separately:
```bash
uv pip install --no-deps git+https://github.com/braingeneers/braindance
```

### Get started

Open Claude Code in the CASI directory and run the startup command:

```
/casi-start
```

This loads your configuration, detects (or creates) a project, and drops you into a conversation where the agent acts as a research partner — it remembers your goals, tracks what you've run, cites references, and picks up where you left off across sessions.

From there, talk to your data in natural language:

```
> create a new project for jGCaMP8m kinetics analysis
> spectrogram of channel 861, full window
> use bandpass 300 to 3000 Hz this time
> cross-correlate ROI 12 against all electrodes
> add that last plot to the report with an interpretation
```

For each request, the agent generates the equivalent DSL string, asks for confirmation, runs the pipeline, and reports the saved file paths. Every plot ships with a sidecar JSON containing the full DSL, expanded parameters, window, and source-file fingerprints — full reproducibility metadata travels with every artifact.

---

## Commands

Everything in CASI is driven by slash commands inside Claude Code. No terminal required.

### Getting started

| Command | Description |
|---|---|
| `/casi-start` | Load config, detect or create a project, and begin an analysis session |

### Projects

| Command | Arguments | Description |
|---|---|---|
| `/casi-project-new` | `<name> [-- <description>]` | Create a new project workspace and optionally set goals |
| `/casi-project-open` | `<name>` | Open an existing project as the active workspace |
| `/casi-project-close` | | Deactivate the current project |
| `/casi-project-list` | | List all projects (active project marked with `*`) |
| `/casi-project-info` | `[name]` | Show details about a project (defaults to active) |
| `/casi-project-rename` | `<old-name> <new-name>` | Rename a project |
| `/casi-project-delete` | `<name>` | Delete a project and all its data (asks for confirmation) |

### Analysis

| Command | Arguments | Description |
|---|---|---|
| `/casi-plot` | `[what you want to plot]` | Generate a plot from a natural-language request |
| `/casi-config` | `[show \| edit <file> <key> <value> \| validate]` | View or edit configuration |

### Operations

| Command | Arguments | Description |
|---|---|---|
| `/casi-op-propose` | `<op_name> [-- <what it should do>]` | Draft a design proposal for a new operation (no code written) |
| `/casi-op-implement` | `<op_name>` | Implement a previously proposed operation across all six touch points |

### Maintenance

| Command | Description |
|---|---|
| `/casi-reset` | Reset the entire repo to a clean state — deletes all projects, restores default configs (asks for confirmation) |

### Example session

```
> /casi-start
  ✓ config loaded, no active project

> /casi-project-new jgcamp8m-kinetics -- jGCaMP8m calcium kinetics analysis
  ✓ created and activated project "jgcamp8m-kinetics"

> /casi-plot spectrogram of channel 861, full window
  ✓ saved to projects/jgcamp8m-kinetics/output/session_001/plot_001_spectrogram.png

> /casi-config edit ops butter_bandpass low_hz 300
  ✓ updated ops.yaml: butter_bandpass.low_hz = 300

> /casi-project-list
  * jgcamp8m-kinetics   0 refs   1 plot   jGCaMP8m calcium kinetics analysis

> /casi-project-rename jgcamp8m-kinetics calcium-kinetics
  ✓ renamed to "calcium-kinetics"
```

---

## Managing projects

A **project** is a durable workspace with its own references, config overrides, history, output cache, and living report. Projects give you:

- **Continuity** — the agent reads `claude_history.md` on startup, so it knows your goals, past decisions, and next steps without you repeating yourself.
- **Isolation** — each project has its own output directory, intermediate cache, config overrides, and references. Switching projects switches context entirely.
- **Dedup caching** — re-running the same plot with identical DSL + source fingerprints is a no-op; the agent returns the cached path instead of re-computing.
- **A living report** — `report.md` accumulates your findings, interpretations, and citations as the analysis progresses.

Project names must match `[a-zA-Z0-9_-]{1,64}`. New projects are copied from `projects/TEMPLATE/` and get their own `claude_config.yaml`, `claude_history.md`, `report.md`, output directory, cache, and reference folders.

### Per-project config overrides

Each project can override global settings via `projects/<name>/claude_config.yaml`. Add any of these optional keys:

```yaml
paths_overrides:
  mea_h5: /data/other-recording.h5
ops_overrides:
  butter_bandpass:
    low_hz: 300
    high_hz: 3000
globals_overrides:
  plot_backend: pyqtgraph
```

Overrides are deep-merged on top of the global `configs/` files at runtime (in-memory only — global configs are never mutated). See [`configs/CLAUDE.md`](configs/CLAUDE.md) for the full schema.

See [`docs/projects.md`](docs/projects.md) for the full project contract and [`docs/agent-guide.md`](docs/agent-guide.md) for the agent workflow reference.

---

## Features

- **Project workspaces**: durable analysis contexts with their own config overrides, references, output cache, structured history, and a living report. The Claude agent resumes where you left off across conversations. See [`docs/projects.md`](docs/projects.md).
- **Claude Code agent**: natural-language interface that translates requests into DSL strings, manages projects, tracks goals and decisions in `claude_history.md`, cites references, and builds up `report.md` as findings accumulate. See [`docs/agent-guide.md`](docs/agent-guide.md).
- **Config-driven DSL pipeline**: chains like `mea_trace(861).notch_filter.butter_bandpass.sliding_rms.spike_pca` composed declaratively, parsed into a typed AST, and executed by a single executor with prefix caching.
- **17 operations** spanning filtering (Butterworth bandpass, notch, amplitude gain correction), spike detection (constant RMS, sliding RMS, RT-Sort CNN), calcium preprocessing (rolling-percentile baseline correction), simulation (jGCaMP8m kernel convolution), cross-modal alignment (normalized cross-correlation), spectral analysis (STFT spectrogram, narrowband + broadband power traces), and quality diagnostics (saturation mask + survey, PCA waveform outlier curation). See [`docs/operations.md`](docs/operations.md) for the math behind every op.
- **Two-tier prefix cache**: in-memory reuse within a run + on-disk pickle persistence across runs. Cache keys are derived from the full DSL chain, parameter values, window, **and** input file mtimes — stale reads are impossible.
- **Plot dedup cache**: re-running the same DSL with identical source fingerprints in a project returns the cached plot path instead of re-computing.
- **MEABank vectorization**: single-channel ops are auto-applied across all channels in an `MEABank` without per-op vectorization code.
- **4 interchangeable plot backends**:
  | Backend | Output | Use case |
  |---|---|---|
  | `matplotlib` | Static PNG | Default, headless-safe |
  | `matplotlib_widget` | ipympl widget | Interactive Jupyter notebooks |
  | `pyqtgraph` | Standalone Qt window | Live exploration of long recordings |
  | `pyqplot` | Publication PDF/SVG | Final figures for papers |
- **Per-session output directories** with `manifest.json` (config snapshot + file fingerprints) and a `<plot>.json` sidecar next to every saved figure containing the DSL, expanded params, window, and source mtimes — full reproducibility metadata travels with every artifact.

---

## Architecture

```
casi/
├── src/casi/
│   ├── engine.py            DSL parser, AST executor, op registry, two-tier cache, op handlers, source loaders
│   ├── config.py            YAML config loader + validator
│   ├── projects.py          Project lifecycle, history, references, dedup cache
│   ├── sessions.py          Session directories + provenance sidecar writer
│   ├── cli.py               `casi` command (config / ops / project / run)
│   └── plot_backends/       Pluggable plot backends (matplotlib / pyqtgraph / pyqplot)
├── projects/                Project workspaces (gitignored except TEMPLATE/ and docs)
├── configs/
│   ├── paths.yaml           input/output file paths
│   ├── ops.yaml             defaults for all 17 operations
│   └── globals.yaml         execution + plot backend settings
├── examples/                Jupyter notebooks (local + Colab variants)
├── docs/                    architecture, operations math reference, agent guide, proposal
├── tests/                   pytest suite using synthetic data
├── .claude/                 Claude Code agent definition + slash commands
└── legacy/                  frozen snapshot of the pre-refactor `notebooks/` layout
```

A deeper architectural overview lives in [`docs/architecture.md`](docs/architecture.md).

---

## Documentation

| Document | What it covers |
|---|---|
| [`docs/getting-started.md`](docs/getting-started.md) | Install, first analysis, choosing a backend |
| [`docs/agent-guide.md`](docs/agent-guide.md) | Claude Code workflow + slash command reference |
| [`docs/projects.md`](docs/projects.md) | Project workspace contract: layout, history, cache, references |
| [`docs/operations.md`](docs/operations.md) | Math reference for all 17 ops with LaTeX formulas |
| [`docs/data-format.md`](docs/data-format.md) | Expected MEA `.h5`, calcium `.npz`, and RTSort model layouts |
| [`docs/architecture.md`](docs/architecture.md) | DSL, AST, executor, cache, type system, bank vectorization |
| [`docs/sessions.md`](docs/sessions.md) | Session directory layout + sidecar JSON schema |
| [`docs/development.md`](docs/development.md) | Contributor setup, running tests, project conventions |
| [`docs/proposal.pdf`](docs/proposal.pdf) | SURF proposal — scientific motivation and experimental design |

---

## Appendix: CLI and notebook usage

Everything above can also be done directly from the terminal via the `casi` CLI, without Claude Code.

### CLI reference

```bash
# Configuration and ops
casi config show                              # verify the loaded configuration
casi ops list                                 # list all 17 operations

# Project management
casi project new my-analysis --description "jGCaMP8m kinetics study" --open
casi project open my-analysis
casi project close
casi project list
casi project info my-analysis

# Running pipelines
casi run "mea_trace(861).butter_bandpass.spectrogram" --window full
casi run --force "mea_trace(861).butter_bandpass.spectrogram"   # bypass dedup cache

# Inspecting results
casi project find-plot "mea_trace(861).butter_bandpass.spectrogram"
ls projects/my-analysis/output/
```

> **Note:** the DSL source `mea_trace` refers to **multi-electrode-array** recording data (hardware). It is unrelated to the CLI name.

There are no CLI commands for rename, delete, or full reset — use the slash commands above, or handle these manually:

```bash
# Rename
mv projects/old-name projects/new-name
casi project open new-name                    # update active pointer
# then edit projects/new-name/claude_config.yaml to update the name field

# Delete
casi project close                            # if active
rm -rf projects/my-analysis

# Reset configs to defaults
git checkout HEAD -- configs/paths.yaml configs/ops.yaml configs/globals.yaml
```

### Jupyter notebooks

[`examples/pipeline.ipynb`](examples/pipeline.ipynb) is the local Windows notebook entry point. [`examples/colab_pipeline.ipynb`](examples/colab_pipeline.ipynb) is the Google Drive variant. Both load the same `configs/` files as the CLI and the agent, so changing a default in one place changes it everywhere.

---

## Citation

If you use CASI in your research, please cite it. A `CITATION.cff` is provided at the repo root and rendered by GitHub's "Cite this repository" button.

```bibtex
@software{lavrador_casi_2026,
  author  = {Lavrador, Phillip},
  title   = {CASI: Calcium-Assisted Spike Identity},
  year    = {2026},
  version = {0.1.0},
  url     = {https://github.com/philliplavrador/CASI},
}
```

---

## Acknowledgements

CASI is developed in the [Kosik Lab](https://kosik.mcdb.ucsb.edu/) at UC Santa Barbara under the mentorship of Dr. Tjitse van der Molen, with computational guidance from Dr. Daniel Wagenaar's lab at Caltech. Pilot recordings used a Maxwell Biosystems MaxOne high-density MEA at 20 kHz paired with widefield calcium imaging at 50 Hz of mouse cortical primary cultures expressing jGCaMP8m. The RT-Sort spike sorting model used by the `rt_detect` op is from [van der Molen et al. (2024)](https://doi.org/10.1371/journal.pone.0312438).

## License

[BSD 3-Clause](LICENSE) © 2026 Phillip Lavrador, Kosik Lab UCSB.
