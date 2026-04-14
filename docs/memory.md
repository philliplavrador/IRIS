# IRIS Memory Layer

Authoritative overview of the V2 memory system (REVAMP Phases 1–17).
For the design rationale, see [`memory-restructure.md`](memory-restructure.md).
For the build ledger, see [`REVAMP.md`](REVAMP.md).

## Three storage substrates

| # | Substrate | Role | Owning code |
|---|---|---|---|
| 1 | SQLite `iris.sqlite` | Source of truth: projects, sessions, events, messages, tool_calls, memory_entries, datasets, artifacts, runs, operations, retrieval_events. | `src/iris/projects/db.py` + per-module writers |
| 2 | Content-addressed filesystem | SHA-256-keyed artifact + dataset store — plots, reports, code, caches. | `src/iris/projects/artifacts.py` |
| 3 | Curated Markdown | Regenerated human view of the DB: `memory/PROJECT.md`, `DECISIONS.md`, `OPEN_QUESTIONS.md`. Never the source of truth. | `src/iris/projects/markdown_sync.py` |

## Unified L3 memory entries

Every semantic memory lives in `memory_entries`:

- `finding`, `decision`, `caveat`, `open_question`, `assumption`,
  `failure_reflection`, `reflection`, `preference`, `session_summary`.

Proposals land as `status='draft'`; a subsequent `commit_pending` flips
them to `active`. Contradictions, staleness, and supersession transition
entries to `contradicted`, `stale`, or `superseded` without deleting
history.

## Pipelines

| Stage | Module | When it runs |
|---|---|---|
| Session-end extraction | `extraction.extract_session` | On `end_session` (or manual `/memory/extract`) |
| Per-turn extraction | `extraction.extract_turn` | After each substantive assistant message (Mem0-style, Jaccard dedup) |
| Retrieval gate | `retrieval.should_retrieve` | Per user turn, before slice assembly |
| Retrieval | `retrieval.recall` | SQL filter → FTS5 BM25 → optional vector RRF → triple-weighted rerank (α=0.5, β=0.3, γ=0.2) |
| Slice build | `slice_builder.build_slice` | Per user turn; 7-segment budgeted context |
| Reflection | `reflection.run_reflection` | When unreflected importance > 40 |
| Summarization | `summarization.summarize_session`, `summarize_summaries` | At session close; when N summaries accumulate |
| Op validation | `op_validation.validate_operation` | On generated-op propose (3-stage sandbox: static → pytest → sample run) |
| Contradictions | `contradictions.detect_contradictions` | On new active memory; flips loser to `contradicted` |
| Staleness | `staleness.scan` | Cron / manual; flips `finding` > 90d, `assumption` > 30d, `open_question` > 60d to `stale` |
| Usage tracking | `retrieval._record_retrieval_event` + `messages._scan_citations` | Retrieval emits event; assistant message cites memory_id → `was_used` updated |

## HTTP surface

All endpoints live under `/api/memory/*` in `src/iris/daemon/routes/memory.py`.
Express proxies 1:1 at `iris-app/server/routes/memory.ts`.

Highlights: `/memory/slice`, `/memory/recall`, `/memory/entries*`,
`/memory/extract`, `/memory/extract/turn`, `/memory/pending/count`,
`/memory/reflect`, `/memory/operations/propose`,
`/memory/operations/{id}/validate`, `/memory/contradictions*`,
`/memory/staleness/scan`, `/memory/metrics`.

## See also

- [`memory-restructure.md`](memory-restructure.md) — design spec (authoritative)
- [`architecture.md`](architecture.md) — system shape
- [`../src/iris/projects/CLAUDE.md`](../src/iris/projects/CLAUDE.md) — module map
