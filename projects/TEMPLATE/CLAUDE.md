# Project navigation (TEMPLATE)

This is the committed skeleton copied into every new IRIS project. A real
project is a self-contained, portable folder: copy or move the directory to
back up, archive, or share the work.

## Layout (spec: `IRIS Memory Restructure.md` §6)

```
<project>/
├── config.toml           # Per-project config (name, description, dials, overrides)
├── iris.sqlite           # Runtime-created by db.init_schema(); NOT committed
├── memory/               # Human-readable curated notes (markdown)
│   ├── PROJECT.md        # Goals, hypotheses, open questions, caveats, preferences
│   ├── DECISIONS.md      # Decision & conclusion register
│   ├── OPEN_QUESTIONS.md # Open questions register
│   └── DATASETS/         # One <dataset-id>.md card per imported dataset
├── datasets/
│   ├── raw/<dataset-id>/<sha256>.<ext>     # Original uploads (content-addressed)
│   └── derived/<dataset-id>/<sha256>.<ext> # Transformed versions
├── artifacts/<sha256>/   # Content-addressed outputs (plots, reports, caches)
├── ops/<op-name>/v<semver>/  # Project-scoped versioned operations
└── indexes/              # Vector / FTS indexes (runtime, not committed)
```

## Key principles

- `iris.sqlite` is the programmatic interface; the Markdown files in `memory/`
  are the human interface. Both are kept in sync.
- Immutable "heavy" objects (datasets, artifacts) live outside mutable curated
  notes and outside versioned ops.
- Each project is self-contained — no cross-project file dependencies.

## Runtime-created, not committed

`iris.sqlite` (and its `-wal` / `-shm` siblings) are created by
`db.init_schema()` on first use. The `indexes/`, `datasets/`, and `artifacts/`
directories keep only `.gitkeep` markers in the template; their real contents
are gitignored.

## See also

- [../CLAUDE.md](../CLAUDE.md) — `projects/` directory navigation
- [../../src/iris/projects/CLAUDE.md](../../src/iris/projects/CLAUDE.md) — lifecycle & memory API
- `IRIS Memory Restructure.md` §6 — filesystem layout spec
