# CASI Desktop App — Complete Build Plan

## What This Is

You are building a desktop app for CASI (Calcium-Assisted Spike Identity), a Python-based neuroscience data analysis pipeline. The app wraps the existing `casi` CLI tool in an Electron shell with a chat interface powered by the Claude Code Agent SDK, inline plot viewing, and project management — all running locally on Windows.

## Project Location

- **This app**: `d:/Projects/casi-app/`
- **CASI backend** (Python, DO NOT modify): `d:/Projects/CASI/`
- **Platform**: Windows 11, Node.js 22, npm 10

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                 RENDERER (React)                     │
│  Sidebar │ Chat Panel │ Plot Viewer │ Status Bar     │
└──────────────────────┬──────────────────────────────┘
                       │ IPC (contextBridge)
┌──────────────────────┴──────────────────────────────┐
│                 MAIN PROCESS (Node.js)               │
│  AgentBridge (Agent SDK)  │  CliBridge (spawn casi)  │
│  PlotWatcher (fs.watch)   │                          │
└──────────────────────┬──────────────────────────────┘
                       │ child_process.spawn
┌──────────────────────┴──────────────────────────────┐
│              CASI Python Backend (unchanged)          │
│  Called via: uv run casi <command>                    │
│  CWD: d:/Projects/CASI                               │
└─────────────────────────────────────────────────────┘
```

- **Agent SDK** (`@anthropic-ai/claude-code`) is the primary interaction layer — user types natural language, agent translates to CASI CLI commands, streams responses back
- **Direct CLI calls** (`uv run casi project list`, etc.) bypass the agent for instant UI population (sidebar, config)
- **Zero changes to CASI Python code** — the app only calls the `casi` CLI
- Auth reuses existing Claude Code credentials from `~/.claude/`

## Tech Stack

- **Electron** via `electron-vite` — desktop framework
- **React 19 + TypeScript** — renderer UI
- **Tailwind CSS 4** (via `@tailwindcss/vite`) — styling
- **Zustand** — state management
- **react-markdown + remark-gfm** — render agent markdown responses
- **react-resizable-panels** — split panel layout
- **react-zoom-pan-pinch** — plot zoom/pan

## UI Layout

```
+-------+---------------------------+---------------------------+
|       |                           |                           |
| (A)   |       (B) Chat            |    (C) Plot Viewer        |
| Side  |                           |                           |
| bar   |  Agent messages stream    |  Full-size plot with      |
|       |  with markdown. Tool use  |  zoom/pan. Sidecar        |
| Proj  |  shown as collapsible     |  metadata card below.     |
| list  |  cards. Plot thumbnails   |                           |
|       |  appear inline.           |                           |
|       |                           |                           |
|       |  [Type message here...]   |  [thumbnail strip]        |
|       |                           |                           |
+-------+---------------------------+---------------------------+
| Status: project=kinetics | agent=idle | tokens: 12.4k         |
+---------------------------------------------------------------+
```

## What Already Exists

The following files are already written and working. Read them to understand the patterns, then complete the missing pieces.

### Config files (DONE)
- `package.json` — all dependencies declared
- `electron-vite.config.ts` — main/preload/renderer build config
- `tsconfig.json`, `tsconfig.node.json`, `tsconfig.web.json`

### Main process (DONE)
- `src/main/index.ts` — app entry, window creation, IPC setup
- `src/main/agent-bridge.ts` — wraps Agent SDK `query()`, streams messages to renderer
- `src/main/cli-bridge.ts` — spawns `uv run casi <args>`, returns stdout
- `src/main/ipc-handlers.ts` — all ipcMain.handle registrations for agent + CLI + file access
- `src/main/plot-watcher.ts` — fs.watch on project output dirs, emits PLOT_NEW events

### Preload (DONE)
- `src/preload/index.ts` — contextBridge exposing `window.casi` API

### Shared (DONE)
- `src/shared/types.ts` — ProjectInfo, PlotInfo, PlotSidecar, ChatMessage, ToolUseInfo, IPC channel constants

### Renderer - entry (DONE)
- `src/renderer/index.html`
- `src/renderer/main.tsx`
- `src/renderer/styles/globals.css` — dark theme CSS variables, scrollbar styling
- `src/renderer/env.d.ts` — `Window.casi` type declaration

### Renderer - state & hooks (DONE)
- `src/renderer/stores/casi-store.ts` — Zustand store (projects, messages, agentStatus, plots)
- `src/renderer/hooks/useAgentMessages.ts` — listens to agent messages, updates store
- `src/renderer/hooks/usePlotWatcher.ts` — listens for new plots from PlotWatcher
- `src/renderer/lib/message-parser.ts` — processes Agent SDK messages into ChatMessage format, extracts plot paths

### Renderer - components (DONE)
- `src/renderer/App.tsx` — top-level layout with PanelGroup (sidebar | chat | plot viewer) + StatusBar
- `src/renderer/components/sidebar/Sidebar.tsx` — project list, create project form, click to switch
- `src/renderer/components/chat/ChatPanel.tsx` — message list, thinking/running indicators, example prompts
- `src/renderer/components/chat/ChatMessage.tsx` — renders user/assistant/system messages, ToolUseCard, PlotThumbnail
- `src/renderer/components/chat/ChatInput.tsx` — textarea with Ctrl+Enter send, abort button

### Renderer - components (MISSING — you must create these)
- `src/renderer/components/visualization/PlotViewer.tsx`
- `src/renderer/components/StatusBar.tsx`

## What You Need To Do

### Step 1: Create the two missing components

**`src/renderer/components/visualization/PlotViewer.tsx`**
- Shows the `currentPlot` from the Zustand store as a full-size image
- Uses `react-zoom-pan-pinch` for zoom/pan functionality
- Displays the sidecar metadata below the image (DSL string, window, ops with params)
- Has an "Open in Explorer" button calling `window.casi.openInExplorer(path)`
- Shows a thumbnail strip at the bottom from `sessionPlots` in the store
- Clicking a thumbnail sets it as `currentPlot`
- When no plot is selected, show a placeholder message
- Plot images load via `file:///` protocol (webSecurity is disabled in main)

**`src/renderer/components/StatusBar.tsx`**
- Shows: active project name, agent status (idle/thinking/running), session info
- Uses `useCasiStore` to read `activeProject` and `agentStatus`
- Status indicator: green dot for idle, yellow pulsing for thinking, blue spinner for tool_use
- Thin bar at the bottom of the window

### Step 2: Install dependencies and verify the app launches

```bash
cd d:/Projects/casi-app
npm install
npm run dev
```

If there are import errors or missing dependencies, fix them. Common issues:
- `@electron-toolkit/utils` is imported in `src/main/index.ts` — either install it (`npm install @electron-toolkit/utils`) or replace `is.dev` with `!app.isPackaged`
- The Agent SDK (`@anthropic-ai/claude-code`) is an ESM module — the dynamic import in `agent-bridge.ts` handles this
- If `electron-vite` has trouble with the config, check that the paths in `electron-vite.config.ts` resolve correctly

### Step 3: Test the end-to-end flow

1. App should launch with dark theme, three-panel layout
2. Sidebar should show CASI projects (loaded via `uv run casi project list --json`)
3. Typing a message and pressing Ctrl+Enter should send it to the Agent SDK
4. Agent responses should stream into the chat with markdown rendering
5. Tool use (Bash commands) should appear as collapsible cards
6. When a plot is generated, it should appear as a thumbnail in chat and auto-load in the PlotViewer
7. Clicking a project in the sidebar should switch the active project

### Step 4: Fix any issues

- If the `casi` CLI isn't found, check that `uv` is on PATH
- If plots don't appear, check the PlotWatcher output directory path
- If the Agent SDK fails to authenticate, the user may need to set `ANTHROPIC_API_KEY` as an env var or ensure Claude Code is installed and authenticated

## Key Patterns in the Existing Code

### IPC Pattern
All IPC channels are defined in `src/shared/types.ts` as `IPC` constants. Main process registers handlers in `ipc-handlers.ts`. Preload exposes them via `contextBridge` as `window.casi.*`. Renderer calls them directly.

### Agent Message Flow
1. User types → `window.casi.sendMessage(text)` → IPC → `AgentBridge.sendMessage()`
2. Agent SDK `query()` yields messages → each forwarded via `win.webContents.send(IPC.AGENT_MESSAGE, msg)`
3. Renderer's `useAgentMessages` hook processes them through `message-parser.ts` → updates Zustand store
4. `ChatPanel` re-renders with new messages

### Plot Detection Flow
Two mechanisms:
1. **Message parsing**: `extractPlotPaths()` in `message-parser.ts` regex-matches `.png/.pdf` paths from agent output
2. **PlotWatcher**: `fs.watch` on the project output directory detects new files independently

### Store Access
All components use `useCasiStore()` from Zustand. Key selectors:
- `projects`, `activeProject` — sidebar
- `messages`, `agentStatus` — chat
- `currentPlot`, `sessionPlots` — plot viewer

### File Protocol for Images
Plot images are loaded via `file:///` URLs. The path normalization is in `ChatMessage.tsx`'s `PlotThumbnail`:
```tsx
const normalizedPath = path.replace(/\\/g, '/')
const fileUrl = `file:///${normalizedPath.replace(/^\//, '')}`
```

## CASI CLI Reference (what the app calls)

The app calls the CASI CLI via `uv run casi <command>` from `d:/Projects/CASI`. Key commands:

```
casi project list [--json]     — list all projects
casi project open <name>       — activate a project
casi project new <name> --open — create and activate
casi project info [name]       — show project details
casi config show [--json]      — display configuration
casi config edit <file> <key> <value> — edit a config value
casi ops list [--json]         — list all 17 operations
casi session list [--json]     — list sessions
casi run "<dsl>"               — execute a pipeline (e.g., "mea_trace(861).spectrogram")
```

## File Tree

```
casi-app/
├── package.json                          ✅ exists
├── electron-vite.config.ts               ✅ exists
├── tsconfig.json                         ✅ exists
├── tsconfig.node.json                    ✅ exists
├── tsconfig.web.json                     ✅ exists
├── src/
│   ├── main/
│   │   ├── index.ts                      ✅ exists
│   │   ├── agent-bridge.ts               ✅ exists
│   │   ├── cli-bridge.ts                 ✅ exists
│   │   ├── ipc-handlers.ts               ✅ exists
│   │   └── plot-watcher.ts               ✅ exists
│   ├── preload/
│   │   └── index.ts                      ✅ exists
│   ├── renderer/
│   │   ├── index.html                    ✅ exists
│   │   ├── main.tsx                      ✅ exists
│   │   ├── App.tsx                       ✅ exists
│   │   ├── env.d.ts                      ✅ exists
│   │   ├── styles/
│   │   │   └── globals.css               ✅ exists
│   │   ├── stores/
│   │   │   └── casi-store.ts             ✅ exists
│   │   ├── hooks/
│   │   │   ├── useAgentMessages.ts       ✅ exists
│   │   │   └── usePlotWatcher.ts         ✅ exists
│   │   ├── lib/
│   │   │   └── message-parser.ts         ✅ exists
│   │   └── components/
│   │       ├── chat/
│   │       │   ├── ChatPanel.tsx          ✅ exists
│   │       │   ├── ChatMessage.tsx        ✅ exists
│   │       │   └── ChatInput.tsx          ✅ exists
│   │       ├── sidebar/
│   │       │   └── Sidebar.tsx            ✅ exists
│   │       ├── visualization/
│   │       │   └── PlotViewer.tsx         ❌ MISSING — create this
│   │       └── StatusBar.tsx              ❌ MISSING — create this
│   └── shared/
│       └── types.ts                      ✅ exists
```
