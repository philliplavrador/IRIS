# IRIS Architecture

IRIS is a local AI-powered data-analysis workspace. A user runs a React
webapp in the browser, chats with Claude (via the Claude Code Agent SDK),
and the model drives a Python analysis daemon that reads and writes a
per-project SQLite database, a content-addressed artifact store, and a
set of regenerated Markdown files.

This document is the architectural overview. For deeper detail:

- Memory system design → [`memory-restructure.md`](memory-restructure.md) (spec)
- Build-order task ledger → [`REVAMP.md`](REVAMP.md)
- Operation math → [`operations.md`](operations.md)
- Project workspace contract → [`projects.md`](projects.md)

---

## System shape

Three long-lived processes, three ports:

```
+---------------------------+   HTTP proxy   +----------------------------+
| React renderer (Vite)     | -------------> | Express webapp (:4001)     |
|   browser @ :4173         |    WebSocket   |   server/index.ts          |
|   src/renderer/           | <------------> |   server/agent-bridge.ts   |
+---------------------------+                +---------------------------+
                                                      |
                                      Claude Code SDK |  HTTP (localhost)
                                                      v
                                             +-----------------------------+
                                             | Python daemon (:4002)       |
                                             |   FastAPI                   |
                                             |   src/iris/daemon/          |
                                             +-----------------------------+
                                                      |
                                                      v
                                             +-----------------------------+
                                             | Project workspace on disk   |
                                             |   projects/<name>/          |
                                             |     iris.sqlite             |
                                             |     memory/*.md             |
                                             |     datasets/ artifacts/    |
                                             |     ops/ indexes/           |
                                             +-----------------------------+
```

- **Renderer (`:4173`)** — Vite dev server serves the React 19 SPA
  (`iris-app/src/renderer/`). Talks only to the webapp.
- **Webapp (`:4001`)** — Express + WebSocket. Hosts the agent bridge
  that spawns the Claude Code SDK session, forwards tool calls, and
  proxies REST requests to the daemon. See [`iris-app/server/CLAUDE.md`](../iris-app/server/CLAUDE.md).
- **Daemon (`:4002`)** — FastAPI, owns all disk state: the project
  SQLite files, artifacts, and Markdown renders. The webapp never
  touches disk directly; every mutation goes through a daemon route.

The CLI (`iris …`) and the webapp share the same daemon and the same
project workspace, so a CLI run is visible to a chat session and vice
versa.

---

## Three storage substrates

Per spec §5.1, every project has three canonical stores that sit side
by side under `projects/<name>/`:

```
projects/<name>/
|-- iris.sqlite             <-- Substrate 1: programmatic truth
|-- memory/
|   |-- PROJECT.md          <-- Substrate 3: regenerated human view
|   |-- DECISIONS.md
|   |-- OPEN_QUESTIONS.md
|   `-- DATASETS/<id>.md
|-- datasets/
|   |-- raw/<id>/<sha>.<ext>         <-- Substrate 2: content-addressed
|   `-- derived/<id>/<sha>.<ext>
|-- artifacts/<sha>/...              <-- Substrate 2: content-addressed
|-- ops/<op>/v<semver>/...
|-- indexes/embeddings.<fmt>         <-- V2+ vector index
`-- config.toml
```

| # | Substrate | Role | Write path |
|---|-----------|------|------------|
| 1 | SQLite `iris.sqlite` | Source of structured truth: projects, sessions, events, messages, tool_calls, memory_entries, datasets, artifacts, runs, operations. WAL mode, FTS5 on messages + memory entries. | Every daemon route; every SDK tool handler. |
| 2 | Content-addressed files | Heavy immutable bytes: uploaded datasets, derived tables, plot PNGs, HTML reports. Filename is the SHA-256 of the content. | `src/iris/projects/` dataset + artifact writers. DB stores hash + metadata; filesystem stores content. |
| 3 | Curated Markdown | Human-auditable view: `memory/PROJECT.md`, `DECISIONS.md`, `OPEN_QUESTIONS.md`, `DATASETS/<id>.md`. Always regenerated from SQLite — never the source of truth. | `src/iris/projects/markdown_sync.py`. |

Rules:

- Binaries never go in SQLite. DB holds a `sha256` + metadata; the file
  lives under `datasets/` or `artifacts/`.
- Markdown is a read-only mirror from the user's perspective. Edits
  land through `propose → commit` against memory entries, which then
  re-renders the file.
- The SQLite schema is the single source for everything IRIS reasons
  about. Rebuilding Markdown or the vector index from scratch is
  supported by design.

Schema lives in [`src/iris/projects/schema.sql`](../src/iris/projects/schema.sql).

---

## Memory model

IRIS's memory is layered, with each layer backed by specific tables and
code modules.

```
       User input                    Assistant + tool output
            \                            /
             v                          v
  +-----------------------------------------------+
  |  L0  events          (append-only, hashed)     |   <-- everything happens here first
  +-----------------------------------------------+
            |                          |
            v                          v
  +-----------------+        +-----------------------+
  |  L1  messages   |        |  L1  tool_calls       |
  |  (FTS5, session |        |  (request/result,     |
  |   buffer)       |        |   cleared on commit)  |
  +-----------------+        +-----------------------+
            \                          /
             v                        v
        +----------------------------------+
        |  L3  memory_entries              |   <-- findings, decisions,
        |   type, confidence, evidence,    |       caveats, open questions,
        |   status, provenance             |       preferences
        +----------------------------------+
                         |
                         v
             +-------------------------+
             |  runs DAG               |   <-- parent_run_id chain,
             |  dataset -> op -> art   |       reproducibility backbone
             +-------------------------+
                         |
                         v
             +-------------------------+
             |  operations catalog     |   <-- project-scoped + global,
             |  versioned, tested      |       skill library (Phase 8+)
             +-------------------------+
```

| Layer | Purpose | Table(s) | Code |
|---|---|---|---|
| L0 events | Append-only audit log. Every message, tool call, memory write, dataset import, run start/end produces an event with a hash chain. | `events` | `src/iris/projects/events.py` |
| L1 messages | Verbatim conversation. FTS5 over `content_text`. Drives the session buffer and recall. | `messages`, `messages_fts` | `src/iris/projects/messages.py` |
| L1 tool_calls | Paired request/result records. The result payload is nulled out after its findings are committed (see "tool-result clearing"). | `tool_calls` | `src/iris/projects/tool_calls.py` |
| L3 memory entries | Curated semantic memory: findings, decisions, caveats, open questions, preferences, failure reflections. Proposed by extraction, committed by the user. | `memory_entries` | `src/iris/projects/memory_entries.py`, `extraction.py` |
| Runs DAG | Provenance: which op on which dataset version produced which artifact, with parent links. | `runs`, `datasets`, `artifacts` | Phase 6 modules under `src/iris/projects/` |
| Operations catalog | Built-in 17 ops + project-scoped versioned skills. | `operations` | `src/iris/engine/` (built-ins), `ops/<name>/v<semver>/` (project) |

L2 (working set) and L4 (procedural) from the spec live on top of these
primitives; they are assembly strategies, not new tables.

### Propose → commit

Memory entries are never written silently. The assistant (via the
`propose_memory` tool) stages entries with `status = 'proposed'`; the
user approves or edits them in the UI; on commit they flip to
`'active'` and the corresponding `memory/*.md` file is regenerated.

### Tool-result clearing

Tool results can be huge (Parquet previews, plot payloads, RTSort
outputs). Once a tool-call's findings are distilled into a memory
entry or an artifact row, the large result blob in `tool_calls.result`
is replaced with a stub pointer. The event row retains the hash, so
provenance is preserved without paying the token or disk cost on every
context rebuild. Implemented in `src/iris/projects/tool_calls.py`.

---

## DSL and engine

The analysis engine is stable and not being restructured. It parses a
dot-separated DSL into an AST and runs it through a typed executor
with a two-tier cache.

```
  "mea_trace(861).butter_bandpass.spectrogram"
              |
              v  DSLParser
  +-----------------------------+
  | AST: source + op nodes      |
  +-----------------------------+
              |
              v  PipelineExecutor
  +-----------------------------+        +--------------------+
  | Type check (input -> output)| -----> | PipelineCache      |
  | Margin padding              |        |  mem + disk tiers  |
  | Bank vectorization          |        +--------------------+
  | Auto-plot on terminal node  |
  +-----------------------------+
              |
              v
        artifact + run rows in iris.sqlite
```

- 17 built-in ops (filters, spike detectors, calcium alignment,
  spectrogram, cross-correlation, GCaMP simulation).
- Types flow left-to-right through `TYPE_TRANSITIONS`; mismatches fail
  before compute.
- Cache keys include window, op params, source path, and mtime, so
  any parameter change invalidates exactly the downstream prefix.

Full math, types, and parameters → [`operations.md`](operations.md).
Per-project versioned ops land in Phase 8 and live under
`projects/<name>/ops/<op>/v<semver>/`.

---

## Agent bridge

The webapp is not the LLM host — the Claude Code SDK is. The bridge
(`iris-app/server/agent-bridge.ts`) owns a single SDK session per chat
and shuttles messages between the browser and the daemon.

```
 Browser (Zustand store)
     |   WebSocket JSON {type:"user_message", text}
     v
 Express /ws
     |
     v
 agent-bridge.ts
     |   SDK query(prompt, options)
     v
 Claude Code SDK (Max subscription, --model opus)
     |
     |   tool_use -> bridge
     v
 Tool handlers (bridge)
     |   POST :4002/memory/...  /runs/...  /datasets/...
     v
 Daemon routes  ->  src/iris/projects/*  ->  iris.sqlite + fs
     |
     v  tool_result
 SDK  ->  bridge  ->  WebSocket  ->  browser
```

Key responsibilities:

1. **Slice builder** — before each turn, the bridge asks the daemon
   for a context slice: L1 core memory, recent L1 messages, relevant
   L3 entries (by FTS + recency), and open tool-calls. It packs them
   into the SDK system prompt within a fixed token budget (spec §9).
2. **Tool routing** — every SDK `tool_use` event dispatches to a
   handler that issues an HTTP request to the daemon. The daemon is
   the only thing that writes SQLite.
3. **Tool-result clearing** — after the assistant turn closes, the
   bridge signals the daemon to null large tool-call payloads that
   have been superseded by memory entries.
4. **Event streaming** — SDK events fan out over WebSocket to the
   renderer so the UI can render tool-use pills, token counts, and
   progress bars in real time.

---

## Project workspace layout

Each project is a self-contained folder, copy-paste portable.

```
projects/<name>/
  config.toml           # project-scoped overrides (ops defaults, paths)
  iris.sqlite           # created on first open
  memory/               # regenerated from SQLite, user-editable via UI
  datasets/{raw,derived}/<id>/<sha>.<ext>
  artifacts/<sha>/...
  ops/<op>/v<semver>/   # project-scoped skills (Phase 8+)
  indexes/              # V2+ vector index
```

Global config lives in [`configs/config.toml`](../configs/config.toml)
(single TOML after REVAMP Phase 0; replaces the legacy YAML quartet).
`.iris/active_project` at the repo root records the currently open
project for CLI + webapp.

Full contract: [`projects.md`](projects.md) (rewritten under Task 10.2).

---

## Request flow walkthrough

A user types "plot the spectrogram of channel 861 between 15 and 16
seconds." Here is the full path from keystroke to plot.

```
1. Browser
   |   WebSocket send: {"type":"user_message","text":"plot the spectrogram..."}
   v
2. Express webapp (:4001)
   |   agent-bridge receives message
   |   GET :4002/memory/slice?session=...  (context slice)
   |   SDK query(prompt=text, system=slice, tools=[run_pipeline, propose_memory, ...])
   v
3. Claude Code SDK
   |   Plans: call `run_pipeline` with
   |     "window_ms[15000,16000].mea_trace(861).butter_bandpass.spectrogram"
   |   Emits tool_use
   v
4. agent-bridge tool handler
   |   POST :4002/runs {dsl, project_id, session_id}
   v
5. Daemon /runs route
   |   INSERT events (run_started)
   |   PipelineExecutor runs AST (engine)
   |     - reads dataset by sha from datasets/raw/<id>/
   |     - hits cache or computes
   |     - writes artifact PNG under artifacts/<sha>/
   |   INSERT runs, artifacts, events (run_finished)
   |   Returns {run_id, artifact_sha, preview_url}
   v
6. agent-bridge
   |   tool_result -> SDK, forwards over WebSocket as tool_use + artifact event
   v
7. Browser
   |   Renderer fetches artifact via :4001 -> :4002 proxy
   |   Shows plot inline; assistant's narration streams in
   v
8. Session close (later)
   |   extraction.py proposes memory entries from the turn
   |   User approves -> markdown_sync regenerates memory/*.md
   |   tool-result clearing nulls the large result payload
```

Every step that mutates state produces an `events` row with a hash
chained off the previous event, so a full replay of the project is
always possible from L0.

---

## Pointers

- Spec (authoritative, deep): [`memory-restructure.md`](memory-restructure.md)
- Build order: [`REVAMP.md`](REVAMP.md)
- Memory code map: [`../src/iris/projects/CLAUDE.md`](../src/iris/projects/CLAUDE.md)
- Daemon routes: [`../src/iris/daemon/routes/CLAUDE.md`](../src/iris/daemon/routes/CLAUDE.md)
- Webapp server: [`../iris-app/server/CLAUDE.md`](../iris-app/server/CLAUDE.md)
- Op math: [`operations.md`](operations.md)
