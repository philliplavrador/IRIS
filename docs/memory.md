# IRIS Memory System

Practical code-pointer reference for the memory layer. Design decisions
and rationale live in [`IRIS Memory Restructure.md`](../IRIS%20Memory%20Restructure.md)
(the spec); the ordered build ledger lives in [`REVAMP.md`](../REVAMP.md).
This doc tells implementers **where each concept lives in the tree** and
**how the pieces fit together at runtime**. If you are about to write code,
read the module map in
[`src/iris/projects/CLAUDE.md`](../src/iris/projects/CLAUDE.md) alongside
this file.

---

## Goals

IRIS is meant to be a **persistent research partner** across sessions. The
memory layer exists so that when a user closes the app on Friday and reopens
it on Monday, the agent still knows:

- What datasets this project has and how their columns were annotated.
- What was found in prior sessions (findings, caveats, open questions).
- What preferences the user stated (units, plot styles, tolerances).
- Which operations were run, on which data, with what parameters.
- Which conclusions are stale, contradicted, or superseded.

Non-goals: replacing the analysis engine's cache, replacing the artifact
store with general-purpose object storage, serving cross-project search in
V1.

---

## The storage triad

Every durable piece of state lives in exactly one of three substrates
(spec §5.1). A single project workspace contains all three.

| Store | Medium | Source of truth for | Touchpoints |
|---|---|---|---|
| **1. SQLite** | `projects/<name>/iris.sqlite` | Everything programmatic: events, sessions, messages, tool_calls, memory_entries, artifacts metadata, datasets, runs, operations | [`src/iris/projects/schema.sql`](../src/iris/projects/schema.sql), [`db.py`](../src/iris/projects/db.py) |
| **2. Content-addressed FS** | `artifacts/<sha256>/`, `datasets/raw/<sha>/`, `ops/<name>/v<semver>/` | Immutable bytes — plots, reports, generated code, uploaded data | [`artifacts.py`](../src/iris/projects/artifacts.py), [`datasets.py`](../src/iris/projects/datasets.py) |
| **3. Curated Markdown** | `memory/*.md` (findings, decisions, caveats, open_questions, preferences) | Human-readable view, **regenerated from SQLite** on demand | [`markdown_sync.py`](../src/iris/projects/markdown_sync.py) |

Rules:

- SQLite is canonical. Markdown is derived.
- Artifact metadata rows point at content-addressed paths; the bytes never
  get rewritten, so the hash is the permanent identity.
- User edits to `memory/*.md` are watched (Phase 10) and become **draft
  proposals** in SQLite — never committed automatically.
- `iris.sqlite` is runtime-created. It is never committed and never part
  of the `projects/TEMPLATE/` skeleton.

---

## Layers

The old L0–L4 tables are gone (Phase 0). The new layout is flatter and
tracks the runtime lifecycle rather than a conceptual hierarchy.

### Events log + hash chain

- Table: `events` (append-only, one row per mutation).
- Column set: `id`, `session_id?`, `kind`, `payload_json`, `prev_sha`,
  `sha` (SHA-256 of `prev_sha || kind || payload_json`).
- Every memory-layer write path calls
  [`events.append_event`](../src/iris/projects/events.py) in the same
  transaction as its domain write.
- `events.verify_chain` walks the log and flags any broken link — this is
  what the V1 acceptance gate (Task 10.4 step 10) exercises.

Spec refs: §4 L4, §7.1, §7.2.

### Messages + tool_calls with FTS5

- Tables: `messages`, `tool_calls`, plus FTS5 virtual table
  `messages_fts` (BM25 ranking built-in).
- Every chat turn writes a row to `messages`; every tool invocation writes
  a row to `tool_calls` and optionally an artifact via
  `tool_calls.attach_output_artifact`.
- Full-text search is exposed via
  [`messages.search(query, k)`](../src/iris/projects/messages.py) — the V1
  retrieval path delegates here before any reranking.
- Tool-call rows carry a `summary` column; once the raw output is old
  enough the body is replaced with a short summary (see
  **Tool-result clearing** below).

Spec refs: §7.1, §9.3.

### Memory entries (unified L3)

One table, many memory types. This is what makes the layer L3 in the old
taxonomy, but stored flat for indexability.

- Table: `memory_entries` + `memory_entries_fts`.
- Types: `finding`, `decision`, `caveat`, `open_question`, `preference`,
  and (V2) `reflection`, `session_summary`.
- Status machine: `pending` → `committed` | `discarded`; committed entries
  can later become `stale`, `contradicted`, or `superseded`. Soft-delete
  via `status='deleted'` — rows are never dropped.
- API: [`memory_entries.propose`, `commit_pending`, `discard_pending`,
  `query`, `set_status`, `supersede`, `soft_delete`, `touch`](../src/iris/projects/memory_entries.py).
- Every status transition appends an event.

Spec refs: §4 L3, §7.1, §10.1, §10.4.

### Runs DAG

- Table: `runs`.
- Every pipeline execution (DSL run, profile job, reflection job) opens a
  run row at start and closes it at finish (or failure).
- Runs link to their inputs (dataset versions, prior runs, op versions)
  and their outputs (artifacts, memory_entries). This gives provenance:
  "which memory cited which plot cited which run cited which dataset?"
- API: [`runs.start_run`, `complete_run`, `fail_run`, `query_lineage`,
  `list_runs`](../src/iris/projects/runs.py).
- `engine/executor.py` is rewired in Phase 7 so that **no pipeline call
  completes without producing a run row**.

Spec refs: §4 L4, §7.1.

### Operations catalog

- Tables: `operations`, `operation_executions`, `operations_fts`.
- The 17 hardcoded ops register themselves at startup; Phase 8+ adds
  per-project versioned ops under `projects/<name>/ops/<name>/v<semver>/`.
- `operations_store.record_execution` writes a row per op invocation so
  the agent can answer "have we run bandpass on dataset foo yet?"
- V2 adds `propose_operation` for LLM-generated ops, gated by
  `op_validation.validate_operation`.

Spec refs: §4 L5, §7.1, §12.

---

## Event-sourced semantics

The single invariant holding the system together:

> **Every mutation of durable state appends an event first (or in the
> same transaction) via `events.append_event`.**

Consequences:

- Replaying the `events` table reconstructs any derived index.
- The hash chain turns tampering into a visible integrity error.
- Tests can assert on event sequences rather than on table snapshots.
- Markdown regeneration is a pure function of the committed event set.

Daemon routers enforce this at the HTTP boundary — see the note in
[`src/iris/daemon/routes/CLAUDE.md`](../src/iris/daemon/routes/CLAUDE.md)
§5: *"Memory endpoints that mutate MUST call `events.append_event` in
the same transaction as the domain write."*

---

## Tool-result clearing (spec §9.3)

Tool outputs dominate context windows. A 12k-row profile printout from
last Tuesday is not worth carrying into today's system prompt — but
losing the fact that the tool was *called* is unacceptable because the
agent needs to know the call happened.

The compaction rule:

1. Every `tool_calls` row starts with the full `output_json` blob.
2. After the output is either: (a) attached to a content-addressed
   artifact, or (b) older than the current session, or (c) followed
   by enough newer turns, the row is **summarized in place**.
3. `tool_calls.summarize_for_clearing(tool_call_id)` replaces the full
   blob with `{"summary": "...", "artifact_sha": "..."}` and leaves the
   message intact. The bytes, if any, remain accessible via the
   artifact store.
4. Retrieval still surfaces the summary + a pointer; if the user asks
   for the underlying bytes, the agent fetches them deliberately.

This is what prevents the "tool-result bloat" pathology in spec §11.6.
The stub lives in [`tool_calls.py`](../src/iris/projects/tool_calls.py);
the policy (when to clear, what to keep inline) is refined in Phase 4
once extraction lands.

---

## Session lifecycle

A "session" here means a **memory-layer session** — a bounded span of
user ↔ agent interaction. Distinct from the plot sessions in
[`src/iris/plot_sessions.py`](../src/iris/plot_sessions.py) (note the
rename in Task 2.3).

Flow:

1. **Start.** Webapp hits `POST /memory/sessions/start` →
   [`sessions.start_session`](../src/iris/projects/sessions.py) writes a
   row and appends `session_started` event.
2. **Messages.** Each turn hits `POST /memory/messages` and, if the
   model called a tool, `POST /memory/tool_calls`. Both paths append
   events.
3. **Mid-session extraction** (V2, Phase 12). `extraction.extract_turn`
   proposes draft memories continuously instead of only at end.
4. **End.** Webapp hits `POST /memory/sessions/end`. That handler:
   a. Runs [`extraction.extract_session`](../src/iris/projects/extraction.py),
      which asks Claude to distill findings/caveats/questions and calls
      `memory_entries.propose(..., status='pending')`.
   b. (V2, Phase 14) Runs `summarization.summarize_session` to produce
      a `session_summary` memory entry.
   c. Appends `session_ended` event.
5. **Review.** Proposed entries sit in `status='pending'` until the
   user reviews them (see **Curation ritual** next).

---

## Curation ritual (propose → commit / discard)

Nothing the agent extracts becomes "real" memory until the user says so.

The loop:

1. **Propose.** Either extraction or profile annotations or the agent
   itself call `memory_entries.propose(kind, content, evidence_refs)`.
   The row is written with `status='pending'`.
2. **Surface.** The webapp Curation panel calls
   `GET /memory/entries?status=pending` and renders each draft.
3. **Act.** User clicks Commit or Discard.
   - `POST /memory/entries/{id}/commit` → `status='committed'`, fires
     `entry_committed` event, triggers Markdown regeneration.
   - `POST /memory/entries/{id}/discard` → `status='discarded'`, fires
     `entry_discarded` event, no Markdown touch.
4. **Later transitions.** A committed entry can be superseded by another
   (`supersede`), marked stale (`set_status('stale')`), or
   soft-deleted. Each transition is event-logged.

Markdown user-edits follow the same ritual: the watcher detects a
change, diffs it against the DB view, and files a pending proposal that
the user must confirm. This is what spec §10.1 calls the "no magic
writes" invariant.

---

## Retrieval pipeline

### V1 (Phase 9)

Three stages, all in [`retrieval.py`](../src/iris/projects/retrieval.py):

1. **Should we retrieve?** `should_retrieve(query, context)` short-circuits
   cheap turns (single-token replies, pure tool callbacks, greetings).
   Based on spec §8.2 conditional triggers.
2. **Candidate set (filter + FTS5).** `recall(query, k)` filters
   `memory_entries` by `status IN ('committed','stale')`, then runs
   FTS5 BM25 search over `memory_entries_fts`. Candidate cap is typically
   `3k`.
3. **Rerank.** Triple-weighted score:
   `score = α · bm25_norm + β · recency + γ · importance`,
   weights from `config.toml [memory.retrieval]`. Top `k` returned.

### V2 (Phase 11)

- `migrations/v2.sql` adds `*_vec` virtual tables backed by
  [`sqlite-vec`](https://github.com/asg017/sqlite-vec).
- `embeddings.py` provides pluggable providers
  (`SentenceTransformerProvider`, `OllamaProvider`).
- `embedding_worker.py` drains a queue and backfills vectors lazily.
- `retrieval.py` changes to hybrid: union the FTS5 and vector top-N,
  fuse with reciprocal rank fusion, then apply the V1 rerank on the
  merged set.

Spec refs: §8, §11.5, §14.2.

---

## Slice builder (seven-segment assembly)

The system prompt the agent sees is not one blob — it's assembled fresh
per turn from seven named segments. Source:
[`slice_builder.build_slice`](../src/iris/projects/slice_builder.py).

| # | Segment | Source | Typical size |
|---|---|---|---|
| 1 | Project identity | `config.toml` + project row | tiny, ~200 tok |
| 2 | Active datasets + schemas | `datasets`, `dataset_versions`, schema_json | small |
| 3 | Pinned memories (preferences, critical caveats) | `memory_entries` where `pinned=1` | small |
| 4 | Retrieved memories | `retrieval.recall(current_query)` | budgeted |
| 5 | Recent runs (current session) | `runs` last N | small |
| 6 | Session scratchpad (rolling window of messages) | `messages` last M | largest |
| 7 | Available operations slice | `operations_store.list(relevant)` | bounded |

Each segment has a token budget (spec §9.2). When the total blows
through the window, segments 6 and 7 are trimmed first; segment 3
(pinned) is never trimmed.

The slice is served read-only over `POST /memory/slice`. The webapp
prepends it to the user's turn before calling the Agent SDK.

---

## What's V1 vs V2

V1 is "enough to be useful." V2 is "enough to be smart." Everything
under V2 is deferred past the `v1.0-memory` tag (Task 10.4).

| Capability | V1 | V2 | Where |
|---|---|---|---|
| Event log + hash chain | yes | — | Phase 2 |
| Messages / tool_calls / FTS5 | yes | — | Phase 3 |
| Unified memory_entries + curation | yes | — | Phase 4 |
| Markdown regeneration + ingest | yes | — | Phase 4, 10 |
| Artifacts (CAS) + datasets + profile | yes | — | Phase 5, 6 |
| Runs DAG | yes | — | Phase 7 |
| Operations catalog (hardcoded register) | yes | `propose_operation` + validation | Phase 8, 15 |
| Retrieval (FTS5 + triple-weighted rerank) | yes | +vector hybrid (sqlite-vec) | Phase 9, 11 |
| Slice builder (7 segments) | yes | — | Phase 9 |
| Session-end extraction | yes | +per-turn (Mem0-style) | Phase 4, 12 |
| Reflection (importance-triggered) | — | yes | Phase 13 |
| Progressive summarization | — | yes | Phase 14 |
| Contradiction detection | — | yes | Phase 16 |
| Staleness detection | — | yes | Phase 16 |
| Retrieval metrics + citation mining | — | yes | Phase 17 |

Spec refs: §14.1 (V1), §14.2 (V2), §14.3 (V3 — out of scope here).

---

## See also

- [`IRIS Memory Restructure.md`](../IRIS%20Memory%20Restructure.md) — the design spec (authoritative; jump to the cited §).
- [`REVAMP.md`](../REVAMP.md) — the task ledger (read this first when implementing).
- [`src/iris/projects/CLAUDE.md`](../src/iris/projects/CLAUDE.md) — per-file module map with task numbers.
- [`src/iris/daemon/CLAUDE.md`](../src/iris/daemon/CLAUDE.md) — HTTP shell overview.
- [`src/iris/daemon/routes/CLAUDE.md`](../src/iris/daemon/routes/CLAUDE.md) — endpoint inventory by phase.
- [`docs/projects.md`](projects.md) — project workspace contract.
- [`docs/architecture.md`](architecture.md) — system-wide architecture.
