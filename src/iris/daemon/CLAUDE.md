# src/iris/daemon/ — HTTP shell for the Python engine

FastAPI app (`iris.daemon.app:app`, port 4002) that exposes the engine,
operation registry, project lifecycle, and (Phases 2+) the memory system to the
Express backend. Nothing here owns domain logic — everything is a thin router
over `src/iris/engine/` or `src/iris/projects/`.

## 1. What this dir is for

- Single HTTP process the webapp can call. Express never imports Python.
- Streams plot + report events over WebSocket-adjacent polling endpoints.
- Serves memory reads/writes once Phase 2+ routes land — see
  [`routes/CLAUDE.md`](routes/CLAUDE.md).

## 2. What's changing (REVAMP sweep)

- Phase 0 Task 0.5 stubbed `routes/memory.py` with 503 responses. All memory
  endpoints stay 503 until Phases 2–10 replace them.
- Phase 1.10 adds `/projects/*` routes backed by the rebuilt lifecycle in
  `iris.projects`.
- Phase 2.4 brings back `/memory/append_event`, `/memory/sessions/*`.
- Phase 4 returns `/memory/entries/*` (propose/commit/query).
- Phase 9 serves `/memory/slice` (read-only slice builder).
- Phase 10 adds the Markdown watcher + writeback endpoints.

## 3. Migration notes

- `routes/pipeline.py` must tolerate `NotImplementedError` from the memory
  layer until Phase 2 lands (see Task 0.5).
- New routes must use the standard FastAPI dependency-injection pattern for
  project path resolution (`projects.resolve_active_project`).
- Every mutating memory endpoint must also append an event via
  `iris.projects.events.append_event` once Phase 2.1 ships.

## 4. Dependencies

- `fastapi`, `uvicorn` — HTTP server.
- `iris.engine`, `iris.projects` — domain layer.
- `watchdog` — Phase 10 filesystem watcher lives in `daemon/services/`.

## 5. Implementation order hints

1. Keep `app.py` dumb — just wiring.
2. Put long-running work in `daemon/services/` (Phase 10 watcher, Phase 11
   embedding worker, Phase 13 reflection job, Phase 14 summarizer).
3. Route handlers return pydantic models; domain modules return plain dicts or
   dataclasses. The routers adapt.

## See also
- [../projects/CLAUDE.md](../projects/CLAUDE.md) — memory module map
- [routes/CLAUDE.md](routes/CLAUDE.md) — endpoint inventory
- [../../../REVAMP.md](../../../REVAMP.md) — task ledger
