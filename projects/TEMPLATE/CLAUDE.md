# Project navigation

This is a IRIS project workspace. The webapp and analysis agent use this project to scope all work — uploaded data, conversations, memory, plots, and reports live here.

## Read on startup (in order)
1. `claude_config.yaml` — project name, description, behavior dials, per-project overrides
2. Pinned memory slice — assembled by the daemon (`/api/memory/build_slice`) from L2 last digest + L3 active goals/decisions/facts + confirmed profile annotations. Injected into the system prompt automatically; do NOT read memory files directly.

## Read on demand (via tools, never by auto-load)
- `conversations/<session>.jsonl` — L0 raw turns; access via `read_conversation`
- `ledger.sqlite` — L1 event ledger; access via `read_ledger` / `recall`
- `knowledge.sqlite` — L3 curated knowledge; access via `recall` or knowledge list endpoints
- `digests/<session>.json` — L2 session digests; access via `recall` or `get`
- `views/history.md`, `views/analysis_log.md` — regenerated human-readable views of the SQLite stores
- `claude_references/INDEX.md` if present — cached research
- `user_references/` — user-placed references
- `report.md` — the living analysis report
- `output/` — existing sessions and plot sidecars
- `custom_ops/` — project-scoped Python operations
- `input_data/` — uploaded datasets

## Never load automatically
- `.cache/` contents
- Any SQLite / JSONL memory file (use the tool endpoints)

## See also
- [../../CLAUDE.md](../../CLAUDE.md) — repo root navigation
- [../../docs/iris-memory.md](../../docs/iris-memory.md) — memory architecture
- [../../docs/iris-behavior.md](../../docs/iris-behavior.md) — behavior blueprint
