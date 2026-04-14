# IRIS

> Your local AI research partner for data analysis. Create a project, drop in your data, and chat with Claude to filter, detect, plot, and write up — in a workspace that remembers you across sessions.

[![License: BSD-3-Clause](https://img.shields.io/badge/License-BSD--3--Clause-blue.svg)](LICENSE)
[![Python: 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)

---

## Why IRIS

Most AI chat tools describe analyses. IRIS **runs** them. It pairs a local React webapp with a Python signal-processing engine and the Claude Code SDK so the model operates on your real data — filtering, detecting, plotting, writing reports — inside a project workspace that persists decisions and data profiles across sessions. Everything stays on your machine.

For the scientific motivation behind the original neuroscience pipeline, see [`docs/proposal.pdf`](docs/proposal.pdf).

---

## Quickstart

### Prerequisites

- [Node.js](https://nodejs.org/) 20+
- [uv](https://github.com/astral-sh/uv) (`pip install uv`)
- A [Claude Max](https://claude.ai) subscription (the webapp uses the Claude Code SDK)

### Install

```bash
git clone https://github.com/philliplavrador/IRIS
cd IRIS

# Python backend (core + daemon + dev tooling)
uv sync --all-extras

# Webapp
cd iris-app && npm install && cd ..
```

### Run

```bash
iris start
```

This launches the Python daemon (`:4002`), Express server (`:4001`), and Vite dev server (`:4173`), then opens [http://localhost:4173](http://localhost:4173).

Create a project, drag in a dataset, and start chatting.

---

## How it works

```
                  ┌──────────────────┐
  you  ─chat─▶    │  React webapp    │ ──▶ plots, reports, files
                  │  (Vite, :4173)   │
                  └────────┬─────────┘
                           │ WebSocket
                  ┌────────▼─────────┐
                  │  Express server  │ ──▶ Claude Code SDK (agent)
                  │     (:4001)      │
                  └────────┬─────────┘
                           │ HTTP
                  ┌────────▼─────────┐          ┌──────────────────┐
                  │  FastAPI daemon  │ ◀──────▶ │ Project workspace │
                  │     (:4002)      │          │  data • memory •  │
                  │   ops • cache    │          │  conversations    │
                  └──────────────────┘          └──────────────────┘
```

The Express server gives the agent filesystem access, project context, and a handle to the Python engine. The daemon profiles uploaded data and executes DSL pipelines with a two-tier cache. The project workspace is the ground truth — data, memory, conversations, plots, and reports all live there.

Deeper dive: [`docs/architecture.md`](docs/architecture.md).

---

## Architecture

```
iris-app/                React 19 + Express webapp
  server/                  Express + Claude Code SDK bridge + WebSocket
    routes/                REST endpoints (agent, projects)
    services/              Daemon client, file watchers
  src/renderer/            Vite + Tailwind 4 + Zustand + Radix UI
    pages/                 ProjectsPage, WorkspacePage
    components/            Chat, PlotViewer, ReportViewer, FileManager

src/iris/                Python package
  engine/                  DSL parser, AST executor, op registry, two-tier cache
    ops/                   17 operations (filtering, detection, spectral, …)
  daemon/                  FastAPI backend — runs ops, profiles data
  config.py                YAML config loader + validator
  projects.py              Project lifecycle, history, references, dedup cache
  sessions.py              Session directories + provenance sidecars
  cli.py                   `iris` CLI

configs/                 Global YAML configs
projects/                Per-project workspaces (gitignored except TEMPLATE)
tests/                   Pytest suite (synthetic data, headless)
docs/                    Architecture, operations math, project contract
```

---

## Projects

A **project** is a self-contained workspace under `projects/<name>/` with its own data, conversations, memory, config overrides, plots, and reports.

- **Persistent** — the agent reads `memory.yaml` on every message, so it remembers goals, decisions, and data profiles without you repeating yourself.
- **Isolated** — switching projects switches context entirely. Each has its own cache and config overrides.
- **Conversational** — chat history persists as JSONL in `conversations/`; resume or branch at any time.

Full contract: [`docs/projects.md`](docs/projects.md).

---

## Features

**Interface**
- **Chat** — natural-language requests get translated into DSL pipelines and executed.
- **File upload** — drag-and-drop; the daemon profiles the data automatically.
- **Plot viewer** — generated plots with sidecar metadata (DSL, parameters, source fingerprints) for full reproducibility.
- **Report viewer** — a living Markdown report that accumulates findings as analysis progresses.

**Engine**
- **17 built-in operations**, grouped into:
  - *Filtering* — Butterworth bandpass, notch.
  - *Detection* — constant/sliding RMS thresholding, RT-Sort CNN.
  - *Spectral* — spectrograms and spectral summaries.
  - *Cross-modal* — calcium preprocessing, jGCaMP8m kernel simulation, normalized cross-correlation alignment, quality diagnostics.
  - Full math reference: [`docs/operations.md`](docs/operations.md).
- **Config-driven DSL** — chains like `mea_trace(861).notch_filter.butter_bandpass.sliding_rms` parsed into a typed AST, executed with prefix caching.
- **Two-tier cache** — in-memory reuse within a run + on-disk persistence across runs. Keys include DSL chain, parameters, window, and input file mtimes.
- **Per-project overrides** — override any global setting via `projects/<name>/claude_config.yaml`. See [`configs/CLAUDE.md`](configs/CLAUDE.md).

**Extensibility**
- Custom per-project ops can be added through the chat interface when built-ins fall short.

---

## CLI

The `iris` CLI works for direct use outside the webapp:

```bash
iris config show
iris ops list
iris project new my-analysis --open
iris run "mea_trace(861).butter_bandpass.spectrogram"
```

---

## Documentation

| Document | What it covers |
|---|---|
| [`docs/architecture.md`](docs/architecture.md) | DSL, AST, executor, cache, type system, bank vectorization |
| [`docs/operations.md`](docs/operations.md) | Math reference for all 17 ops |
| [`docs/projects.md`](docs/projects.md) | Project workspace contract |
| [`docs/agent-guide.md`](docs/agent-guide.md) | Agent workflow reference |
| [`docs/data-format.md`](docs/data-format.md) | Expected MEA `.h5`, calcium `.npz`, and RT-Sort model layouts |
| [`docs/sessions.md`](docs/sessions.md) | Session directory layout + sidecar JSON schema |
| [`docs/development.md`](docs/development.md) | Contributor setup, running tests, project conventions |

---

## For contributors / agents

Before committing any change, run the maximalist validation gate:

```bash
bash scripts/check.sh       # POSIX
pwsh scripts/check.ps1      # Windows PowerShell
```

The gate runs `ruff format --check`, `ruff check`, `pyright`, `pytest`,
`semgrep --config=auto --error`, and `vulture` across `src/iris` + `tests`,
plus `tsc --noEmit` (and `npm run lint` when present) in `iris-app/`. Any
non-zero exit blocks the commit. This is the same gate REVAMP.md requires
for every task.

---

## Acknowledgements

IRIS is developed in the [Kosik Lab](https://kosik.mcdb.ucsb.edu/) at UC Santa Barbara under the mentorship of Dr. Tjitse van der Molen, with computational guidance from Dr. Daniel Wagenaar's lab at Caltech. Pilot recordings used a Maxwell Biosystems MaxOne high-density MEA at 20 kHz paired with widefield calcium imaging at 50 Hz of mouse cortical primary cultures expressing jGCaMP8m. The RT-Sort spike sorting model used by the `rt_detect` op is from [van der Molen et al. (2024)](https://doi.org/10.1371/journal.pone.0312438).

## License

[BSD 3-Clause](LICENSE) © 2026 Phillip Lavrador, Kosik Lab UCSB.
