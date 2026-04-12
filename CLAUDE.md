# CASI — Agent navigation

CASI is a **local AI-powered data analysis webapp**. Users create projects, upload datasets (neuroscience or general tabular/time-series), and chat with Claude (via Claude Code SDK + Max subscription) to run analysis, make plots, generate reports, and build slide decks. Think of it as a persistent, project-scoped research partner that remembers context across sessions.

## Architecture overview

```
casi-app/          React 19 + Express webapp (port 3001)
  server/            Express backend + Claude Code Agent SDK bridge + WebSocket
  src/renderer/      React frontend (Vite, Tailwind 4, Zustand, Radix UI)
src/casi/          Python package — ops engine, DSL, config, projects, sessions
  daemon/            FastAPI backend (port 3002) — runs ops, profiles data
configs/           Global YAML configs (paths, ops defaults, globals)
projects/          Per-project workspaces (gitignored except TEMPLATE)
tests/             Pytest suite (synthetic data, headless)
docs/              Architecture, operations math, project contract
```

## First-read rules (token discipline)

- **Never load more than 2 `CLAUDE.md` files in total.** These files are nav gateways, not reading material.
- **Never load the full `claude_history.md` of a project.** Load only `## Goals` and `## Next Steps` on startup.
- **Always check for an active project** via `cat .casi/active_project` before doing anything else.

## Where to go

| Task | Read this |
|---|---|
| Webapp frontend or backend | [casi-app/CLAUDE.md](casi-app/CLAUDE.md) → React + Express + Agent SDK |
| Python ops engine / DSL / pipeline | [src/casi/CLAUDE.md](src/casi/CLAUDE.md) → package layout + op registry |
| Project workspaces | [projects/CLAUDE.md](projects/CLAUDE.md) → workspace contract |
| Operation math reference | [docs/operations.md](docs/operations.md) — authoritative op catalog |
| System architecture | [docs/architecture.md](docs/architecture.md) |
| Configuration (YAML) | [configs/CLAUDE.md](configs/CLAUDE.md) → yaml schemas |
| Tests | [tests/CLAUDE.md](tests/CLAUDE.md) |

## Key concepts

- **Projects** are self-contained workspaces under `projects/<name>/` with uploaded data, conversations, memory, plots, reports, and caches.
- **The webapp** (`casi-app/`) is the primary interface. The Express server wraps the Claude Code SDK to give the AI access to the filesystem, Python engine, and project context.
- **Operations** are hardcoded signal-processing/analysis functions (17 currently). The AI can also create custom per-project ops on user request.
- **Per-project memory** (`memory.yaml`) stores learned facts, data profiles, and analysis state. This context is injected into every AI prompt so Claude understands the project across sessions.
- **Conversations** persist as JSONL in each project's `conversations/` directory.

## The CLI surface (still works)

The `casi` CLI remains functional for direct use:

```bash
casi config show
casi ops list
casi project new my-analysis --open
casi run "mea_trace(861).butter_bandpass.spectrogram"
```

## After editing Python files

- Run `uv run pytest -x -q` before reporting any code change as complete.
- Run `uv run ruff check --fix src tests && uv run ruff format src tests` to fix lint/format issues.

## After editing webapp files

- Run `cd casi-app && npm run dev` to start the dev server.
- Test in browser at http://localhost:5173.

## See also
- [README.md](README.md) — user-facing quickstart
- [docs/agent-guide.md](docs/agent-guide.md) — agent workflow reference
- [docs/projects.md](docs/projects.md) — full project contract
