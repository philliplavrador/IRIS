# tests/ — test navigation

Pytest suite using synthetic data. Runs headless — no hardware data or
uploads required.

## Current test files (post-Phase 0)

| File | Scope |
|---|---|
| `test_op_registry.py` | Every op in `TYPE_TRANSITIONS` is registered, every registered op has a handler, type transitions correct. |
| `test_engine_types.py` | Data-type dataclasses + type-system invariants. |
| `test_engine_ops.py` | Per-op handler behavior on synthetic fixtures. |
| `test_engine_executor.py` | Pipeline execution end-to-end on synthetic sources. |
| `test_dsl_parser.py` | Parser for the DSL string form. |
| `test_cache.py` | Two-tier cache correctness (memory + disk). |
| `test_cli.py` | `iris` CLI surface. |
| `test_daemon.py` | FastAPI daemon endpoints (health + stable routes). |
| `test_sessions.py` | Plot-session directory + manifest + sidecar. Renamed to `test_plot_sessions.py` when `sessions.py` is renamed in Task 2.3. |
| `conftest.py`, `synthetic_data.py`, `fixtures/` | Shared pytest wiring. |

## Planned new test files (REVAMP)

| Phase | Task | File | Coverage |
|---|---|---|---|
| 1 | 1.4 | `test_db.py` | schema apply, idempotency, FKs, WAL files, FTS5 virtual tables. |
| 1 | 1.6 | `test_projects_lifecycle.py` | create/open/list/delete/active-project. |
| 2 | 2.2 | `test_events.py` | append + hash-chain verification + integrity on tamper. |
| 2 | 2.3 | `test_memory_sessions.py` | start/end/get session rows. |
| 3 | 3.3 | `test_messages.py` | append + FTS5 BM25 search. |
| 3 | 3.3 | `test_tool_calls.py` | tool-call persistence + artifact attachment + clearing summary. |
| 4 | 4.3 | `test_memory_entries.py` | propose→commit/discard, query, supersede, touch, soft-delete. |
| 4 | 4.4 | `test_extraction.py` | LLM session-end extractor (mocked). |
| 4 | 4.5 | `test_markdown_sync.py` | regenerate + ingest (round-trip). |
| 5 | 5.2 | `test_artifacts.py` | SHA-256 addressing, dedup, metadata. |
| 6 | 6.5 | `test_datasets.py` | import, raw version capture, profiling. |
| 7 | 7.4 | `test_runs.py` | start/complete/fail + lineage queries. |
| 8 | 8.5 | `test_operations_store.py` | register/find/list/record_execution. |
| 9 | 9.2 | `test_retrieval.py` | filter→FTS5→rerank path; `should_retrieve` heuristics. |
| 9 | 9.3 | `test_slice_builder.py` | 7-segment assembly, token budgeting. |
| 10 | 10.2 | `test_markdown_watcher.py` | watchdog-triggered ingest loop. |
| 11 | 11.6 | `test_embeddings.py` + `test_retrieval_hybrid.py` | V2 vector retrieval + fusion. |
| 13 | 13.2 | `test_reflection.py` | importance-trigger + insight write. |
| 14 | 14.2 | `test_summarization.py` | session summary + summary-of-summaries. |
| 15 | 15.2 | `test_op_validation.py` | sandbox validation pipeline. |
| 16 | 16.3 | `test_contradictions.py` + `test_staleness.py` | detect/resolve + decay. |
| 17 | 17.2 | `test_retrieval_metrics.py` | retrieval_events + citation scan. |

The old scale suite (`tests/memory_scale/`) was deleted in Task 0.4. A new
load suite lands in REVAMP Phase 17 once retrieval metrics exist.

## Running tests

```bash
uv run pytest -x -q          # Python tests
cd iris-app && npm test      # Webapp tests (vitest + testing-library)
```

The full REVAMP validation gate (every task) is in
[`../docs/REVAMP.md`](../docs/REVAMP.md#standard-validation-gate-every-task).

## Adding a test for a new op

```python
def test_<op_name>_transitions():
    registry, _ = create_registry()
    assert registry.validate_type_transition("<op_name>", InputType) is OutputType
```

## See also
- [../CLAUDE.md](../CLAUDE.md) — repo root nav
- [../src/iris/CLAUDE.md](../src/iris/CLAUDE.md) — package layout + op authoring
- [../src/iris/projects/CLAUDE.md](../src/iris/projects/CLAUDE.md) — memory module map
- [../docs/operations.md](../docs/operations.md) — op catalog
- [../docs/REVAMP.md](../docs/REVAMP.md) — task ledger
