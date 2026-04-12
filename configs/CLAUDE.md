# configs/ — config navigation

Three YAML files drive CASI runs. Loaded by both the CLI and the Python daemon via `casi.config.load_configs()`.

## Files

| File | What it holds |
|---|---|
| [paths.yaml](paths.yaml) | File paths: `mea_h5`, `ca_traces_npz`, `rt_model_path`, `output_dir`, `cache_dir`. Supports `~`, `${ENV_VAR}`, and relative paths. |
| [ops.yaml](ops.yaml) | Default parameters for every operation. Flat — op name → params dict. |
| [globals.yaml](globals.yaml) | Execution settings: `plot_backend`, `window_ms`, cache toggles. |

## How project overrides compose

When a project is active, `casi.config.apply_project_overrides` rewrites the global config in memory:

1. `paths["output_dir"]` → `projects/<name>/output`
2. `paths["cache_dir"]` → `projects/<name>/.cache`
3. Any `paths_overrides`, `ops_overrides`, `globals_overrides` in `projects/<name>/claude_config.yaml` are deep-merged (project wins).

The global `configs/` files are never mutated by this; the override is in-memory.

## Rules

- **Never** edit these files directly from the agent. Use `casi config edit <file> <key> <value>`.
- **Never** add new required keys without updating `_REQUIRED_PATH_KEYS` in [../src/casi/config.py](../src/casi/config.py).

## See also
- [../CLAUDE.md](../CLAUDE.md) — repo root nav
- [../src/casi/config.py](../src/casi/config.py) — loader + override logic
