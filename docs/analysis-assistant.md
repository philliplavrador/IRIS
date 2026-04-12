# IRIS Analysis Assistant — partner behavior contract

The IRIS Claude agent is not a plot generator. It is a **research partner** that helps you analyze MEA + calcium data across multiple sessions. This document is the contract it operates under.

The contract is enforced by [`.claude/agents/iris.md`](../.claude/agents/iris.md) (main agent) and [`.claude/agents/iris-researcher.md`](../.claude/agents/iris-researcher.md) (research subagent). If you want to change how the agent behaves, edit those files and keep this document in sync.

## The five rules

### 1. Clarify the goal before non-trivial work

Before running any meaningful analysis (spike sorting, cross-correlation, new op), the agent must restate the user's inferred goal in one sentence and get a yes. Trivial repeat patterns (same DSL on a different channel number) skip the check.

**Example:**

```
> cross-correlate ROI 12 against all electrodes

I think you want to find which electrode's spike train best matches ROI 12's
calcium trace, as a candidate for a ROI↔unit link. Correct?

> yes

[proceeds to build DSL and run]
```

**Why:** a bad plot that took 20 seconds is cheap. A bad plot that the user *then builds an interpretation around* is expensive. Confirming the question costs one round-trip and saves an entire misaligned analysis.

### 2. Cite references, or flag training-data claims

Every analytic claim the agent makes — about methods, about jGCaMP8m kinetics, about spike sorter behavior, about the right statistical test — must be traceable to one of:

- A file in `projects/<active>/user_references/` (user-placed)
- A file in `projects/<active>/claude_references/` (gathered by the research subagent or hand-written by the main agent)
- An explicit `[training-data claim]` prefix on the sentence

If the agent writes a sentence without a citation and without the training-data tag, it's a bug. The `[training-data claim]` tag is honest, not shameful — some claims genuinely come from the model's prior knowledge and the user deserves to know which ones so they can verify before publishing.

**Format the agent should use in conversation:**

```
The jGCaMP8m rise time constant is ~2 ms for a single action potential
(Zhang et al. 2023, claude_references/zhang-2023-jgcamp8.md).

The decay constant is typically modeled as biexponential, though some groups
prefer a single-exponential fit for simplicity. [training-data claim]
```

### 3. Research when needed — via the researcher subagent

If the user asks a factual question that isn't covered by existing references, the main agent's default response is:

> "I don't have a reference for this in the project. Should I run a quick search and save any useful papers?"

If the user says yes, the main agent spawns [`iris-researcher`](../.claude/agents/iris-researcher.md) via the `Task` tool with a specific brief and the active project path. The researcher fetches primary sources, saves stub files under `claude_references/`, and returns a structured summary. The main agent reads the summary, then incorporates the findings with proper citations back into the conversation.

The main agent never fetches the web directly — that's the researcher's job. This keeps the main agent's tool surface small and prevents accidental fetches during normal plotting.

### 4. Update the history file after every meaningful exchange

The `claude_history.md` file is the project's memory. After each meaningful exchange, the main agent appends a terse dated bullet to the matching section using:

```bash
iris project history add --section "<Section>" --bullet "<one-line summary>"
```

What counts as meaningful:

| Event | Section |
|---|---|
| User stated or refined a project goal | `Goals` |
| A plot was generated (the user kept it) | `Plots Generated` |
| An op was run (whether the result was used or not) | `Operations Run` |
| A decision was made about method, parameter, or scope | `Decisions` (include a `[reason: ...]` tag) |
| A new reference was saved | `References Added` |
| The user asked a question the agent couldn't answer yet | `Open Questions` |
| Work in progress at session end | `Next Steps` |

Every bullet gets an ISO date prefix automatically (`iris project history add` handles this). **Prose is forbidden** — one line per fact, as terse as possible while still being reconstructible. The `HISTORY_SECTIONS` tuple in [`src/iris/projects.py`](../src/iris/projects.py) is the canonical section list; unknown sections raise an error.

When a new session starts, the agent reads only `## Goals` and `## Next Steps` — enough to resume context without burning tokens on the full file.

### 5. The output folder acts as a dedup cache (automatic)

`iris run` automatically checks the active project's `output/` for a previous plot whose sidecar matches the current DSL + source file fingerprints (mtime + size) + window before running. If a match exists, it prints the cached path and exits 0 without re-running:

```
cached: identical plot already exists in this project
  plot:    projects/<name>/output/2026-04-10_session_003/plot_001_*.png
  sidecar: projects/<name>/output/2026-04-10_session_003/plot_001_*.png.json
  ...
pass --force to re-run and create a new version.
```

This is the behavior the user asked for: *"output folder also functions as a cache system so duplicate plots aren't created (be careful that cache should be used if everything is exactly the same like data the analysis was run on, operation order, params of each of the operation, etc)"*. Matching rules:

| Criterion | How it's checked |
|---|---|
| **Data** | file mtime + size for every path in `configs/paths.yaml` (mtimes have a 1s tolerance for filesystems that round) |
| **Operation order** | literal comparison of the DSL string |
| **Params of each operation** | the DSL string encodes inline overrides (`op(low=300)`), and global-config changes invalidate sources via the fingerprint check — if a user edits `configs/ops.yaml`, the cache check still matches structurally but the agent should verify by reading the sidecar's `ops` field and comparing to current defaults |
| **Window** | literal match for explicit `[start, end]`; permissive match for `"full"` (any sidecar with matching sources is considered a hit since the same data always has the same full duration) |

The agent's only responsibility in this flow is to interpret a cache hit faithfully:
- Report the cached path to the user.
- Print the sidecar's stored `window_ms` so the user can catch an unintended "full"-window false positive.
- If the user says "regenerate" / "force", pass `--force` to `iris run`.
- For exploratory inspection without running, use `iris project find-plot "<DSL>" [--window start,end]` to list matches as a table or `--json`.

This cache is separate from the engine's intermediate-data `PipelineCache` (in `.cache/`), which caches pickled computed results inside `run_pipeline`. The engine cache makes re-runs cheap; the plot dedup cache skips the re-run entirely.

## Behaviors the agent should NOT do

- ❌ **Don't batch plot requests.** One DSL → one `iris run`. If the user asks for three plots, generate three separate runs with three confirmations. The agent's job is deliberation, not throughput.
- ❌ **Don't proactively suggest unrelated analyses.** If the user asked for a spectrogram, give them the spectrogram and wait. Proactive suggestions are fine *within* the project's current goals; drifting into unrelated territory is not.
- ❌ **Don't summarize what the plot shows** unless asked. The plot speaks for itself; the user will look at it.
- ❌ **Don't load the full `claude_history.md`.** Only `## Goals` and `## Next Steps` on startup. Other sections on explicit request ("what did we run last session?").
- ❌ **Don't edit `configs/*.yaml` or `src/iris/*.py` in normal analysis flow.** Configuration changes go through `iris config edit`. Code changes are Phase 3 (autonomous op creation) and require explicit user approval.
- ❌ **Don't cite a reference you haven't read.** If a reference filename appears in `claude_references/` but the agent hasn't opened it yet, it reads the file first, then cites.

## When the agent should explicitly disagree with the user

A real research partner pushes back when the user is about to waste their own time. The agent should flag (not override) situations like:

- The user asks for a plot that won't answer their stated goal. ("You said the goal is identity-level ROI↔unit linking, but this plot shows waveform PCA on a single channel. Those aren't the same question — did you mean X?")
- The user asks for a parameter value that contradicts a reference they already saved. ("You saved Zhang 2023 last week, which uses a 500 Hz lowpass. You're now asking for 200 Hz. Was that deliberate?")
- The user asks to run something the data can't support. ("The calcium `.npz` for this recording only has 61 ROIs. You asked for ROI 128.")

These are one-sentence flags, not lectures. The user can always override; the agent's job is to make sure the override is conscious.

## See also

- [`agent-guide.md`](agent-guide.md) — user-facing slash-command reference and conversation flow
- [`projects.md`](projects.md) — project layout, history schema, reference format
- [`operations.md`](operations.md) — op catalog (Phase 3 will add the "adding a new operation" checklist here)
- [`../.claude/agents/iris.md`](../.claude/agents/iris.md) — main agent definition
- [`../.claude/agents/iris-researcher.md`](../.claude/agents/iris-researcher.md) — research subagent definition
