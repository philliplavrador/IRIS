"""Loader for the single-file TOML config used by IRIS.

Since REVAMP Task 0.7 there is one global config file: ``configs/config.toml``.
It supersedes the legacy ``paths.yaml``, ``ops.yaml``, ``globals.yaml``, and
``agent_rules.yaml`` quartet. Per-project overrides live at
``projects/<name>/config.toml`` and are deep-merged on top of the global file
by :func:`apply_project_overrides`.

This module is the single entry point both the CLI and the Python daemon use
to load and validate configuration.

Public API (stable across the migration):

* :func:`load_configs` — read and expand the global TOML.
* :func:`apply_project_overrides` — return a new ``IrisConfig`` with per-project
  overrides layered in.
* :func:`render_summary` — human-readable one-screen dump.
* :func:`edit_yaml` — retained name for backwards CLI compatibility; now edits
  the TOML file. Callers should migrate to :func:`edit_config` over time.
* :class:`IrisConfig` — the bundle.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from dataclasses import replace as _dc_replace
from pathlib import Path
from typing import Any

DEFAULT_CONFIG_DIR = "configs"
CONFIG_FILENAME = "config.toml"

_REQUIRED_PATH_KEYS = ("mea_h5", "ca_traces_npz", "output_dir", "cache_dir")
_OPTIONAL_PATH_KEYS = ("rt_model_outputs_npy", "rt_model_path")

# Mapping from the flat top-level keys we expose via ``cfg.globals`` to their
# home under the new TOML sections. The engine + CLI still reason in terms of
# a single flat globals dict, so we keep the surface stable.
_GLOBALS_FROM_SECTIONS: tuple[tuple[str, str, str], ...] = (
    # (flat_key, toml_section, toml_key)
    ("plot_backend", "plot", "backend"),
    ("show_ops_params", "plot", "show_ops_params"),
    ("save_plots", "plot", "save_plots"),
    ("window_ms", "plot", "window_ms"),
    ("memory_cache", "engine", "memory_cache"),
    ("disk_cache", "engine", "disk_cache"),
)


@dataclass
class IrisConfig:
    """Bundle of all config after loading and path expansion.

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
    agent: dict[str, Any] = field(default_factory=dict)
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
    ``[paths]``.
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


def _load_toml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"config file not found: {path}")
    with path.open("rb") as f:
        data = tomllib.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must be a TOML table, got {type(data).__name__}")
    return data


def _flatten_globals(raw: dict[str, Any]) -> dict[str, Any]:
    """Project the sectioned TOML into the flat ``globals`` dict the engine expects."""
    out: dict[str, Any] = {}
    for flat_key, section, toml_key in _GLOBALS_FROM_SECTIONS:
        section_dict = raw.get(section)
        if isinstance(section_dict, dict) and toml_key in section_dict:
            out[flat_key] = section_dict[toml_key]
    return out


def load_configs(config_dir: Path | str = DEFAULT_CONFIG_DIR) -> IrisConfig:
    """Load and lightly validate ``configs/config.toml``.

    Returns a ``IrisConfig`` with paths expanded to absolute strings. Missing
    referenced files are recorded in ``missing_paths`` (warned, not raised) so
    the agent can flag them in its config-verify flow.
    """
    cfg_dir = Path(config_dir).resolve()
    if not cfg_dir.is_dir():
        raise FileNotFoundError(f"config directory not found: {cfg_dir}")

    project_root = find_project_root(cfg_dir)

    raw = _load_toml(cfg_dir / CONFIG_FILENAME)

    paths = raw.get("paths") or {}
    ops = raw.get("ops") or {}
    agent = raw.get("agent") or {}

    if not isinstance(paths, dict):
        raise ValueError(f"[paths] must be a table, got {type(paths).__name__}")
    if not isinstance(ops, dict):
        raise ValueError(f"[ops] must be a table, got {type(ops).__name__}")
    if not isinstance(agent, dict):
        raise ValueError(f"[agent] must be a table, got {type(agent).__name__}")

    missing_required = [k for k in _REQUIRED_PATH_KEYS if k not in paths]
    if missing_required:
        raise KeyError(
            f"[paths] is missing required keys: {missing_required}. "
            f"Required: {list(_REQUIRED_PATH_KEYS)}"
        )

    expanded_paths: dict[str, str] = {}
    missing_files: list[str] = []
    for key, value in paths.items():
        if not isinstance(value, str):
            raise ValueError(f"[paths].{key} must be a string, got {type(value).__name__}")
        abs_path = _expand(value, project_root)
        expanded_paths[key] = abs_path
        if key not in ("output_dir", "cache_dir") and not Path(abs_path).exists():
            missing_files.append(f"{key}: {abs_path}")

    Path(expanded_paths["output_dir"]).mkdir(parents=True, exist_ok=True)
    Path(expanded_paths["cache_dir"]).mkdir(parents=True, exist_ok=True)

    # Normalize each op's params into a dict (TOML guarantees this when the
    # section is `[ops.<name>]`, but defensive copy keeps callers safe).
    normalized_ops: dict[str, dict[str, Any]] = {}
    for op_name, params in ops.items():
        if not isinstance(params, dict):
            raise ValueError(f"[ops.{op_name}] must be a table, got {type(params).__name__}")
        normalized_ops[op_name] = dict(params)

    return IrisConfig(
        paths=expanded_paths,
        ops=normalized_ops,
        globals=_flatten_globals(raw),
        config_dir=cfg_dir,
        project_root=project_root,
        agent=dict(agent),
        missing_paths=missing_files,
    )


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


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge ``override`` on top of ``base``; override wins."""
    out = dict(base)
    for k, v in override.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def apply_project_overrides(cfg: IrisConfig, project_dir: Path) -> IrisConfig:
    """Rewrite a global config for a specific project workspace.

    Redirects ``paths["output_dir"]`` -> ``<project_dir>/output`` and
    ``paths["cache_dir"]`` -> ``<project_dir>/.cache`` so runs land inside
    the project. If the project has a ``config.toml`` with matching sections
    (``[paths]``, ``[ops.<name>]``, ``[plot]``, ``[engine]``, ``[agent]``),
    deep-merges them into the corresponding dicts with project values winning.

    Returns a new ``IrisConfig`` (does not mutate the input).
    """
    project_dir = Path(project_dir).resolve()
    if not project_dir.is_dir():
        raise FileNotFoundError(f"project directory not found: {project_dir}")

    new_paths = dict(cfg.paths)
    new_ops = {k: dict(v) for k, v in cfg.ops.items()}
    new_globals = dict(cfg.globals)
    new_agent = dict(cfg.agent)

    # Project workspace layout
    output_dir = project_dir / "output"
    cache_dir = project_dir / ".cache"
    output_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)
    new_paths["output_dir"] = str(output_dir)
    new_paths["cache_dir"] = str(cache_dir)

    # Project-level overrides from config.toml
    project_cfg_path = project_dir / CONFIG_FILENAME
    if project_cfg_path.is_file():
        data = _load_toml(project_cfg_path)

        paths_over = data.get("paths") or {}
        ops_over = data.get("ops") or {}
        agent_over = data.get("agent") or {}

        if isinstance(paths_over, dict):
            for k, v in paths_over.items():
                if isinstance(v, str) and v != "":
                    new_paths[k] = _expand(v, cfg.project_root)
                elif v not in (None, ""):
                    new_paths[k] = v

        if isinstance(ops_over, dict):
            for op_name, params in ops_over.items():
                if not isinstance(params, dict):
                    continue
                base = dict(new_ops.get(op_name, {}))
                base.update(params)
                new_ops[op_name] = base

        # [plot] / [engine] overrides flow into the flat globals dict.
        project_globals = _flatten_globals(data)
        for k, v in project_globals.items():
            if v not in (None, ""):
                new_globals[k] = v

        if isinstance(agent_over, dict):
            new_agent = _deep_merge(new_agent, agent_over)

    return _dc_replace(
        cfg,
        paths=new_paths,
        ops=new_ops,
        globals=new_globals,
        agent=new_agent,
        project_dir=project_dir,
    )


# ---------------------------------------------------------------------------
# Minimal TOML writer for in-place edits. Stdlib has tomllib (read-only), and
# we don't want a new runtime dep for one CLI verb, so we hand-roll a writer
# that covers the subset our config.toml uses: str, int, float, bool, list of
# scalars, and nested tables keyed by [section] / [section.sub].
# ---------------------------------------------------------------------------


def _toml_escape(s: str) -> str:
    # Basic-string escaping (TOML §Strings). Covers backslash, quote, control.
    out = []
    for ch in s:
        o = ord(ch)
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif o < 0x20:
            out.append(f"\\u{o:04X}")
        else:
            out.append(ch)
    return "".join(out)


def _format_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        if "\n" in value:
            # Multi-line basic string.
            escaped = value.replace("\\", "\\\\").replace('"""', '\\"""')
            return f'"""\n{escaped}"""'
        return f'"{_toml_escape(value)}"'
    if value is None:
        return '""'
    if isinstance(value, list):
        inner = ", ".join(_format_scalar(v) for v in value)
        return f"[{inner}]"
    raise TypeError(f"unsupported TOML scalar: {type(value).__name__}")


def _dump_toml(path: Path, data: dict[str, Any]) -> None:
    """Serialize ``data`` to ``path`` using the subset IRIS configs require."""

    def emit_table(prefix: str, table: dict[str, Any], lines: list[str]) -> None:
        scalars: dict[str, Any] = {}
        subtables: dict[str, dict[str, Any]] = {}
        for k, v in table.items():
            if isinstance(v, dict):
                subtables[k] = v
            else:
                scalars[k] = v
        if prefix and (scalars or not subtables):
            lines.append(f"[{prefix}]")
        for k, v in scalars.items():
            lines.append(f"{k} = {_format_scalar(v)}")
        if scalars:
            lines.append("")
        for k, v in subtables.items():
            child_prefix = f"{prefix}.{k}" if prefix else k
            emit_table(child_prefix, v, lines)

    lines: list[str] = []
    # Emit top-level scalars first (there shouldn't be any in our layout but
    # we handle it for completeness).
    top_scalars: dict[str, Any] = {}
    top_tables: dict[str, dict[str, Any]] = {}
    for k, v in data.items():
        if isinstance(v, dict):
            top_tables[k] = v
        else:
            top_scalars[k] = v
    for k, v in top_scalars.items():
        lines.append(f"{k} = {_format_scalar(v)}")
    if top_scalars:
        lines.append("")
    for k, v in top_tables.items():
        emit_table(k, v, lines)

    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        f.write("\n".join(lines).rstrip() + "\n")
    tmp.replace(path)


# Legacy CLI bucket aliases → the section they now live in.
_LEGACY_BUCKET_MAP: dict[str, tuple[str, ...]] = {
    "paths": ("paths",),
    "ops": ("ops",),
    "globals": (),  # globals are resolved via _GLOBALS_FROM_SECTIONS below
}


def _resolve_globals_key(dotted: str) -> tuple[str, ...]:
    """Map a legacy ``globals`` dotted key onto its new TOML path."""
    for flat_key, section, toml_key in _GLOBALS_FROM_SECTIONS:
        if dotted == flat_key:
            return (section, toml_key)
    # Fallback: treat as a raw dotted key under no section — not supported for
    # writes into the new schema, so raise a clear error.
    raise KeyError(
        f"unknown global key {dotted!r}; valid: {[flat for flat, _, _ in _GLOBALS_FROM_SECTIONS]}"
    )


def edit_config(cfg_dir: Path | str, section: str, key_path: str, value: Any) -> None:
    """In-place atomic edit of a single key in ``configs/config.toml``.

    ``section`` is the legacy bucket name ("paths", "ops", or "globals"); it
    selects how ``key_path`` is resolved onto the TOML schema. ``key_path`` is
    dotted (e.g. ``butter_bandpass.low_hz`` for ``[ops.butter_bandpass]``).
    """
    cfg_dir = Path(cfg_dir).resolve()
    if section not in _LEGACY_BUCKET_MAP:
        raise ValueError(f"section must be one of {list(_LEGACY_BUCKET_MAP)}, got {section!r}")

    path = cfg_dir / CONFIG_FILENAME
    data = _load_toml(path)

    if section == "globals":
        parts = _resolve_globals_key(key_path)
    else:
        parts = (*_LEGACY_BUCKET_MAP[section], *key_path.split("."))

    target: dict[str, Any] = data
    for part in parts[:-1]:
        node = target.get(part)
        if not isinstance(node, dict):
            node = {}
            target[part] = node
        target = node
    target[parts[-1]] = value

    _dump_toml(path, data)


# Backwards-compatible alias so existing CLI code (``from iris.config import
# edit_yaml``) keeps working during the migration. New callers should use
# :func:`edit_config`.
edit_yaml = edit_config
