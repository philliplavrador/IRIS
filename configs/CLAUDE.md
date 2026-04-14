# configs/ — config navigation

IRIS is configured from a single TOML file. It replaced the legacy
`paths.yaml` / `ops.yaml` / `globals.yaml` / `agent_rules.yaml` quartet in
REVAMP Task 0.7. Loaded by both the CLI and the Python daemon via
`iris.config.load_configs()`, which uses stdlib `tomllib`.

## File

- [config.toml](config.toml) — global defaults. Per-project overrides (same
  schema, partial) live at `projects/<name>/config.toml`.

## Schema overview

| Section | What it holds |
|---|---|
| `[paths]` | Required: `mea_h5`, `ca_traces_npz`, `output_dir`, `cache_dir`. Optional: `rt_model_outputs_npy`, `rt_model_path`. Relative paths resolve against the repo root; `~` and `${ENV_VAR}` expand. |
| `[engine]` | Execution knobs: `memory_cache`, `disk_cache`. |
| `[plot]` | Plot backend + annotation defaults: `backend`, `show_ops_params`, `save_plots`, `window_ms`. |
| `[agent]` | `rules` (multiline string). |
| `[agent.dials]` | Per-install autonomy / pushback defaults: `autonomy`, `pushback`. |
| `[ops.<op_name>]` | Per-operation parameter defaults. One table per op. |

The CLI (`iris config show`) still presents a flat `globals` dict for
backwards compatibility — that dict is projected from `[plot]` + `[engine]`
by `iris.config._flatten_globals()`.

## How project overrides compose

When a project is active, `iris.config.apply_project_overrides` reads
`projects/<name>/config.toml` and deep-merges it on top of the global config
in memory:

1. `paths["output_dir"]` → `projects/<name>/output` (always)
2. `paths["cache_dir"]` → `projects/<name>/.cache` (always)
3. `[paths]` / `[ops.*]` / `[plot]` / `[engine]` / `[agent]` sections in
   the project's `config.toml` win over the globals.

The global `configs/config.toml` is never mutated by this; the override is
in-memory only.

## Rules

- **Never** edit `config.toml` directly from the agent. Use
  `iris config edit <bucket> <key> <value>`. The bucket is one of `paths`,
  `ops`, `globals` (legacy name that still maps onto `[plot]` / `[engine]`).
- **Never** add new required keys without updating `_REQUIRED_PATH_KEYS` in
  [../src/iris/config.py](../src/iris/config.py).

## See also
- [../CLAUDE.md](../CLAUDE.md) — repo root nav
- [../src/iris/config.py](../src/iris/config.py) — loader + override logic
- `IRIS Memory Restructure.md` §6 — filesystem layout spec
