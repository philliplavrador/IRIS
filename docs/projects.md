# CASI projects

A **project** is a durable analysis workspace. Each project bundles references, per-project config, cached outputs, a living report, and a structured Claude history file. Projects are gitignored except for a committed `TEMPLATE/` skeleton and this documentation.

The goal is for the Claude analysis agent to feel like a research partner that can resume your work later — not an amnesiac code generator that forgets everything the moment the conversation ends.

## Layout

```
projects/
├── README.md                   (committed; user-facing explainer)
├── CLAUDE.md                   (committed; agent navigation gateway)
├── .gitignore                  (committed; ignores everything except TEMPLATE + README)
├── TEMPLATE/                   (committed scaffold; copied on `casi project new`)
│   ├── CLAUDE.md
│   ├── claude_config.yaml
│   ├── claude_history.md
│   ├── report.md
│   ├── claude_references/
│   │   └── .gitkeep
│   ├── user_references/
│   │   └── .gitkeep
│   └── output/
│       └── .gitkeep
└── <your-project>/             (gitignored; created via `casi project new`)
    ├── CLAUDE.md               (same contents as TEMPLATE's)
    ├── claude_config.yaml      (filled with name / description / created_at)
    ├── claude_history.md       (structured memory; see schema below)
    ├── report.md               (living writeup; user + agent collaborate)
    ├── claude_references/      (agent-gathered refs; web fetches, summaries)
    ├── user_references/        (user-placed refs; PDFs, notes, code)
    ├── output/                 (session directories land here)
    │   └── 2026-04-10_session_001_<label>/
    │       ├── manifest.json
    │       ├── plot_001_*.png
    │       └── plot_001_*.png.json
    └── .cache/                 (project-scoped PipelineCache; sibling of output/)
```

The active project is tracked in `.casi/active_project` (one-line file containing the project name) at the repo root. This file is gitignored so every checkout starts with no active project until the user opens one.

## Lifecycle

```bash
# Create + activate a new project
casi project new kinetics-study --description "jGCaMP8m decay analysis" --open

# Plot something — lands in projects/kinetics-study/output/
casi run "mea_trace(861).butter_bandpass.spectrogram" --window full

# Switch projects
casi project open other-study

# See all projects; the active one is marked with *
casi project list

# Inspect a project's metadata
casi project info kinetics-study

# Deactivate the current project (a project must be opened before the next run)
casi project close
```

## Per-project configuration

Each project's `claude_config.yaml` can override any of the global `configs/` values for that project only:

```yaml
name: kinetics-study
description: jGCaMP8m decay analysis
created_at: 2026-04-10T14:30:00Z

# Merged on top of configs/paths.yaml
paths_overrides: {}

# Merged per-op on top of configs/ops.yaml
ops_overrides:
  butter_bandpass:
    low_hz: 500
    high_hz: 5000

# Merged on top of configs/globals.yaml
globals_overrides:
  plot_backend: pyqplot

# Free-form guidance the analysis agent reads on startup
agent_notes: "Only use narrow-band analyses for this project; publication figures."
```

The override is in-memory — the global `configs/` files are never mutated. Project overrides win over global defaults.

## The `claude_history.md` schema

The history file is the "partner continuity" store. It uses fixed top-level sections with terse dated bullets. Prose is explicitly forbidden.

```markdown
# Claude History: kinetics-study

_Last updated: 2026-04-10T14:45:00Z_

## Goals
- 2026-04-10 - characterize jGCaMP8m rise/decay kinetics on channel 861

## Open Questions
- 2026-04-10 - is the 60 Hz notch biasing the decay fit?

## Decisions
- 2026-04-10 - use 300-5000 Hz bandpass [reason: narrow-band best SNR]

## Operations Run
- 2026-04-10 - mea_trace(861).butter_bandpass.spectrogram [session: 2026-04-10_session_001] [status: ok]

## Plots Generated
- 2026-04-10 - plot_001_mea_trace_861_spectrogram_0.png [dsl: mea_trace(861).butter_bandpass.spectrogram]

## References Added
- 2026-04-10 - zhang_jgcamp8_2023.md [source: web] [decay time constant]

## Next Steps
- 2026-04-10 - cross-correlate against ROI 12
```

### Why this format (instead of JSONL or prose)

- **Section names are the type tags.** The agent can Read the file and jump straight to `## Goals` or `## Next Steps` without parsing free-form text.
- **Terse bracketed metadata** avoids repeating field names, which JSONL duplicates per line.
- **ISO dates first** make recency queries a simple sort.
- **Markdown renders inline** in `report.md` references and is safe to hand-edit.

The seven sections are defined in `HISTORY_SECTIONS` in [`src/casi/projects.py`](../src/casi/projects.py) and enforced by `append_history()` (raises `ValueError` on unknown sections). Do not invent new top-level sections.

## References

Each project has two reference directories with different ownership:

| Directory | Who writes to it | What lives there |
|---|---|---|
| `user_references/` | You (manually) | PDFs, hand-written notes, related code, anything you want the agent to treat as ground truth |
| `claude_references/` | The analysis agent | Stub markdown files summarizing web pages, papers, GitHub repos, or training-data-derived claims |

### Adding a reference

Via the CLI (the agent uses these same commands):

```bash
# A web source — stub lands in claude_references/
casi project reference add "https://doi.org/10.1371/journal.pone.0312438" \
    --source web \
    --title "van der Molen et al. (2024) RT-Sort" \
    --summary "Real-time spike sorting CNN for MaxWell MEAs; reports sub-ms latency." \
    --tag rt-sort --tag spike-sorting

# A user-placed file (the file itself must already be in user_references/)
casi project reference add "zhang-2023.pdf" \
    --source user \
    --summary "Primary paper on jGCaMP8 kinetics"

# A training-data claim (agent flags it as unverified)
casi project reference add "biexponential-decay-fit" \
    --source claude \
    --summary "Biexponential fits are conventional for GCaMP variants." \
    --tag kinetics
```

### Reference stub format

Every reference written by the agent is a markdown file with YAML frontmatter:

```markdown
---
source: web
title: van der Molen et al. (2024) RT-Sort
added_at: 2026-04-10T14:30:00Z
tags:
  - rt-sort
  - spike-sorting
summary: Real-time spike sorting CNN for MaxWell MEAs; reports sub-ms latency.
url: https://doi.org/10.1371/journal.pone.0312438
---

# van der Molen et al. (2024) RT-Sort

Real-time spike sorting CNN for MaxWell MEAs; reports sub-ms latency.
```

For user-placed files, the sidecar `<file>.ref.md` lives next to the file and records the same frontmatter fields (with `file:` instead of `url:`).

### Citation contract

The analysis agent is required to cite references for any analytic claim it makes. Claims that come from the model's training data (rather than a saved reference) must be prefixed `[training-data claim]`. See [`docs/analysis-assistant.md`](analysis-assistant.md) § "Rule 2" for the full contract.

### Listing and inspecting

```bash
casi project reference list                        # tabular
casi project reference list --json                  # machine-readable
casi project reference show "van der Molen"       # substring match on title
casi project reference show claude_references/van-der-molen-2024.md
```

## Cache semantics

CASI has **two** caches per project, working together:

### Intermediate data cache — `projects/<name>/.cache/`

This is the existing two-tier `PipelineCache` from [`src/casi/engine.py`](../src/casi/engine.py), now scoped per-project. Cache keys are content-addressed (DSL + param values + input file mtimes), so moving the cache directory simply creates a fresh cache for the new project the first time. It caches *pickled intermediate computed results* (e.g. a filtered trace, a spectrogram matrix) so repeat runs don't re-compute.

### Plot dedup cache — `projects/<name>/output/`

The output folder itself doubles as a dedup cache: `casi run` checks for an existing sidecar JSON matching the current DSL + source fingerprints + window *before* creating a new session, and short-circuits with the cached path if found. You'll see:

```
$ casi run "mea_trace(861).butter_bandpass.spectrogram" --window 14487.05,44352.95
project: my-analysis
cached: identical plot already exists in this project
  plot:    projects/my-analysis/output/2026-04-10_session_001_test-b/plot_001_mea_trace_861_butter_bandpass_spectrogram_0.png
  sidecar: projects/my-analysis/output/2026-04-10_session_001_test-b/plot_001_mea_trace_861_butter_bandpass_spectrogram_0.png.json
  session: 2026-04-10_session_001_test-b
  window:  [14487.05, 44352.95] (from sidecar)
  rendered: 2026-04-10T14:30:00

pass --force to re-run and create a new version.
```

**Matching rules:**
- **DSL** — literal string comparison (inline overrides like `op(low_hz=300)` are part of the string)
- **Sources** — mtime + size for every file in `configs/paths.yaml` (1-second mtime tolerance)
- **Window** — literal `[start, end]` equality, OR permissive "same sources" match when the query window is `"full"` or missing (same data → same full duration)

**Bypassing the cache:**
- `casi run --force "<DSL>"` — always run, never check
- Editing the input data file invalidates matching sidecars automatically (mtime change)

**Explicit inspection:**
```bash
casi project find-plot "mea_trace(861).spectrogram" --window 14487.05,44352.95
casi project find-plot "mea_trace(861).spectrogram" --json   # machine-readable
casi project find-plot "mea_trace(861).spectrogram" --project my-analysis  # non-active project
```

### Together

The two caches compose: the plot dedup cache short-circuits re-runs entirely (skipping the engine), and the intermediate data cache makes any remaining re-runs cheap. In practice, a typical conversation looks like:

1. First run of a new DSL → engine computes from scratch → plot saved → sidecar written
2. Re-run of the same DSL in the same project → `cached:` short-circuit (no engine call)
3. Re-run with `--force` → engine re-runs but hits the data cache for intermediate results → new plot saved to a new session
4. Re-run after the user edited the source file → sources fingerprint mismatch → both caches miss → engine re-runs from scratch, new plot

## The `report.md` file

Each project has a `report.md` — your living writeup. When a plot turns out to be worth keeping, ask the analysis agent to add a section with:

- the reason the plot was generated
- what the results actually show
- what they insinuate about the underlying biology or methodology
- citations from `claude_references/` or `user_references/` that back the interpretation

Phase 2 formalizes this into an explicit agent workflow with citation gates.

## See also

- [`../src/casi/projects.py`](../src/casi/projects.py) — project lifecycle API
- [`../projects/CLAUDE.md`](../projects/CLAUDE.md) — agent nav gateway
- [`../projects/README.md`](../projects/README.md) — user-facing quick reference
- [`operations.md`](operations.md) — op catalog (and, in Phase 3, the "adding a new operation" checklist)
- [`agent-guide.md`](agent-guide.md) — Claude Code workflow reference
