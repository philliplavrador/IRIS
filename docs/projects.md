# IRIS Project Workspaces

A **project** is a self-contained, portable analysis workspace. Every project bundles its own config, memory, datasets, artifacts, operation catalog, and runtime database under a single directory. Copy the directory to back up, move, or share the project — no cross-project dependencies exist.

Projects live under `projects/<project-id>/`. Only the committed `TEMPLATE/` skeleton, `projects/README.md`, `projects/CLAUDE.md`, and `projects/.gitignore` are tracked in git. Every real project is gitignored.

The authoritative design reference is [`IRIS Memory Restructure.md` §6](../IRIS%20Memory%20Restructure.md) (Filesystem Layout) and §7 (Database Schema). This document is the human-facing contract: what exists on disk, what the lifecycle commands do, and how to read the truth.

---

## Layout

```
projects/
├── .gitignore                        (committed — ignores everything except TEMPLATE + scaffolding)
├── README.md                         (committed — user-facing intro)
├── CLAUDE.md                         (committed — agent nav gateway)
├── TEMPLATE/                         (committed — copied by `iris project new`)
│   ├── CLAUDE.md
│   ├── config.toml                   (seed config; name/description filled in on create)
│   ├── memory/
│   │   ├── PROJECT.md                (project core memory; regenerated from SQLite)
│   │   ├── DECISIONS.md              (decision & conclusion register; regenerated)
│   │   ├── OPEN_QUESTIONS.md         (open questions register; regenerated)
│   │   └── DATASETS/                 (one dataset card per registered dataset)
│   ├── datasets/
│   │   ├── raw/                      (original uploads, content-addressed by sha256)
│   │   └── derived/                  (transformed / profiled versions)
│   ├── artifacts/                    (content-addressed outputs: plots, reports, caches)
│   ├── ops/                          (project-scoped operations, versioned by semver)
│   └── indexes/                      (vector / FTS auxiliary indexes — V2+)
└── <project-id>/                     (gitignored — created from TEMPLATE)
    ├── config.toml
    ├── iris.sqlite                   (runtime; WAL-mode; programmatic truth)
    ├── memory/
    │   ├── PROJECT.md
    │   ├── DECISIONS.md
    │   ├── OPEN_QUESTIONS.md
    │   └── DATASETS/
    │       └── <dataset-id>.md
    ├── datasets/
    │   ├── raw/<dataset-id>/<sha256>.<ext>
    │   └── derived/<dataset-id>/<sha256>.<ext>
    ├── artifacts/<sha256>/…
    ├── ops/<op-name>/v<semver>/
    │   ├── op.py
    │   ├── schema.json
    │   ├── tests/
    │   └── README.md
    └── indexes/embeddings.<format>   (optional, V2+)
```

`iris.sqlite` does **not** live in `TEMPLATE/`. It is created at project-open time by `db.connect(project_dir)` when the schema is applied. TEMPLATE ships only the committed scaffolding.

The active project is tracked in `.iris/active_project` at the repo root (gitignored; one line holding the project id). No project is active by default.

---

## The three storage substrates (per project)

Every project mixes three substrates, each with a distinct role. See spec §5.1.

| Substrate | Location | Role | Mutability |
|---|---|---|---|
| **SQLite** | `iris.sqlite` | Programmatic truth — events, messages, memory entries, datasets, runs, ops, artifacts metadata | Append-dominant; events are immutable |
| **Content-addressed FS** | `datasets/`, `artifacts/` | Heavy bytes — original uploads, derived data, plots, reports, cached outputs | Immutable; keyed by `sha256` |
| **Curated Markdown** | `memory/*.md` | Human view — rendered from SQLite `memory_entries`, `decisions`, `open_questions`, `datasets` | Regenerated; **never edited by hand** |

Rule of thumb: **SQLite is canonical**. Markdown is a render. Files in `datasets/` and `artifacts/` are keyed by hash — referenced from SQLite, never orphaned.

---

## Lifecycle

```bash
# Create + activate a new project (copies TEMPLATE, seeds config.toml, creates iris.sqlite)
iris project new kinetics-study --description "jGCaMP8m decay analysis" --open

# Switch the active project
iris project open other-study

# List all projects (active one marked)
iris project list

# Inspect one project's metadata + stats
iris project info kinetics-study

# Close the active project (no project active until next `open`)
iris project close

# Delete a project (removes the directory + drops it from the list)
iris project delete abandoned-study
```

Under the hood (`src/iris/projects/`):

- **create** — copy `TEMPLATE/` to `projects/<id>/`, fill `config.toml`, call `db.init(project_dir)` to apply `schema.sql` and write an initial `projects` row.
- **open** — validate the directory exists, run pending migrations against `iris.sqlite`, update `.iris/active_project`.
- **list** — enumerate `projects/*/` (excluding `TEMPLATE/`), read each `config.toml` header.
- **delete** — remove the directory; the active pointer is cleared if it pointed there.
- **close** — clear `.iris/active_project`.

`iris.sqlite` is opened lazily by daemon routes and tools; agents never open it directly — they call the memory HTTP API.

---

## Configuration

Two layers of config, both TOML.

### Global (`configs/config.toml`)

Repo-wide settings: default model, daemon ports, logging, retrieval knobs, feature flags. Owned by the operator; same for every project. See [configs/CLAUDE.md](../configs/CLAUDE.md).

### Per-project (`projects/<id>/config.toml`)

Project identity + per-project overrides:

```toml
[project]
id          = "kinetics-study"
name        = "Kinetics study"
description = "jGCaMP8m decay analysis across temperatures"
created_at  = "2026-04-10T18:22:00Z"

[memory]
# autonomy / pushback / retrieval dials — overrides the global defaults
autonomy_level   = "moderate"
pushback_level   = "high"
retrieval_k      = 12

[model]
# optional; falls back to global
provider = "anthropic"
name     = "claude-sonnet-4-20250514"
```

Resolution order (lowest → highest precedence): hard-coded defaults → `configs/config.toml` → `projects/<id>/config.toml` → explicit CLI / API overrides.

---

## What's committed vs gitignored

**Committed** (tracked in git):
- `projects/README.md`, `projects/CLAUDE.md`, `projects/.gitignore`
- The entire `projects/TEMPLATE/` directory (scaffolding only — no `iris.sqlite`, no data)

**Gitignored** (everything real):
- `projects/<id>/` for every id other than `TEMPLATE`
- `iris.sqlite` and any WAL / SHM sidecars
- All `datasets/`, `artifacts/`, `indexes/` contents
- `.iris/active_project` (per-checkout state, at repo root)

This is enforced by `projects/.gitignore`:

```
*
!.gitignore
!README.md
!CLAUDE.md
!TEMPLATE/
!TEMPLATE/**
```

Heavy bytes (raw recordings, plots, caches) never enter git. Back up a project by tarring its directory.

---

## Memory files

The `memory/` subtree is the **human-readable view** of curated knowledge. Every file is regenerated from `iris.sqlite` by the views renderer (`src/iris/projects/views.py` post-REVAMP). Editing these files by hand has no effect on the agent's memory — the next render overwrites them.

| File | Backed by | Contents |
|---|---|---|
| `PROJECT.md` | `projects`, top `memory_entries` (goal / context), active `datasets` summary | The project's identity card + active objectives + current datasets |
| `DECISIONS.md` | `decisions` table (memory_entries of type `decision`/`conclusion`) | Timestamped register of settled choices, with rationale + linked evidence events |
| `OPEN_QUESTIONS.md` | `open_questions` (memory_entries of type `question`) | Unresolved threads — each with status, linked runs, proposed next steps |
| `DATASETS/<dataset-id>.md` | `datasets`, `dataset_versions`, profile annotations | Per-dataset card: shape, column roles, confirmed annotations, provenance |

Writes flow SQLite-first: an agent calls `propose_memory_entry` → user approves via `commit_memory_entry` → the views renderer rewrites the affected markdown. The event chain in `events` is the actual history; markdown is a projection.

---

## Seeing the truth

When the markdown disagrees with behaviour, trust SQLite.

```bash
# Open the canonical store for a project (read-only recommended)
sqlite3 projects/<id>/iris.sqlite

# Verify the event chain is intact
SELECT event_id, type, ts FROM events ORDER BY ts LIMIT 20;

# See committed memory entries
SELECT entry_id, kind, status, content FROM memory_entries WHERE status = 'committed';

# Force-regenerate markdown views after editing SQLite directly (rare)
iris project views regenerate
```

Rules:
- **Never** edit `memory/*.md` by hand — the next render overwrites.
- **Never** delete `iris.sqlite` on a live project; use `iris project delete`.
- **Never** write directly to `datasets/` or `artifacts/` — use the import / run pipeline so the sha256 lands in SQLite.
- Agents read memory only through the daemon's memory HTTP API, never by opening `iris.sqlite` directly.

---

## See also

- [architecture.md](architecture.md) — system architecture (daemon / webapp / engine)
- [operations.md](operations.md) — operation math reference
- [../IRIS Memory Restructure.md](../IRIS%20Memory%20Restructure.md) — full memory-system spec (§6 layout, §7 schema)
- [../REVAMP.md](../REVAMP.md) — active task ledger for the memory rewrite
- [../projects/CLAUDE.md](../projects/CLAUDE.md) — projects directory nav
- [../projects/TEMPLATE/CLAUDE.md](../projects/TEMPLATE/CLAUDE.md) — per-project nav stub
- [../src/iris/projects/CLAUDE.md](../src/iris/projects/CLAUDE.md) — projects module map
- [../src/iris/daemon/CLAUDE.md](../src/iris/daemon/CLAUDE.md) — daemon (memory HTTP API)
- [../configs/CLAUDE.md](../configs/CLAUDE.md) — global config
