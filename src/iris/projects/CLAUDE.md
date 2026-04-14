# src/iris/projects/ — memory-layer module map

This package is the Python implementation of the IRIS memory system described in
[`IRIS Memory Restructure.md`](../../../IRIS%20Memory%20Restructure.md). It owns
the project workspace lifecycle, the SQLite schema (`iris.sqlite`), every memory
store, retrieval, extraction, and the Markdown sync layer. The daemon
(`src/iris/daemon/`) is a thin HTTP shell over this package; the webapp never
talks to these modules directly.

## 1. What this dir is for

Authoritative programmatic interface to a project's durable state. Spec §5.1
calls out three storage substrates — SQLite (Store 1), content-addressed
filesystem (Store 2), and curated Markdown (Store 3). All three are driven from
this package.

## 2. What's changing (REVAMP sweep)

Phase 0 nuked the old L0–L4 layer split (`knowledge.py`, `ledger.py`,
`recall.py`, `digest.py`, `conversation.py`, `profile.py`, `embeddings.py`,
`slice_builder.py`, `views.py`, `tools.py`, `archive.py`). Phases 1–17 rebuild
the package on a single `iris.sqlite` per spec §7. The list below is the target
state, with the REVAMP task that creates each file.

### Phase 1 — Foundation (SQLite + lifecycle)

| File | Role | Public API surface | Storage | Spec § | Task |
|---|---|---|---|---|---|
| [`schema.sql`](schema.sql) | Full V1 DDL | (data file) | SQLite | §7.1 | 1.2 |
| [`db.py`](db.py) | Connection + schema migration | `connect`, `init_schema`, `current_version`, `migrate` | SQLite | §5.1 Store 1, §7 | 1.3 |
| [`__init__.py`](__init__.py) | Project lifecycle CRUD | `create_project`, `open_project`, `list_projects`, `delete_project`, `resolve_active_project`, `set_active_project` | FS + SQLite | §6 | 1.5 |

### Phase 2 — Event log + memory sessions

| File | Role | Public API | Storage | Spec § | Task |
|---|---|---|---|---|---|
| [`events.py`](events.py) | Append-only event log with SHA-256 hash chain | `append_event`, `verify_chain`, event-type constants | `events` table | §4 L4, §7.1/§7.2 | 2.1 |
| [`sessions.py`](sessions.py) | Memory-layer session records (distinct from plot sessions) | `start_session`, `end_session`, `get_session` | `sessions` table | §7.1 | 2.3 |

Naming note: the existing `src/iris/sessions.py` (plot sessions + manifests) is
renamed to `src/iris/plot_sessions.py` in Task 2.3 so the name in this package
is unambiguous.

### Phase 3 — Messages, tool calls, FTS5

| File | Role | Public API | Storage | Spec § | Task |
|---|---|---|---|---|---|
| [`messages.py`](messages.py) | Chat message persistence + FTS5 BM25 search | `append_message`, `search` | `messages` + `messages_fts` | §7.1, §9.3 | 3.1 |
| [`tool_calls.py`](tool_calls.py) | Tool invocation records + clearing stub helper | `append_tool_call`, `attach_output_artifact`, `summarize_for_clearing` | `tool_calls` | §7.1, §9.3 | 3.2 |

### Phase 4 — Memory entries (unified L3) + Markdown sync

| File | Role | Public API | Storage | Spec § | Task |
|---|---|---|---|---|---|
| [`memory_entries.py`](memory_entries.py) | Unified L3 store (findings, decisions, caveats, open questions, …) | `propose`, `commit_pending`, `discard_pending`, `query`, `set_status`, `supersede`, `soft_delete`, `touch` | `memory_entries` + `memory_entries_fts` | §4 L3, §7.1, §10.1, §10.4 | 4.1 |
| [`extraction.py`](extraction.py) | Session-end LLM extraction of findings/caveats/questions | `extract_session` | calls `memory_entries.propose` | §10.1, §11.4 | 4.2 |
| [`markdown_sync.py`](markdown_sync.py) | Bidirectional sync between DB and `memory/*.md` | `regenerate_markdown`, `ingest_markdown` | FS ↔ SQLite | §5.1 Store 3 | 4.5 |

Phase 12 adds `extract_turn` to `extraction.py` (per-turn Mem0-style continuous
extraction).

### Phase 5 — Artifacts (content-addressed store)

| File | Role | Public API | Storage | Spec § | Task |
|---|---|---|---|---|---|
| [`artifacts.py`](artifacts.py) | SHA-256-addressed output store for plots, reports, code, caches | `store`, `get_bytes`, `get_metadata`, `list`, `soft_delete` | `artifacts` table + `artifacts/<sha>/` | §5.1 Store 2, §7.1 | 5.1 |

### Phase 6 — Datasets + profiling

| File | Role | Public API | Storage | Spec § | Task |
|---|---|---|---|---|---|
| [`datasets.py`](datasets.py) | Dataset import + raw-version capture | `import_dataset`, `list_datasets`, `get_version` | `datasets` + `dataset_versions` + `datasets/raw/` | §7.1 | 6.1 |
| [`transformations.py`](transformations.py) | Derived-version chaining | `record_derived_version` | `dataset_versions` | §7.1 | 6.2 |
| [`profile.py`](profile.py) | Column schema + stats + annotation proposals | `profile_dataset` | writes `schema_json` + proposes draft memories | §7.1 | 6.3 |

### Phase 7 — Runs DAG (provenance)

| File | Role | Public API | Storage | Spec § | Task |
|---|---|---|---|---|---|
| [`runs.py`](runs.py) | Analysis run lifecycle + lineage DAG | `start_run`, `complete_run`, `fail_run`, `query_lineage`, `list_runs` | `runs` table | §4 L4, §7.1 | 7.1 |

Phase 7 also re-wires `engine/executor.py` so every pipeline invocation produces
a run row.

### Phase 8 — Operations catalog

| File | Role | Public API | Storage | Spec § | Task |
|---|---|---|---|---|---|
| [`operations_store.py`](operations_store.py) | Operation catalog (hardcoded + generated) | `register`, `find`, `list`, `record_execution`, (V2) `propose_operation` | `operations` + `operation_executions` + `operations_fts` | §4 L5, §7.1, §12 | 8.1 |

### Phase 9 — Retrieval + slice builder (V1)

| File | Role | Public API | Storage | Spec § | Task |
|---|---|---|---|---|---|
| [`retrieval.py`](retrieval.py) | Three-stage retrieval (filter → FTS5 → triple-weighted rerank) | `should_retrieve`, `recall` | reads `memory_entries`, `memory_entries_fts` | §8, §11.5 | 9.1 |
| [`slice_builder.py`](slice_builder.py) | 7-segment context assembly for system prompt | `build_slice` | reads everything | §9.1, §9.2 | 9.3 |

### Phase 11 — V2 vector retrieval

| File | Role | Public API | Storage | Spec § | Task |
|---|---|---|---|---|---|
| [`migrations/v2.sql`](migrations/v2.sql) | sqlite-vec virtual tables | (data file) | `*_vec` virtual tables | §14.2 | 11.2 |
| [`embeddings.py`](embeddings.py) | Pluggable embedding provider | `EmbeddingProvider`, `SentenceTransformerProvider`, `OllamaProvider` | — | §14.2 | 11.3 |
| [`embedding_worker.py`](embedding_worker.py) | Background embedding job drain | (queue API) | writes `*_vec` | §14.2 | 11.4 |
| `retrieval.py` (updated) | Hybrid FTS5 ∪ vector via reciprocal rank fusion | (same) | — | §8 | 11.5 |

### Phase 13 — Reflection cycles (V2)

| File | Role | Public API | Storage | Spec § | Task |
|---|---|---|---|---|---|
| [`reflection.py`](reflection.py) | Importance-triggered higher-level insights | `should_reflect`, `run_reflection` | writes `memory_entries(memory_type='reflection')` | §10.2 | 13.1 |

### Phase 14 — Progressive summarization (V2)

| File | Role | Public API | Storage | Spec § | Task |
|---|---|---|---|---|---|
| [`summarization.py`](summarization.py) | Session summaries + summary-of-summaries | `summarize_session`, `summarize_summaries` | writes `sessions.summary` + `memory_entries(memory_type='session_summary')` | §10.2 | 14.1 |

### Phase 15 — Operation validation + generated-op pipeline (V2)

| File | Role | Public API | Storage | Spec § | Task |
|---|---|---|---|---|---|
| [`op_validation.py`](op_validation.py) | Static + unit + sample-run validation in a sandbox | `validate_operation` | updates `operations.validation_status` | §12.2 | 15.1 |

### Phase 16 — Contradictions + staleness (V2)

| File | Role | Public API | Storage | Spec § | Task |
|---|---|---|---|---|---|
| [`contradictions.py`](contradictions.py) | LLM-driven contradiction detection | `detect_contradictions`, `resolve` | `contradictions` + `memory_entries.status='contradicted'` | §10.3, §11.3 | 16.1 |
| [`staleness.py`](staleness.py) | Type-specific temporal decay | `scan` | `memory_entries.status='stale'` | §10.3 | 16.2 |

### Phase 17 — Retrieval metrics (V2)

| File | Role | Public API | Storage | Spec § | Task |
|---|---|---|---|---|---|
| [`migrations/v3.sql`](migrations/v3.sql) | `retrieval_events` table | (data file) | new table | §Appendix A.4 | 17.1 |
| `retrieval.py` (updated) | Records retrieved memory IDs per slice | (same) | `retrieval_events` | §Appendix A.4 | 17.1 |
| `messages.py` (updated) | Scans assistant messages for citations → flags `was_used` | (same) | `retrieval_events` | §Appendix A.4 | 17.1 |

## 3. Migration notes

- The old L0/L1/L2/L3/L4 split is gone. There is one SQLite file per project
  (`iris.sqlite`), schema version tracked via `PRAGMA user_version`.
- `iris.sqlite` is runtime-created by `db.init_schema()` — never committed,
  never in the TEMPLATE.
- Content-addressed artifacts, datasets, and versioned ops live on the
  filesystem next to the DB; their metadata lives in SQLite.
- Markdown files in `memory/` are a **regenerated** human view. The DB is
  source of truth. User edits are detected by `markdown_sync.ingest_markdown`
  and become draft proposals (never auto-committed).

## 4. Dependencies

- `sqlite3` (stdlib), `pathlib`, `hashlib`, `json` — always.
- `sqlite-vec` — added in Phase 11 (V2).
- `anthropic` (Python SDK) — Phase 4 extraction, Phase 13 reflection, Phase 14
  summarization, Phase 16 contradictions. Key from `ANTHROPIC_API_KEY`.
- `sentence-transformers` or Ollama — Phase 11 embedding providers (optional).
- `watchdog` — Phase 4 Markdown watcher (lives in `daemon/services/`).

## 5. Implementation order hints

Build strictly bottom-up:

1. `schema.sql` → `db.py` → `tests/test_db.py` → lifecycle in `__init__.py`.
2. `events.py` first (every later module logs events via it).
3. `sessions.py` next (messages/tool_calls/memory_entries all carry
   `session_id`).
4. `messages.py` + `tool_calls.py` land together; they share FTS5 patterns.
5. `memory_entries.py` is the widest-blast-radius module; freeze its API before
   anything above Phase 4 starts.
6. `artifacts.py` before anything that produces heavy outputs (plots in
   Phase 5, run outputs in Phase 7, operation code in Phase 8).
7. `retrieval.py` + `slice_builder.py` last in V1 — they read everything.

## See also
- [`../CLAUDE.md`](../CLAUDE.md) — package-level navigation
- [`../../../IRIS Memory Restructure.md`](../../../IRIS%20Memory%20Restructure.md) — design spec (authoritative)
- [`../../../REVAMP.md`](../../../REVAMP.md) — task ledger (this document)
- [`../daemon/CLAUDE.md`](../daemon/CLAUDE.md) — how these modules are exposed over HTTP
