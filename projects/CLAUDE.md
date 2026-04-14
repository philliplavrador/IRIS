# projects/ — workspace navigation

Each subdirectory under `projects/` is a durable, self-contained analysis workspace. Only `TEMPLATE/`, `README.md`, `CLAUDE.md`, and `.gitignore` are committed — every real project is gitignored.

## Layout

```
projects/
├── TEMPLATE/               (committed skeleton, copied on project creation)
│   ├── CLAUDE.md           (per-project navigation stub)
│   ├── claude_config.yaml  (name, description, autonomy/pushback/memory dials, overrides)
│   ├── report.md           (living writeup)
│   ├── conversations/      (L0 — JSONL chat history per session)
│   ├── digests/            (L2 — auto-drafted + finalized session digests)
│   ├── views/              (regenerated human-readable views of L2/L3)
│   ├── input_data/         (user-uploaded datasets)
│   ├── custom_ops/         (project-scoped Python operations)
│   ├── claude_references/  (agent-gathered refs)
│   ├── user_references/    (user-placed refs)
│   └── output/             (sessions + plots)
└── <your-project>/         (gitignored; created from TEMPLATE)
    ├── ledger.sqlite       (L1 — event ledger: ops_runs, plots, cache)
    ├── knowledge.sqlite    (L3 — curated goals, decisions, facts, annotations)
    └── ... plus .cache/ at the same level as output/
```

## Memory model

Memory is split across five layers (see `docs/iris-memory.md`):
- **L0** conversation JSONL under `conversations/`
- **L1** event ledger in `ledger.sqlite`
- **L2** session digests under `digests/` (draft + final)
- **L3** curated knowledge in `knowledge.sqlite`
- **L4** semantic index (optional `memory.vec`)

`views/history.md` and `views/analysis_log.md` are **regenerated** from L2/L3 for human reading — never edited by hand and never used as source of truth.

## How agents should interact with a project

1. On startup, read `.iris/active_project` to get the project name.
2. Read `claude_config.yaml` (always fine to load fully).
3. Trust the pinned memory slice the daemon injects via `/api/memory/build_slice`. Do not grep the SQLite files directly — use `recall`, `get`, `read_ledger`, `read_conversation`.
4. Propose durable writes via `propose_*` endpoints; they are committed by the curation ritual at session end (see `docs/iris-behavior.md` §7).

## Rules

- **Never** commit project contents (other than TEMPLATE). The .gitignore handles this.
- **Never** put cache files under `output/` — caches live in `.cache/`.
- **Never** read memory stores by file path — go through the memory tool endpoints.

## See also
- [../CLAUDE.md](../CLAUDE.md) — repo root nav
- [../docs/iris-memory.md](../docs/iris-memory.md) — memory architecture
- [../docs/iris-behavior.md](../docs/iris-behavior.md) — behavior blueprint
- [../src/iris/projects/__init__.py](../src/iris/projects/__init__.py) — lifecycle API
