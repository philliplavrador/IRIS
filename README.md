# CASI

> A local AI-powered data analysis webapp. Create projects, upload datasets, and chat with Claude to run analysis, make plots, generate reports, and build slide decks — all in a persistent, project-scoped workspace that remembers context across sessions.

[![License: BSD-3-Clause](https://img.shields.io/badge/License-BSD--3--Clause-blue.svg)](LICENSE)
[![Python: 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)

CASI pairs a React webapp with a Python signal-processing engine and the Claude Code SDK to give you an AI research partner that can operate on your data directly. It ships with 17 hardcoded operations (filtering, spike detection, spectral analysis, calcium preprocessing, cross-modal alignment) and supports custom per-project ops. For the scientific motivation behind the original neuroscience pipeline, see [`docs/proposal.pdf`](docs/proposal.pdf).

---

## Quickstart

### Prerequisites

- [Node.js](https://nodejs.org/) 20+
- [uv](https://github.com/astral-sh/uv) (`pip install uv`)
- A [Claude Max](https://claude.ai) subscription (the webapp uses the Claude Code SDK)

### Install

```bash
git clone https://github.com/philliplavrador/CASI
cd CASI

# Python backend
uv sync                          # core
uv sync --extra daemon           # FastAPI daemon
uv sync --extra dev              # pytest + ruff

# Webapp
cd casi-app && npm install
```

### Run

Start both the Python daemon and the webapp dev server:

```bash
# Terminal 1 — Python daemon (port 3002)
uv run casi-daemon

# Terminal 2 — Webapp (Express :3001 + Vite :5173)
cd casi-app && npm run dev
```

Open [http://localhost:5173](http://localhost:5173) in your browser.

From there you can create a project, upload data files, and start chatting. The AI can run the full DSL pipeline, generate plots, and build up reports — all within your project workspace.

---

## Architecture

```
casi-app/                React 19 + Express webapp
  server/                  Express backend, Claude Code SDK agent bridge, WebSocket
    routes/                  REST endpoints (agent, projects)
    services/                Daemon client, file watchers
  src/renderer/            Vite + Tailwind 4 + Zustand frontend
    pages/                   ProjectsPage, WorkspacePage
    components/              Chat, PlotViewer, ReportViewer, FileManager, etc.

src/casi/                Python package
  engine/                  DSL parser, AST executor, op registry, two-tier cache
    ops/                     17 operations (filtering, detection, spectral, etc.)
  daemon/                  FastAPI backend (port 3002) — runs ops, profiles data
    routes/                  /api/projects, /api/config, /api/ops, /api/pipeline, /api/sessions
  config.py                YAML config loader + validator
  projects.py              Project lifecycle, history, references, dedup cache
  sessions.py              Session directories + provenance sidecar writer
  cli.py                   `casi` CLI (config / ops / project / run)

configs/                 Global YAML configs (paths, ops defaults, globals)
projects/                Per-project workspaces (gitignored except TEMPLATE)
tests/                   Pytest suite (synthetic data, headless)
docs/                    Architecture, operations math, project contract
```

A deeper overview lives in [`docs/architecture.md`](docs/architecture.md).

---

## Projects

A **project** is a self-contained workspace under `projects/<name>/` with its own uploaded data, conversations, memory, config overrides, output cache, plots, and reports.

- **Persistence** — the AI reads project memory (`memory.yaml`) on every message, so it knows your goals, past decisions, and data profiles without you repeating yourself.
- **Isolation** — switching projects switches context entirely. Each project has its own output directory, intermediate cache, and config overrides.
- **Conversations** — chat history persists as JSONL in each project's `conversations/` directory. You can resume or start new conversations from the webapp.

Project details: [`docs/projects.md`](docs/projects.md).

---

## Features

- **Chat interface** — talk to Claude in natural language to run analysis, iterate on plots, and interpret results. The AI translates requests into DSL pipeline strings and executes them.
- **File upload** — drag-and-drop datasets into a project. The daemon profiles uploaded data and makes it available to the pipeline.
- **Plot viewer** — browse generated plots with sidecar metadata (DSL, parameters, source fingerprints) for full reproducibility.
- **Report viewer** — a living Markdown report that accumulates findings and interpretations as analysis progresses.
- **17 built-in operations** — filtering (Butterworth bandpass, notch), spike detection (constant/sliding RMS, RT-Sort CNN), calcium preprocessing, simulation (jGCaMP8m kernel convolution), cross-modal alignment (normalized cross-correlation), spectral analysis, and quality diagnostics. Math reference: [`docs/operations.md`](docs/operations.md).
- **Config-driven DSL** — chains like `mea_trace(861).notch_filter.butter_bandpass.sliding_rms` composed declaratively, parsed into a typed AST, and executed with prefix caching.
- **Two-tier cache** — in-memory reuse within a run + on-disk persistence across runs. Cache keys include DSL chain, parameters, window, and input file mtimes.
- **Per-project config overrides** — override global settings via `projects/<name>/claude_config.yaml`. See [`configs/CLAUDE.md`](configs/CLAUDE.md).

---

## CLI

The `casi` CLI still works for direct use outside the webapp:

```bash
casi config show
casi ops list
casi project new my-analysis --open
casi run "mea_trace(861).butter_bandpass.spectrogram"
```

---

## Documentation

| Document | What it covers |
|---|---|
| [`docs/architecture.md`](docs/architecture.md) | DSL, AST, executor, cache, type system, bank vectorization |
| [`docs/operations.md`](docs/operations.md) | Math reference for all 17 ops |
| [`docs/projects.md`](docs/projects.md) | Project workspace contract |
| [`docs/agent-guide.md`](docs/agent-guide.md) | Agent workflow reference |
| [`docs/data-format.md`](docs/data-format.md) | Expected MEA `.h5`, calcium `.npz`, and RTSort model layouts |
| [`docs/sessions.md`](docs/sessions.md) | Session directory layout + sidecar JSON schema |
| [`docs/development.md`](docs/development.md) | Contributor setup, running tests, project conventions |

---

## Acknowledgements

CASI is developed in the [Kosik Lab](https://kosik.mcdb.ucsb.edu/) at UC Santa Barbara under the mentorship of Dr. Tjitse van der Molen, with computational guidance from Dr. Daniel Wagenaar's lab at Caltech. Pilot recordings used a Maxwell Biosystems MaxOne high-density MEA at 20 kHz paired with widefield calcium imaging at 50 Hz of mouse cortical primary cultures expressing jGCaMP8m. The RT-Sort spike sorting model used by the `rt_detect` op is from [van der Molen et al. (2024)](https://doi.org/10.1371/journal.pone.0312438).

## License

[BSD 3-Clause](LICENSE) © 2026 Phillip Lavrador, Kosik Lab UCSB.
