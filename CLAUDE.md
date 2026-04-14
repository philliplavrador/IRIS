# IRIS — Agent navigation

IRIS is a **local AI-powered data analysis webapp**. Users create projects, upload datasets (neuroscience or general tabular/time-series), and chat with Claude (via Claude Code SDK + Max subscription) to run analysis, make plots, generate reports, and build slide decks. Think of it as a persistent, project-scoped research partner that remembers context across sessions.

## Memory System Migration (active)

The memory layer is being rewritten end-to-end. The authoritative design is
[`IRIS Memory Restructure.md`](IRIS%20Memory%20Restructure.md); the ordered
task ledger is [`REVAMP.md`](REVAMP.md). If you are implementing anything
under `src/iris/projects/`, `src/iris/daemon/routes/memory.py`, or the
memory-facing parts of the webapp, **read REVAMP.md first** — it tells you
which task is next, which files to touch, and which tests must pass.

Phase 0 (nuke legacy memory modules, rebuild TEMPLATE, collapse YAML into a
single `config.toml`) is complete. Phase 1+ rebuilds `iris.sqlite` per spec
§7 and scaffolds lifecycle / events / messages / memory entries / artifacts
/ datasets / runs / operations / retrieval.

## Architecture overview

```
iris-app/          React 19 + Express webapp (port 4001)
  server/            Express backend + Claude Code Agent SDK bridge + WebSocket
  src/renderer/      React frontend (Vite, Tailwind 4, Zustand, Radix UI)
src/iris/          Python package — ops engine, DSL, config, projects, daemon
  daemon/            FastAPI backend (port 4002) — ops, profiles, memory HTTP
  engine/            Analysis engine (stable; not being restructured)
  projects/          Project workspaces + memory layer (REVAMP rewrite zone)
configs/           Single config.toml (replaces legacy YAML quartet)
projects/          Per-project workspaces (gitignored except TEMPLATE)
tests/             Pytest suite (synthetic data, headless)
docs/              Architecture, operations math, project contract
```

## First-read rules (token discipline)

- **Never load more than 2 `CLAUDE.md` files in total.** These files are nav gateways, not reading material.
- **Always check for an active project** via `cat .iris/active_project` before doing anything else.
- **Never load `IRIS Memory Restructure.md` in full** — jump to the § the REVAMP task cites.

## Where to go

| Task | Read this |
|---|---|
| Pick the next REVAMP task | [REVAMP.md](REVAMP.md) |
| Memory-system design spec | [IRIS Memory Restructure.md](IRIS%20Memory%20Restructure.md) |
| Webapp frontend or backend | [iris-app/CLAUDE.md](iris-app/CLAUDE.md) → React + Express + Agent SDK |
| Python package map | [src/iris/CLAUDE.md](src/iris/CLAUDE.md) |
| Memory module map (detailed) | [src/iris/projects/CLAUDE.md](src/iris/projects/CLAUDE.md) |
| Daemon (HTTP shell) | [src/iris/daemon/CLAUDE.md](src/iris/daemon/CLAUDE.md) |
| Daemon routes inventory | [src/iris/daemon/routes/CLAUDE.md](src/iris/daemon/routes/CLAUDE.md) |
| Express proxy + agent bridge | [iris-app/server/CLAUDE.md](iris-app/server/CLAUDE.md) |
| Frontend module map | [iris-app/src/renderer/CLAUDE.md](iris-app/src/renderer/CLAUDE.md) |
| Analysis engine (stable) | [src/iris/engine/CLAUDE.md](src/iris/engine/CLAUDE.md) |
| Project workspace contract | [projects/CLAUDE.md](projects/CLAUDE.md) |
| TEMPLATE layout | [projects/TEMPLATE/CLAUDE.md](projects/TEMPLATE/CLAUDE.md) |
| Operation math reference | [docs/operations.md](docs/operations.md) |
| System architecture | [docs/architecture.md](docs/architecture.md) |
| Configuration (TOML) | [configs/CLAUDE.md](configs/CLAUDE.md) |
| Tests | [tests/CLAUDE.md](tests/CLAUDE.md) |

## Key concepts (post-REVAMP terms)

- **Project**: self-contained workspace under `projects/<name>/` with a
  `config.toml`, runtime-created `iris.sqlite`, human-readable `memory/*.md`
  files, `datasets/`, `artifacts/`, `ops/`, and `indexes/`.
- **Three storage substrates** (spec §5.1): SQLite (programmatic truth),
  content-addressed filesystem (artifacts + datasets), curated Markdown
  (human view, regenerated from SQLite).
- **Memory entries**: unified L3 store — findings, decisions, caveats, open
  questions, preferences — with propose → commit workflow.
- **Operations**: 17 hardcoded signal-processing ops plus a Phase 8 catalog
  for project-scoped versioned ops.
- **Runs**: every pipeline execution writes a row to `runs` for lineage.

## The CLI surface (still works)

```bash
iris config show
iris ops list
iris project new my-analysis --open
iris run "mea_trace(861).butter_bandpass.spectrogram"
```

## After editing Python files

- `uv run pytest -x -q` before reporting any change as complete.
- `uv run ruff check --fix src tests && uv run ruff format src tests`.
- Tasks inside REVAMP have their own validation gate — run the full
  [Standard validation gate](REVAMP.md#standard-validation-gate-every-task).

## After editing webapp files

- `cd iris-app && npm run dev` to start the dev server.
- Test in browser at http://localhost:4173.

## See also
- [README.md](README.md) — user-facing quickstart
- [docs/projects.md](docs/projects.md) — full project contract
