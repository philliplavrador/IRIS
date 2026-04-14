# IRIS — Intelligent Research & Insight System

> A local AI research partner that learns from your analyses *and* the published literature — so it suggests, questions, and contributes insights instead of just running what you ask.

[![License: BSD-3-Clause](https://img.shields.io/badge/License-BSD--3--Clause-blue.svg)](LICENSE)
[![Python: 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)

<!-- TODO: hero screenshot of the webapp (chat + plot + memory side panel) -->
<p align="center">
  <img src="docs/images/hero.png" alt="IRIS webapp — chat, plots, and project memory" width="800">
</p>

---

## What it is

**IRIS** is both the app *and* the assistant inside it. The app is a local data analysis webapp; IRIS (the assistant, powered by Claude under the hood) is your research partner — not a code autocomplete. Every project accumulates its own memory — findings, decisions, caveats — and is cross-referenced against relevant published research.

| | |
|---|---|
| 🧠 **Learns from your work** | Per-project memory of runs, findings, and decisions |
| 📚 **Learns from the field** | Grounded in literature relevant to your data |
| ⚙️ **Actually runs the analysis** | Typed DSL + signal-processing engine on your real files |
| 🔁 **Reproducible** | Every plot carries its DSL, params, and input fingerprints |
| 🔒 **Local-first** | Your data never leaves your machine |

**Domain-agnostic by design.** IRIS works for any field — neuroscience, finance, climate, genomics, whatever you're analysing. *This repo* ships with a neuroscience focus (MEA recordings, calcium imaging).

## What makes it different

Most AI tools describe analyses and forget the conversation. IRIS is the opposite:

**Remembers your project:**

> **You:** "Plot the firing rate over time for channel 861."
>
> **IRIS:** *[runs `mea_trace(861).butter_bandpass.sliding_rms`, renders the plot]*<br>
> "Firing rate peaks around 12 min — matches the bursting pattern you flagged on 2026-03-14 in channel 742. Want me to align these with the calcium trace like last time?"

**Grounds suggestions in the literature:**

> **You:** "The ISI distribution on this culture looks bimodal — not sure what to make of it."
>
> **IRIS:** *[pulls up Wagenaar et al. 2006, *J. Neurosci.*]*<br>
> "Bimodal ISIs in cortical cultures are usually a signature of superbursts — short intra-burst intervals plus long inter-burst gaps. Wagenaar's group characterised this exact pattern at DIV 14–21. If that's what you're seeing, a burst-detection pass with a 100 ms ISI threshold would separate the two modes cleanly. Want me to run it?"

It proposes next steps, flags contradictions with prior runs or published findings, and remembers what you care about.

## Who it's for

- 🔬 Researchers in **any field** who want an analysis partner that grows with the project
- 🧬 Neuroscientists using this repo specifically — MEA + calcium imaging pipelines ready to go
- 📊 Anyone tired of stateless chat windows that forget everything between sessions

---

## Features

### 🧠 Project-scoped learning

Every project is its own universe. IRIS keeps a dedicated memory store per project — so context from your MEA bursting analysis doesn't bleed into your climate-data project, and vice versa.

What gets remembered, automatically:

- **Data profiles** — shapes, sample rates, units, channel counts, inferred on upload
- **Findings & decisions** — "we're treating channels 742 and 861 as the reference pair"
- **Caveats & open questions** — "sampling rate on day 3 is suspect, revisit later"
- **Preferences** — plot styles, default params, conventions you've set
- **Run lineage** — every pipeline execution, with inputs, params, and outputs

Switch projects and the workspace flips entirely — different data, different memory, different configured behaviors.

<!-- TODO: screenshot of the memory/curation panel showing memory entries -->
<p align="center">
  <img src="docs/images/memory-panel.png" alt="Per-project memory panel with findings, decisions, and open questions" width="720">
</p>

### ⚙️ Configurable behavior

IRIS isn't a fixed personality. Every project has a `config.toml` plus a **Behavior** panel in the UI where you dial in *how* the assistant collaborates with you:

- **Autonomy level** — from "ask before every run" to "just figure it out"
- **Pushback strength** — how hard IRIS questions assumptions or flags issues
- **Suggestion frequency** — chatty partner vs. quiet executor
- **Literature grounding** — whether to cite papers proactively, only on request, or off
- **Tone & verbosity** — terse bullets vs. full paragraphs

<!-- TODO: screenshot of the Behavior panel -->
<p align="center">
  <img src="docs/images/behavior-panel.png" alt="Behavior settings — autonomy, pushback, and suggestion controls" width="720">
</p>

### 🧪 Reproducible by construction

Every plot, dataset derivative, and report carries the DSL chain, parameters, and input fingerprints that produced it. Re-running six months later reproduces the exact output — or tells you loudly what changed.

<!-- TODO: screenshot of a plot viewer showing sidecar metadata / provenance -->
<p align="center">
  <img src="docs/images/plot-provenance.png" alt="Plot viewer with DSL + parameters + source fingerprints sidecar" width="720">
</p>

### 📚 Literature-aware suggestions

IRIS pulls context from relevant published work and uses it to interpret unusual results, propose methods, and flag contradictions with prior findings — with citations so you can trace every claim.

### 🔌 Extensible ops

17 built-in signal-processing operations out of the box (filtering, detection, spectral, cross-modal). Need something bespoke? Ask IRIS in chat — it can author a project-scoped custom op, version it, and wire it into the DSL.

---

## How IRIS manages memory

IRIS's value comes from remembering, so memory isn't a side feature — it's the core. Each project keeps its own memory, organised across three layers:

| Layer | Where it lives | What it's for |
|---|---|---|
| 📒 **SQLite database** | `iris.sqlite` inside the project | The source of truth — every event, message, run, artifact, and memory entry |
| 📁 **Content-addressed files** | `artifacts/` and `datasets/` | Raw bytes (plots, derived data) keyed by hash for exact reproducibility |
| 📝 **Curated Markdown** | `memory/*.md` files | The human-readable view — regenerated from SQLite so you can read, diff, and edit in your editor |

### The memory entries themselves

Memory entries are small, typed facts the assistant accumulates as you work:

- **Findings** — "channel 861 shows burst-like firing after minute 8"
- **Decisions** — "we're treating channels 742 and 861 as the reference pair"
- **Caveats** — "day-3 sample rate looks off, don't trust it blindly"
- **Open questions** — "is the bimodal ISI a superburst signature?"
- **Preferences** — "user wants narrow-band spectrograms, no titles"

Nothing lands in long-term memory silently. IRIS **proposes** entries after a session, you **review and commit** the ones worth keeping, and the rest are discarded — so the workspace stays grounded in things you actually endorsed.

### Why this design

- **Three substrates, one truth.** SQLite is queryable, files are reproducible, Markdown is human-readable. No format has to do all three jobs badly.
- **Scoped per project.** Context from your neuroscience project doesn't leak into your finance one. Switch projects, switch memory.
- **Local and inspectable.** Everything is a file on your machine. You can read it, back it up, or delete it — no hidden vendor state.
- **Curated, not hoarded.** Long-term memory is what you confirmed, not whatever happened to be said in chat. That keeps suggestions sharp over time.

Deeper dive: [`IRIS Memory Restructure.md`](IRIS%20Memory%20Restructure.md) (design spec).

---
