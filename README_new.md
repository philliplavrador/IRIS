# IRIS

> A local AI research partner that learns from your analyses and the published literature — so it can suggest next steps, flag patterns, and contribute its own insights instead of just running what you ask.

[![License: BSD-3-Clause](https://img.shields.io/badge/License-BSD--3--Clause-blue.svg)](LICENSE)
[![Python: 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)

---

## What IRIS is

IRIS is a **local AI-powered data analysis webapp** built around a simple idea: your analysis tool should get smarter the longer you use it.

IRIS itself is domain-agnostic — it's designed to support data analysis in any field, from neuroscience to finance to climate to whatever dataset you happen to be staring at. This repository currently ships with a **neuroscience focus** (MEA recordings, calcium imaging, and the signal-processing operations that go with them), but the architecture, memory layer, and partner behaviour are built to generalise.

You create a project, upload a dataset, and work alongside Claude in a persistent workspace. IRIS doesn't just execute what you ask — it accumulates context from every run, every decision, and every result, and cross-references it against the published research relevant to your domain. Over time, it becomes a collaborator that proposes the next analysis, flags when your results echo (or contradict) known findings, and surfaces insights you didn't think to look for.

Everything lives on your machine. The project workspace remembers your data, your decisions, and the shape of prior sessions — so you never have to re-explain yourself, and the model has real grounding to reason from.

## What it's for

Most AI chat tools describe analyses in the abstract and forget the conversation the moment you close the tab. IRIS is built to be the opposite:

- **A partner, not a parser.** IRIS forms opinions. It suggests what to try next, questions suspicious results, and points at literature that supports or challenges what you're seeing.
- **Learns from your work.** Every run, plot, and finding feeds a per-project memory — findings, caveats, preferences, open questions — that shapes future recommendations.
- **Learns from the field.** IRIS pulls context from published research relevant to your dataset and project, so its suggestions are grounded in more than just your own recent history.
- **Actually runs the analysis.** A typed DSL and signal-processing engine let the model operate on your real files — filtering, detecting, plotting, reporting — not a sandboxed code snippet.
- **Reproducible and private.** Every output is content-addressed with the DSL chain, parameters, and inputs that produced it. Data and conversations stay local.

## Who it's for

- Researchers in **any field** — neuroscience, finance, climate, genomics, social science — who want an analysis partner that grows with the project.
- Users of this repo specifically: neuroscientists working with MEA recordings, calcium imaging, and related time-series data, using the bundled signal-processing operations.
- Anyone with a messy dataset who wants real suggestions and recommendations — not just executed commands.
- Users who want a persistent, opinionated, literature-aware research partner rather than a stateless chat window.

---
