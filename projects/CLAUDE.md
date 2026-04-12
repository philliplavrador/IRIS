# projects/ — workspace navigation

Each subdirectory under `projects/` is a durable, self-contained analysis workspace. Only `TEMPLATE/`, `README.md`, `CLAUDE.md`, and `.gitignore` are committed — every real project is gitignored.

## Layout

```
projects/
├── TEMPLATE/               (committed skeleton, copied on project creation)
│   ├── CLAUDE.md           (per-project navigation stub)
│   ├── claude_config.yaml  (name, description, overrides)
│   ├── claude_history.md   (Goals / Open Questions / Decisions / Ops / Plots / Refs / Next Steps)
│   ├── memory.yaml         (learned facts, data profiles, analysis state — AI-managed)
│   ├── report.md           (living writeup)
│   ├── conversations/      (JSONL chat history + session.json for Claude Code SDK resume)
│   ├── input_data/         (user-uploaded datasets)
│   ├── custom_ops/         (project-scoped Python operations)
│   ├── claude_references/  (agent-gathered refs)
│   ├── user_references/    (user-placed refs)
│   └── output/             (sessions + plots)
└── <your-project>/         (gitignored; created from TEMPLATE)
    └── ... plus .cache/ at the same level as output/
```

## Key files in each project

- **`memory.yaml`** — Per-project persistent memory. Stores data profiles, learned facts (data quality, user preferences, analysis decisions), and analysis state (completed analyses, pending questions). The AI reads this on every prompt and writes to it when it learns something new. This is how context survives across sessions.
- **`conversations/history.jsonl`** — Full chat history as JSONL (one message per line). Loaded on project open to hydrate the chat UI.
- **`conversations/session.json`** — Claude Code SDK sessionId for conversation resume.
- **`claude_config.yaml`** — Project name, description, and config overrides (paths, ops, globals).
- **`claude_history.md`** — Structured chronological notes (Goals, Decisions, Next Steps, etc.).
- **`report.md`** — Living analysis report the AI compiles from findings.

## How agents should interact with a project

1. On startup, read `.casi/active_project` to get the project name.
2. Read `claude_config.yaml` (always fine to load fully).
3. Read **only** the `## Goals` and `## Next Steps` sections of `claude_history.md`.
4. The system prompt builder injects `memory.yaml` content automatically — no need to read it manually.
5. After meaningful exchanges, append terse dated bullets to `claude_history.md`.

## Rules

- **Never** commit project contents (other than TEMPLATE). The .gitignore handles this.
- **Never** put cache files under `output/` — caches live in `.cache/`.
- **Never** invent new top-level sections in `claude_history.md`.

## See also
- [../CLAUDE.md](../CLAUDE.md) — repo root nav
- [../docs/projects.md](../docs/projects.md) — full project contract
- [../src/casi/projects.py](../src/casi/projects.py) — lifecycle API
