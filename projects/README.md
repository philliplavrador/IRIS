# IRIS Projects

A **project** is a durable analysis workspace. Each project bundles:

- `claude_config.yaml` — per-project name, description, and config overrides
- `claude_history.md` — structured memory of goals, decisions, operations, references, and next steps (the "partner continuity" file)
- `claude_references/` — research the agent has gathered (web fetches, summaries, citations)
- `user_references/` — references you drop in manually (PDFs, notes, code)
- `output/` — plots generated inside this project (sessions live here)
- `.cache/` — project-scoped pipeline cache (sibling of `output/`)
- `report.md` — living analysis writeup
- `CLAUDE.md` — per-project navigation hint for the analysis agent

## Lifecycle

```bash
iris project new my-analysis --description "jGCaMP8m kinetics study"
iris project open my-analysis
iris run "mea_trace(861).butter_bandpass.spectrogram"    # writes to projects/my-analysis/output/
iris project list
iris project close
```

The active project is tracked in `.iris/active_project` at the repo root (untracked).

## Git

Only `TEMPLATE/`, this `README.md`, and `.gitignore` are committed. Everything else under `projects/` is gitignored so analysis notes, references, and cached plots stay local to your checkout.

## Template

New projects are created by copying `TEMPLATE/`. To change the default skeleton, edit `TEMPLATE/` directly.

## See also

- [../CLAUDE.md](../CLAUDE.md) — repo-root navigation
- [../docs/projects.md](../docs/projects.md) — full project contract
- [../src/iris/projects.py](../src/iris/projects.py) — project lifecycle API
