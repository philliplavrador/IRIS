# Project navigation

This is a CASI project workspace. The webapp and analysis agent use this project to scope all work — uploaded data, conversations, memory, plots, and reports live here.

## Read on startup (in order)
1. `claude_config.yaml` — project name, description, and per-project overrides
2. `claude_history.md` — load the `## Goals` and `## Next Steps` sections only (not the whole file)
3. `memory.yaml` — data profiles, learned facts, analysis state (injected into prompts automatically by the system prompt builder)

## Read on demand
- `conversations/history.jsonl` — full chat history (loaded by webapp on project open)
- `claude_references/INDEX.md` if present — cached research
- `user_references/` — user-placed references (PDFs, notes)
- `report.md` — the living analysis report
- `output/` — existing sessions and plot sidecars
- `custom_ops/` — project-scoped Python operations
- `input_data/` — uploaded datasets

## Never load automatically
- The full `claude_history.md`
- `.cache/` contents

## See also
- [../../CLAUDE.md](../../CLAUDE.md) — repo root navigation
- [../../docs/projects.md](../../docs/projects.md) — project contract
