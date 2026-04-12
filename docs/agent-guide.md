# IRIS Claude Code agent guide

The IRIS agent is the recommended way to drive the pipeline interactively. It is not just a plot generator — it is a **research partner** that remembers project state across sessions, cites references, and delegates web research to a specialist subagent. This guide covers the user-facing workflow; see [`analysis-assistant.md`](analysis-assistant.md) for the full partner-behavior contract.

## What the agent is

Two Markdown agent definitions plus a set of slash commands at [`.claude/commands/`](../.claude/commands/):

- [`.claude/agents/iris.md`](../.claude/agents/iris.md) — **main analysis agent**. Has `Bash`, `Read`, `Edit`, `Write`, and `Task` tools. Never imports Python directly; every action is a `iris ...` shell command or a small edit to a project file. This is the hard wall between the conversation layer and the computation layer.
- [`.claude/agents/iris-researcher.md`](../.claude/agents/iris-researcher.md) — **research specialist subagent**. Has `WebFetch`, `WebSearch`, `Read`, `Write`, and limited `Bash`. Invoked by the main agent via the `Task` tool when a factual question isn't covered by existing references. Returns a structured summary and writes reference stubs into the project.

Keeping `WebFetch`/`WebSearch` on a separate subagent means the main agent's context stays warm for analysis and accidental fetches are impossible during normal plotting.

> **Naming note.** The CLI is `iris`. The DSL source `mea_trace` in expressions like `mea_trace(861).spectrogram` refers to **multi-electrode-array** recording data (hardware) and is unrelated to the CLI name — it is not being renamed.

## Slash commands

| Command | What it does |
|---|---|
| `/iris-start` | Launch the agent, resume the active project, run the configuration verification flow |
| `/iris-plot <description>` | Translate a natural-language plot request into DSL and run it |
| `/iris-config show \| edit \| validate` | View or modify configuration through the agent |
| `/iris-project-new <name>` | Create a new project workspace from TEMPLATE |
| `/iris-project-open <name>` | Open an existing project as the active workspace |
| `/iris-project-close` | Clear the active project |
| `/iris-project-list` | List all projects |
| `/iris-op-propose <name>` | Draft a design proposal for a new op (propose-only, writes no code) |
| `/iris-op-implement <name>` | Implement a proposed op across all six touch points |

## Conversation flow

### 1. Start a session

```
> /iris-start

[agent runs `cat .iris/active_project` and `iris config show`, prints]:
active project: my-analysis  (projects/my-analysis)

Goals:
- 2026-04-08 - identify high-confidence ROI↔unit links on channel 861
Next Steps:
- 2026-04-10 - cross-correlate ROI 12 against all electrodes

IRIS configuration  (project root: D:\Projects\IRIS)
Recording:    legacy/data/alignment-data/Test-B/MEA_B.raw.h5
Calcium:      legacy/data/alignment-data/Test-B/CA_traces_B.npz
RTSort model: legacy/models/rtsort_model
Outputs go to: projects/my-analysis/output/
Plot backend: matplotlib
Window:       set per-request
Operations loaded: 17

Looks right? Reply "go" and tell me what you want to plot, or tell me what to change before we start.
```

If no project is active, the agent offers to create or open one.

### 2. Approve the config or change it

```
> change the bandpass to 300 to 3000 Hz, then go

[agent runs:]
iris config edit ops butter_bandpass.low_hz 300
iris config edit ops butter_bandpass.high_hz 3000
iris session new --label test-b

[outputs the new session path and waits for your first plot request]
```

### 3. Ask for plots in natural language

```
> spectrogram of channel 861, full window

I'll run:
  mea_trace(861).spectrogram
window: full recording

> full

[agent runs:]
iris run "mea_trace(861).spectrogram" --session projects/my-analysis/output/2026-04-10_session_001_test-b --window full

Saved:
  projects/my-analysis/output/2026-04-10_session_001_test-b/plot_001_mea_trace_861_spectrogram_0.png
  projects/my-analysis/output/2026-04-10_session_001_test-b/plot_001_mea_trace_861_spectrogram_0.png.json
```

The sidecar JSON has the full DSL string, every parameter value (including the inherited defaults from `ops.yaml`), the window, and source-file fingerprints. Open it to verify what was actually run.

### 4. Per-request parameter overrides

You don't need to edit the config for one-off changes:

```
> same plot but with the narrow bandpass first

I'll run:
  mea_trace(861).butter_bandpass(low_hz=300, high_hz=3000).spectrogram
```

The override is encoded in the DSL itself. The next request reverts to whatever is in `ops.yaml`.

### 5. Switch backends mid-session

```
> render this last one to PDF for the paper

[agent runs the same DSL with --backend pyqplot]
Saved:
  projects/my-analysis/output/.../plot_002_mea_trace_861_spectrogram.pdf
  projects/my-analysis/output/.../plot_002_mea_trace_861_spectrogram.json
```

```
> let me explore this interactively

[agent runs the same DSL with --backend pyqtgraph]
Opened a desktop window. Pan/zoom inside the window; close it when done.
```

### 6. Research a question the project doesn't already answer

```
> what rise/decay time constants should I expect for jGCaMP8m at room temp?

I don't have a reference for this in the project yet. Should I run a quick
search and save any useful papers?

> yes

[agent spawns iris-researcher via the Task tool with:
  Active project: d:/Projects/IRIS/projects/kinetics-study
  Research brief: What are the published rise and decay time constants for
                   jGCaMP8m at ~22°C in cultured neurons?]

[researcher returns:]
Research brief: What are the published rise and decay time constants...
Searches run: jGCaMP8m kinetics cultured neurons | Zhang 2023 jGCaMP8
References saved: 2
  - Zhang et al. (2023) jGCaMP8 series [kinetics, jgcamp8] → claude_references/zhang-2023-jgcamp8.md
  - Dana et al. (2019) jGCaMP7 baseline [kinetics, jgcamp7] → claude_references/dana-2019-jgcamp7.md
Key findings:
  - Zhang 2023: jGCaMP8m rise ~2ms, decay ~30ms at RT
  - Dana 2019: reference baseline from prior generation
Confidence: high

[main agent then reads zhang-2023-jgcamp8.md and replies:]

jGCaMP8m rise τ is ~2 ms and decay τ is ~30 ms at room temperature for
single action potentials (Zhang et al. 2023,
claude_references/zhang-2023-jgcamp8.md). This is an order of magnitude
faster than GCaMP6s. Want me to log this in Decisions or just Next Steps?
```

### 7. Cite a prior reference in a follow-up

```
> does the decay constant change with temperature?

Zhang 2023 (claude_references/zhang-2023-jgcamp8.md) reports 2P measurements
at 22°C only and doesn't sweep temperature. The typical GCaMP temperature
dependence is an Arrhenius-like speedup at 37°C — faster kinetics, slightly
reduced ΔF/F. [training-data claim]

Want me to spawn the researcher to find a primary source for the
temperature dependence?
```

The `[training-data claim]` tag is mandatory whenever the agent makes a statement that isn't backed by a saved reference file.

## Partner behavior summary

The main agent follows a five-rule contract (see [`analysis-assistant.md`](analysis-assistant.md) for the full version):

1. **Clarify the goal** before any non-trivial analysis — restate the inferred goal in one sentence, get a yes.
2. **Cite references** on every analytic claim, or flag as `[training-data claim]`.
3. **Delegate web research** to `iris-researcher` via the `Task` tool. The main agent never fetches the web itself.
4. **Update `claude_history.md`** after every meaningful exchange using `iris project history add --section ... --bullet ...`.
5. **Respect the automatic plot dedup cache.** `iris run` checks the active project's `output/` before re-running and short-circuits with `cached: ...` on an identical DSL+sources+window match. Pass `--force` to re-run anyway. Use `iris project find-plot "<DSL>"` for explicit inspection.

## Rules the agent follows

These are baked into [`.claude/agents/iris.md`](../.claude/agents/iris.md) and enforced by the contract in [`analysis-assistant.md`](analysis-assistant.md):

- **Never** edits `configs/*.yaml` directly. Always goes through `iris config edit`.
- **Never** invents ops. Only uses ops from `iris ops list`. (Phase 3 will add a guarded autonomous op-creation flow.)
- **One DSL string per `iris run` call**. No multi-step "scripts".
- Asks **one** clarifying question if a request is ambiguous (which channel, which window, etc.) — not a list.
- Reports **only the file paths** that got saved, not a summary of what the plot shows. The plot speaks for itself.
- If a `iris run` fails, parses the error and offers a one-line fix suggestion (missing file, bad op name, type mismatch).
- **Never loads more than two `CLAUDE.md` files** — they are navigation gateways, not reading material.
- **Never fetches the web directly.** Web access lives on `iris-researcher`, invoked via `Task`. The main agent's job is analysis + delegation.
- **Never cites a reference it hasn't read.** If a reference filename appears in `claude_references/` but the agent hasn't opened it yet in this conversation, it reads the file first, then cites.
- **Never writes prose to `claude_history.md`.** One terse dated bullet per fact, in one of the seven fixed sections.

## Working without Claude Code

Almost everything the agent does is a `iris` shell command. You can drive the same workflow from a regular terminal:

```bash
iris project open my-analysis
iris config show
iris config edit ops butter_bandpass.low_hz 300
iris run "mea_trace(861).spectrogram" --window full
iris session list

# Record decisions / references manually
iris project history add --section "Decisions" \
    --bullet "use 300-5000 Hz bandpass [reason: narrow-band best SNR]"

iris project reference add "https://doi.org/10.1371/journal.pone.0312438" \
    --source web \
    --title "van der Molen 2024 RT-Sort" \
    --summary "Real-time spike sorting CNN for MaxWell MEAs." \
    --tag rt-sort
```

The one thing that has no `iris` equivalent is the `iris-researcher` subagent — if you're not using Claude Code, you do your own literature searches and drop references into `user_references/` or add them manually with `iris project reference add`.

The Jupyter notebook at [`examples/pipeline.ipynb`](../examples/pipeline.ipynb) is another entry point for the same machinery.
