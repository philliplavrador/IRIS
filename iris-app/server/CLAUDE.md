# iris-app/server/ — Express proxy + agent bridge

The Node/Express process (port 4001) is the single surface the React frontend
talks to. It (1) proxies everything domain-shaped to the Python daemon on
4002, and (2) hosts the Claude Code Agent SDK bridge that streams chat
messages over WebSocket.

## 1. What this dir is for

- **Pass-through HTTP:** `routes/projects.ts`, `routes/memory.ts` forward to
  the daemon via `services/daemon-client.ts`. No business logic here.
- **Agent bridge:** `agent-bridge.ts` wraps
  `@anthropic-ai/claude-code`'s `query()` and streams assistant/tool messages
  over WebSocket. The system prompt is assembled from the daemon's
  `POST /memory/slice` (Phase 9) plus project metadata.
- **Watchers:** `services/watchers.ts` watches `projects/<name>/artifacts/`
  and `projects/<name>/memory/*.md` and broadcasts updates to the frontend.

## 2. What's changing (REVAMP sweep)

- Memory routes move from the legacy L3 surface (`/memory/profile`,
  `/memory/propose`, `/memory/commit`, `/memory/ledger`) to the new endpoint
  set in `src/iris/daemon/routes/CLAUDE.md`. The Express layer is pure
  forwarding — each daemon endpoint gets a 1:1 proxy handler in
  `routes/memory.ts`.
- Phase 9.4 rewires `agent-bridge.ts` so the system prompt is built from the
  new slice endpoint (replaces the legacy digest + profile injection).
- Phase 10.4 adds a Markdown-file watcher broadcast so the frontend can
  surface `memory/*.md` edits as draft proposals.
- Appendix A UX (curation panel, contradictions inbox, etc.) is **deferred**
  until the backend has stabilized — REVAMP Phases 18+.

## 3. Migration notes

- Remove any direct FS reads of `ledger.sqlite` or `knowledge.sqlite`. Those
  paths no longer exist; everything goes through the daemon.
- `agent-bridge.ts` must not inject `claude_history.md` — that file is gone.
  Use the slice builder instead (Phase 9 lands the endpoint).
- Session IDs: the Claude Code SDK session is distinct from the memory-layer
  `sessions.session_id`. Keep the two IDs in a `{ sdkSessionId,
  memorySessionId }` pair on the project store; Task 2.3 clarifies the
  naming.

## 4. Dependencies

- `express`, `ws`, `@anthropic-ai/claude-code`, `chokidar` (watchers).
- Talks to the Python daemon via fetch; no direct DB access.
- Frontend is decoupled via WebSocket broadcasts — see
  `../src/renderer/CLAUDE.md`.

## 5. Implementation order hints

- Every new daemon route in REVAMP gets a matching proxy here in the same
  phase. Keep parity so the frontend never bypasses Express.
- Treat the daemon as the source of truth for errors: forward status codes
  and bodies unmodified (except to strip internal stack traces).
- When a phase lands, run `npm run dev` and hit the new endpoint end-to-end
  before closing the task — spec §Appendix B lists the expected curls.

## See also
- [../CLAUDE.md](../CLAUDE.md) — webapp overview
- [../../src/iris/daemon/routes/CLAUDE.md](../../src/iris/daemon/routes/CLAUDE.md) — daemon endpoint inventory
- [../src/renderer/CLAUDE.md](../src/renderer/CLAUDE.md) — frontend module map
- [../../REVAMP.md](../../REVAMP.md) — task ledger
