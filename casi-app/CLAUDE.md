# casi-app/ — webapp navigation

The primary user interface for CASI. A local webapp where users create projects, upload data, and chat with Claude to run analysis and generate plots/reports/slides.

## Stack

- **Frontend**: React 19 + TypeScript + Vite (port 5173) + Tailwind CSS 4 + Zustand + Radix UI
- **Backend**: Express 5 (port 3001) + WebSocket (ws) + Claude Code Agent SDK
- **AI**: `@anthropic-ai/claude-code` SDK wraps the user's Claude Max subscription. The agent bridge streams messages to the frontend via WebSocket.

## Layout

```
casi-app/
├── server/                    Express backend
│   ├── index.ts               Server entry, WebSocket setup
│   ├── agent-bridge.ts        Claude Code SDK integration (project-scoped sessions)
│   ├── routes/
│   │   ├── agent.ts           POST /api/agent/send, /abort
│   │   └── projects.ts        Project CRUD, file upload, report, sidecar
│   ├── services/
│   │   ├── daemon-client.ts      HTTP client to Python daemon (port 3002)
│   │   └── watchers.ts           PlotWatcher + ReportWatcher (fs.watch)
│   └── lib/
│       ├── paths.ts           CASI_ROOT resolution
│       └── broadcast.ts       Debounced WebSocket broadcaster
│
├── src/renderer/              React frontend
│   ├── pages/
│   │   ├── ProjectsPage.tsx   Project list, create, rename, delete
│   │   └── WorkspacePage.tsx  Active project workspace
│   ├── components/
│   │   ├── layout/WorkspaceLayout.tsx   3-panel: chat | workspace tabs | status bar
│   │   ├── chat/              ChatPanel, ChatMessage, ChatInput
│   │   ├── workspace/         WorkspaceTabs, FileManager, ProjectSettings, SlidesViewer
│   │   ├── visualization/     PlotViewer, SidecarCard
│   │   └── ReportViewer.tsx   Markdown report with section approval
│   ├── stores/                Zustand state (project, chat, workspace, files)
│   ├── hooks/                 useWebSocket, useAgentMessages
│   └── lib/                   api.ts, message-parser.ts, utils.ts
│
├── package.json
├── vite.config.ts             Proxy /api + /ws + /plots to :3001
└── tsconfig.json
```

## Data flow

1. User types in ChatInput → `POST /api/agent/send { prompt, projectName }`
2. Express calls agent-bridge → Claude Code SDK `query()` with project-scoped session
3. Agent SDK streams messages → `broadcast()` → WebSocket → all frontend clients
4. Frontend `useAgentMessages` hook processes messages → Zustand stores → React re-renders
5. PlotWatcher detects new plots in `output/` → broadcasts `plot:new` → PlotViewer updates
6. ReportWatcher detects `report.md` changes → broadcasts `report:update`

## Key patterns

- **Agent bridge** uses Claude Code SDK's `resume` option with persisted sessionId for conversation continuity
- **WebSocket batching**: rapid events within 50ms are combined into `{ type: 'batch', data: [...] }`
- **Message parsing**: extracts tool_use blocks, plot paths (regex), and markdown content from SDK messages
- **Virtualized chat**: `@tanstack/react-virtual` for large conversation histories

## Pending work

- Conversation persistence (JSONL logging + hydration on project open)
- System prompt builder (inject project memory + data profiles + available ops)
- Per-project memory.yaml read/write service
- Suggestions UI (recommended next analysis steps)
- Data preview in FileManager (tabular grid, HDF5 tree)
- SlidesViewer (PowerPoint generation from report + plots)
- ProjectSettings (config editing, custom ops management)

## Dev commands

```bash
npm run dev        # starts Express (:3001) + Vite (:5173) concurrently
npm run server     # Express only (tsx watch)
npm run client     # Vite only
npm test           # vitest
```

## See also
- [../CLAUDE.md](../CLAUDE.md) — repo root nav
- [../src/casi/CLAUDE.md](../src/casi/CLAUDE.md) — Python engine
