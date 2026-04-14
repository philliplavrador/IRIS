# IRIS

> Your local AI research partner for data analysis. Create a project, drop in your data, and chat with Claude to filter, detect, plot, and write up — in a workspace that remembers you across sessions.

[![License: BSD-3-Clause](https://img.shields.io/badge/License-BSD--3--Clause-blue.svg)](LICENSE)
[![Python: 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)

---

## What IRIS is

IRIS is a **local AI-powered data analysis webapp**. You create a project, upload a dataset (neuroscience recordings or general tabular / time-series data), and hold a conversation with Claude inside a workspace that actually *runs* the analysis — filtering signals, detecting events, generating plots, writing reports, building slide decks — instead of just describing what you could do.

Everything lives on your machine. The project workspace remembers your data, your decisions, and the context of prior sessions, so you never have to re-explain yourself.

## What it's for

Most AI chat tools talk *about* analysis. IRIS does it. It exists to solve a few recurring pain points:

- **Context loss between sessions.** Chat tools start fresh every time; IRIS keeps findings, caveats, and data profiles in a persistent per-project memory.
- **Describing vs. doing.** The model operates on your real files through a typed DSL + signal-processing engine, not a generic code interpreter.
- **Reproducibility.** Every plot, run, and artifact is content-addressed with the DSL chain, parameters, and input fingerprints that produced it.
- **Privacy.** Data, conversations, and outputs stay local — no uploads to third-party services beyond the Claude API itself.

## Who it's for

- Researchers analysing multi-electrode array recordings, calcium imaging, or other time-series data.
- Anyone with a messy dataset who wants a research partner that can run the analysis, not just suggest code snippets.
- Users who want a persistent, project-scoped workspace rather than a stateless chat window.

---
