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
