# src/iris/daemon/routes/ — endpoint inventory

Each file registers one FastAPI router and is mounted in `daemon/app.py`.

## 1. What this dir is for

Request handling only. Parse body, resolve project, call into
`iris.projects.*` or `iris.engine.*`, shape the response. No business logic.

## 2. Current endpoints (post-Phase 0)

| Router | Status | Endpoints |
|---|---|---|
| `config.py` | stable | `GET /config` |
| `ops.py` | stable | `GET /ops`, `POST /ops/run` |
| `pipeline.py` | degraded (Task 0.5) | `POST /pipeline/run` — runs ops but skips memory side-effects under `try/except NotImplementedError` |
| `projects.py` | scheduled rewrite (Task 1.10) | `POST /projects`, `GET /projects`, `GET /projects/{name}`, `DELETE /projects/{name}`, `POST /projects/active` |
| `sessions.py` | stable (plot sessions, not memory) | `GET /sessions/...` — renamed once 2.3 lands |
| `memory.py` | **stub (Task 0.5)** — every endpoint returns 503 | `/memory/*` |

## 3. Planned endpoints (REVAMP)

| Phase | Task | Router | New endpoints |
|---|---|---|---|
| 2 | 2.4 | `memory.py` | `POST /memory/events`, `GET /memory/events`, `POST /memory/sessions/start`, `POST /memory/sessions/end`, `GET /memory/sessions/{id}` |
| 3 | 3.4 | `memory.py` | `POST /memory/messages`, `GET /memory/messages/search`, `POST /memory/tool_calls`, `POST /memory/tool_calls/{id}/attach` |
| 4 | 4.6 | `memory.py` | `POST /memory/entries/propose`, `POST /memory/entries/{id}/commit`, `POST /memory/entries/{id}/discard`, `GET /memory/entries`, `POST /memory/entries/{id}/status`, `POST /memory/entries/{id}/supersede`, `POST /memory/entries/{id}/touch` |
| 5 | 5.3 | `memory.py` | `POST /memory/artifacts`, `GET /memory/artifacts/{sha}`, `GET /memory/artifacts/{sha}/bytes` |
| 6 | 6.4 | `memory.py` | `POST /memory/datasets`, `GET /memory/datasets`, `POST /memory/datasets/{id}/profile` |
| 7 | 7.2 | `memory.py` | `POST /memory/runs/start`, `POST /memory/runs/{id}/complete`, `GET /memory/runs`, `GET /memory/runs/{id}/lineage` |
| 8 | 8.3 | `memory.py` | `POST /memory/operations`, `GET /memory/operations`, `POST /memory/operations/{id}/record` |
| 9 | 9.4 | `memory.py` | `POST /memory/slice` |
| 10 | 10.3 | `memory.py` | `POST /memory/markdown/regenerate`, `POST /memory/markdown/ingest` |

## 4. Dependencies

- FastAPI routers.
- Project path dependency (`resolve_active_project`) from `iris.projects`.
- Pydantic models defined per-router (no shared schema module — keep routers
  isolated so Phase churn doesn't ripple).

## 5. Implementation order hints

- Every new endpoint lands in the same commit as the test in
  `tests/test_daemon_<feature>.py`.
- Keep response envelopes uniform: `{ "data": ... }` on success, `{ "error":
  "..." }` on failure, FastAPI standard status codes.
- Memory endpoints that mutate MUST call `events.append_event` in the same
  transaction as the domain write (Phase 2.1 enforces this at the module
  layer).

## See also
- [../CLAUDE.md](../CLAUDE.md) — daemon overview
- [../../projects/CLAUDE.md](../../projects/CLAUDE.md) — module map
- [../../../../docs/REVAMP.md](../../../../docs/REVAMP.md) — task ledger
