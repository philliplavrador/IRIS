"""Loader for the configs/{paths,ops,globals}.yaml files.

The IRIS pipeline is configured via three YAML files instead of inline Python
dicts. This module is the single entry point both the CLI and the example
notebooks use to load and validate them.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_DIR = "configs"
PATHS_FILE = "paths.yaml"
OPS_FILE = "ops.yaml"
GLOBALS_FILE = "globals.yaml"

_REQUIRED_PATH_KEYS = ("mea_h5", "ca_traces_npz", "output_dir", "cache_dir")
_OPTIONAL_PATH_KEYS = ("rt_model_outputs_npy", "rt_model_path")


@dataclass
class IrisConfig:
    """Bundle of all three configs after loading and path expansion.

    If ``project_dir`` is set, this config has been rewritten for a specific
    project workspace (via :func:`apply_project_overrides`): ``paths["output_dir"]``
    points at ``<project_dir>/output`` and ``paths["cache_dir"]`` points at
    ``<project_dir>/.cache``.
    """
    paths: dict[str, str]
    ops: dict[str, dict[str, Any]]
    globals: dict[str, Any]
    config_dir: Path
    project_root: Path
    missing_paths: list[str] = field(default_factory=list)
    project_dir: Path | None = None

    def as_run_pipeline_kwargs(self) -> dict[str, Any]:
        """Spread into ``run_pipeline(**cfg.as_run_pipeline_kwargs(), pipeline_cfg=...)``."""
        return {
            "paths_cfg": self.paths,
            "ops_cfg": self.ops,
            "globals_cfg": self.globals,
        }


def find_project_root(start: Path | str | None = None) -> Path:
    """Walk upward from ``start`` until a pyproject.toml is found.

    Falls back to the current working directory if no pyproject.toml exists
    on the path. The project root is used to resolve relative paths in
    paths.yaml.
    """
    p = Path(start or Path.cwd()).resolve()
    for candidate in (p, *p.parents):
        if (candidate / "pyproject.toml").is_file():
            return candidate
    return p


def _expand(path_str: str, project_root: Path) -> str:
    """Expand ~, ${VAR}, and resolve relative paths against the project root."""
    expanded = os.path.expandvars(os.path.expanduser(path_str))
    p = Path(expanded)
    if not p.is_absolute():
        p = (project_root / p).resolve()
    return str(p)


def load_configs(config_dir: Path | str = DEFAULT_CONFIG_DIR) -> IrisConfig:
    """Load and lightly validate paths.yaml + ops.yaml + globals.yaml.

    Returns a ``IrisConfig`` with paths expanded to absolute strings. Missing
    referenced files are recorded in ``missing_paths`` (warned, not raised) so
    the agent can flag them in its config-verify flow.
    """
    cfg_dir = Path(config_dir).resolve()
    if not cfg_dir.is_dir():
        raise FileNotFoundError(f"config directory not found: {cfg_dir}")

    project_root = find_project_root(cfg_dir)

    paths = _load_yaml(cfg_dir / PATHS_FILE)
    ops = _load_yaml(cfg_dir / OPS_FILE)
    globals_ = _load_yaml(cfg_dir / GLOBALS_FILE)

    if not isinstance(paths, dict):
        raise ValueError(f"{PATHS_FILE} must be a mapping, got {type(paths).__name__}")
    if not isinstance(ops, dict):
        raise ValueError(f"{OPS_FILE} must be a mapping, got {type(ops).__name__}")
    if not isinstance(globals_, dict):
        raise ValueError(f"{GLOBALS_FILE} must be a mapping, got {type(globals_).__name__}")

    missing_required = [k for k in _REQUIRED_PATH_KEYS if k not in paths]
    if missing_required:
        raise KeyError(
            f"{PATHS_FILE} is missing required keys: {missing_required}. "
            f"Required: {list(_REQUIRED_PATH_KEYS)}"
        )

    expanded_paths: dict[str, str] = {}
    missing_files: list[str] = []
    for key, value in paths.items():
        if not isinstance(value, str):
            raise ValueError(f"{PATHS_FILE}: {key} must be a string, got {type(value).__name__}")
        abs_path = _expand(value, project_root)
        expanded_paths[key] = abs_path
        if key not in ("output_dir", "cache_dir") and not Path(abs_path).exists():
            missing_files.append(f"{key}: {abs_path}")

    Path(expanded_paths["output_dir"]).mkdir(parents=True, exist_ok=True)
    Path(expanded_paths["cache_dir"]).mkdir(parents=True, exist_ok=True)

    return IrisConfig(
        paths=expanded_paths,
        ops=ops,
        globals=globals_,
        config_dir=cfg_dir,
        project_root=project_root,
        missing_paths=missing_files,
    )


def _load_yaml(path: Path) -> Any:
    if not path.is_file():
        raise FileNotFoundError(f"config file not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def render_summary(cfg: IrisConfig) -> str:
    """Human-readable one-screen summary used by `iris config show` and the agent."""
    lines: list[str] = []
    lines.append(f"IRIS configuration  (project root: {cfg.project_root})")
    lines.append("")

    lines.append("Paths:")
    for key in (*_REQUIRED_PATH_KEYS, *_OPTIONAL_PATH_KEYS):
        if key in cfg.paths:
            value = cfg.paths[key]
            tag = ""
            if key not in ("output_dir", "cache_dir") and not Path(value).exists():
                tag = "  [MISSING]"
            lines.append(f"  {key:<22} {value}{tag}")
    extra = sorted(set(cfg.paths) - set(_REQUIRED_PATH_KEYS) - set(_OPTIONAL_PATH_KEYS))
    for key in extra:
        lines.append(f"  {key:<22} {cfg.paths[key]}")
    lines.append("")

    lines.append("Globals:")
    for key, value in cfg.globals.items():
        lines.append(f"  {key:<22} {value!r}")
    lines.append("")

    lines.append(f"Ops: {len(cfg.ops)} loaded ({', '.join(sorted(cfg.ops))})")

    if cfg.missing_paths:
        lines.append("")
        lines.append("WARNING: missing files:")
        for entry in cfg.missing_paths:
            lines.append(f"  - {entry}")

    return "\n".join(lines)


def apply_project_overrides(cfg: IrisConfig, project_dir: Path) -> IrisConfig:
    """Rewrite a global config for a specific project workspace.

    Redirects ``paths["output_dir"]`` -> ``<project_dir>/output`` and
    ``paths["cache_dir"]`` -> ``<project_dir>/.cache`` so runs land inside
    the project. If the project has a ``claude_config.yaml`` with
    ``paths_overrides`` / ``ops_overrides`` / ``globals_overrides`` sections,
    deep-merges them into the corresponding dicts with project values winning.

    Returns a new ``IrisConfig`` (does not mutate the input).
    """
    from dataclasses import replace as _dc_replace

    project_dir = Path(project_dir).resolve()
    if not project_dir.is_dir():
        raise FileNotFoundError(f"project directory not found: {project_dir}")

    new_paths = dict(cfg.paths)
    new_ops = {k: dict(v) for k, v in cfg.ops.items()}
    new_globals = dict(cfg.globals)

    # Project workspace layout
    output_dir = project_dir / "output"
    cache_dir = project_dir / ".cache"
    output_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)
    new_paths["output_dir"] = str(output_dir)
    new_paths["cache_dir"] = str(cache_dir)

    # Project-level overrides from claude_config.yaml
    project_cfg_path = project_dir / "claude_config.yaml"
    if project_cfg_path.is_file():
        data = _load_yaml(project_cfg_path) or {}
        if isinstance(data, dict):
            paths_over = data.get("paths_overrides") or {}
            ops_over = data.get("ops_overrides") or {}
            globals_over = data.get("globals_overrides") or {}
            if isinstance(paths_over, dict):
                for k, v in paths_over.items():
                    if isinstance(v, str):
                        new_paths[k] = _expand(v, cfg.project_root)
                    else:
                        new_paths[k] = v
            if isinstance(ops_over, dict):
                for op_name, params in ops_over.items():
                    if not isinstance(params, dict):
                        continue
                    base = dict(new_ops.get(op_name, {}))
                    base.update(params)
                    new_ops[op_name] = base
            if isinstance(globals_over, dict):
                new_globals.update(globals_over)

    return _dc_replace(
        cfg,
        paths=new_paths,
        ops=new_ops,
        globals=new_globals,
        project_dir=project_dir,
    )


def edit_yaml(cfg_dir: Path | str, file: str, key_path: str, value: Any) -> None:
    """In-place atomic edit of a single key in one of the config files.

    ``file`` is one of "paths", "ops", "globals".
    ``key_path`` is dotted, e.g. "butter_bandpass.low_hz" or "mea_h5".
    """
    cfg_dir = Path(cfg_dir).resolve()
    file_map = {"paths": PATHS_FILE, "ops": OPS_FILE, "globals": GLOBALS_FILE}
    if file not in file_map:
        raise ValueError(f"file must be one of {list(file_map)}, got {file!r}")

    path = cfg_dir / file_map[file]
    data = _load_yaml(path)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must be a mapping")

    parts = key_path.split(".")
    target = data
    for part in parts[:-1]:
        if part not in target or not isinstance(target[part], dict):
            target[part] = {}
        target = target[part]
    target[parts[-1]] = value

    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, default_flow_style=False)
    tmp.replace(path)
