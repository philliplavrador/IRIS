# iris-app/src/renderer/ — React frontend module map

Vite + React 19 + Tailwind 4 + Zustand. Renders the workspace (chat + tabs +
status bar) and the project picker. All backend communication flows through
Express on 4001 (`/api`, `/ws`) — the renderer never imports Python or talks
to 4002.

## 1. What this dir is for

- Project picker (`pages/ProjectsPage.tsx`) — create / open / rename / delete.
- Workspace page (`pages/WorkspacePage.tsx`) — 3-panel layout:
  - Chat (`components/chat/`) — virtualized message list + input.
  - Workspace tabs (`components/workspace/`) — files, plots, memory
    inspector, curation ritual, behavior dials, settings.
  - Status bar — active project + dial readouts + daemon health.
- Plot + report viewers (`components/visualization/`, `ReportViewer.tsx`).

## 2. What's changing (REVAMP sweep)

Appendix A of `IRIS Memory Restructure.md` describes the full new UI surface
(curation panel, provenance drawer, contradictions inbox, dataset cards,
operation catalog). That UX work is **deferred** until the memory backend
stabilizes — concretely, until Phase 17 is green.

Until then, the renderer needs only these touch-ups:

| Phase | Task | Component | Change |
|---|---|---|---|
| 1 | 1.11 | `stores/projectStore.ts`, `pages/ProjectsPage.tsx` | Point to new `/api/projects/*` endpoints; drop legacy fields (`claude_history.md`, `ledger.sqlite`). |
| 4 | 4.7 | `components/workspace/CurationRitual.tsx` | Point at new `/memory/entries` endpoints; pending→committed flow. |
| 9 | 9.5 | `hooks/useAgentMessages.ts`, `agent-bridge.ts` consumer | Accept slice-based system prompt; no behavior change in UI. |
| 10 | 10.5 | `components/workspace/MemoryInspector.tsx` | Surface Markdown-file draft proposals (ingest path). |

The full Appendix A build is tracked separately as Phases 18–24 (not yet in
REVAMP).

## 3. Migration notes

- Remove any client-side references to `ledger.sqlite`, `knowledge.sqlite`,
  `claude_history.md`, `profile.json`, or the L0/L1/L2/L3/L4 vocabulary. The
  new terms are: **sessions, events, messages, tool_calls, memory_entries,
  artifacts, datasets, runs, operations**.
- Zustand stores should expose one action per new daemon endpoint (mirror the
  proxy in `iris-app/server/routes/memory.ts`).
- The `MemoryInspector` tab is the debugging view; the `CurationRitual` tab
  is the approval flow. Do not merge them — they have different affordances.

## 4. Dependencies

- React 19, Vite, Tailwind 4, Radix UI, Zustand, `@tanstack/react-virtual`.
- WebSocket via `useWebSocket` hook; debounced batching matches the server.
- No direct daemon access — always go through `/api/*`.

## 5. Implementation order hints

- New features land behind a feature flag in `lib/flags.ts` until the
  corresponding backend phase is green (prevents partial builds on `main`).
- Component tests in `__tests__/` should mock the API layer, not WebSocket.
- Designs for Appendix A UX live in `IRIS Memory Restructure.md` — read the
  appendix before touching curation/contradictions components.

## See also
- [../../CLAUDE.md](../../CLAUDE.md) — webapp overview
- [../server/CLAUDE.md](../server/CLAUDE.md) — Express contract
- [../../../REVAMP.md](../../../REVAMP.md) — task ledger
- `IRIS Memory Restructure.md` Appendix A — deferred UX spec
