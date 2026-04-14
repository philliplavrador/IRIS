"""Session directories and provenance sidecars for IRIS pipeline runs.

Every analysis run lives in its own session directory with the layout:

    <output_root>/2026-04-10_session_001_my-label/
    ├── manifest.json                         (config snapshot, timestamps, file fingerprints)
    ├── transcript.md                         (filled by the Claude agent if used)
    ├── plot_001_<descriptive_label>.png
    ├── plot_001_<descriptive_label>.json     (DSL string + ops + params + sources)
    ├── plot_002_*.png
    └── ...

``output_root`` defaults to ``outputs/`` at the repo root but is rewritten
to ``projects/<name>/output/`` by ``cli.py:cmd_run`` when an active project
is set. Project-awareness lives entirely in the caller; this module simply
honors whatever root is passed.

The sidecar JSON files are the audit trail: any plot can be reproduced from
its sidecar even if the parent session manifest is lost.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from iris import __version__ as IRIS_VERSION
from iris.engine import ExprNode, OpNode, PipelineContext, SourceNode

DEFAULT_OUTPUT_ROOT = Path("outputs")
_SAFE_CHARS_RE = re.compile(r"[^a-zA-Z0-9._-]+")


def new_session(
    label: str | None = None,
    output_root: Path | str = DEFAULT_OUTPUT_ROOT,
) -> Path:
    """Create ``outputs/YYYY-MM-DD_session_NNN[_label]/`` and return its path.

    The numeric counter is auto-incremented to avoid clobbering an existing
    session in the same day.
    """
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    today = _dt.date.today().isoformat()

    counter = 1
    while True:
        name = f"{today}_session_{counter:03d}"
        if label:
            safe = _SAFE_CHARS_RE.sub("-", label).strip("-")[:40]
            if safe:
                name = f"{name}_{safe}"
        candidate = root / name
        if not candidate.exists():
            candidate.mkdir(parents=True)
            return candidate
        counter += 1


def list_sessions(output_root: Path | str = DEFAULT_OUTPUT_ROOT) -> list[Path]:
    """Return all session directories under ``output_root``, newest first."""
    root = Path(output_root)
    if not root.is_dir():
        return []
    sessions = [p for p in root.iterdir() if p.is_dir() and "_session_" in p.name]
    return sorted(sessions, reverse=True)


def write_manifest(
    session_dir: Path,
    ctx: PipelineContext,
    paths_cfg: dict[str, str],
    ops_cfg: dict[str, dict],
    globals_cfg: dict[str, Any],
) -> Path:
    """Write the per-session manifest.json snapshotting the active config.

    Includes file mtimes + sizes for every input file referenced in paths_cfg
    so a reader can detect whether the source data has changed since the
    session ran.
    """
    manifest = {
        "iris_version": IRIS_VERSION,
        "created_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "session_dir": str(session_dir),
        "paths": paths_cfg,
        "globals": globals_cfg,
        "ops": ops_cfg,
        "sources": _file_fingerprints(paths_cfg),
        "window_ms": list(ctx.window_ms) if ctx.window_ms != (0.0, 0.0) else None,
    }
    out = session_dir / "manifest.json"
    out.write_text(json.dumps(manifest, indent=2, default=_json_default), encoding="utf-8")
    return out


def write_provenance_sidecar(
    plot_path: Path,
    ctx: PipelineContext,
    artifact_id: str | None = None,
) -> Path | None:
    """Write ``<plot_path>.json`` with the active expression's full provenance.

    Returns the sidecar path, or ``None`` if there is no current expression
    (e.g. when called for an overlay plot).

    ``artifact_id`` is an optional content-addressed id (populated when the
    plot has also been stored via :mod:`iris.projects.artifacts`). It is
    recorded in the sidecar and manifest as a new field alongside the
    legacy path so existing frontends keep rendering while new readers can
    fetch via the artifact store.
    """
    if ctx.current_expr is None:
        return None
    sidecar = plot_path.with_suffix(plot_path.suffix + ".json")
    payload = {
        "iris_version": IRIS_VERSION,
        "timestamp": _dt.datetime.now().isoformat(timespec="seconds"),
        "plot_file": plot_path.name,
        "artifact_id": artifact_id,
        "dsl": _expr_to_dsl(ctx.current_expr),
        "window_ms": list(ctx.window_ms),
        "ops": _expand_ops(ctx.current_expr, ctx.ops_cfg),
        "sources": _file_fingerprints(ctx.paths),
        "plot_backend": getattr(ctx, "plot_backend", None),
    }
    sidecar.write_text(json.dumps(payload, indent=2, default=_json_default), encoding="utf-8")
    return sidecar


def store_plot_artifact(
    png_bytes: bytes,
    ctx: PipelineContext,
    *,
    figure_title: str | None = None,
    description: str | None = None,
) -> str | None:
    """Route plot PNG bytes through the content-addressed artifact store.

    Returns the ``artifact_id`` (== SHA-256 of the bytes) on success or
    ``None`` if no project is active / the memory layer is unavailable.
    Never raises: the caller's plot rendering must not be blocked by a
    memory-layer failure. See REVAMP.md Task 5.3.
    """
    try:
        # Imports here so the plot session module stays importable in
        # minimal environments that don't carry the memory layer.
        from iris.projects import artifacts as _artifacts
        from iris.projects import db as _proj_db
        from iris.projects import resolve_active_project

        project_path = resolve_active_project()
        if project_path is None:
            # TODO(Task 5.3): no active project → legacy path only. Once
            # plot-session roots are always project-scoped this branch
            # becomes dead code.
            return None

        conn = _proj_db.connect(project_path)
        try:
            _proj_db.init_schema(conn)
            metadata: dict[str, Any] = {
                "backend": getattr(ctx, "plot_backend", None),
                "figure_title": figure_title,
            }
            return _artifacts.store(
                conn,
                project_path,
                content=png_bytes,
                type="plot_png",
                metadata=metadata,
                description=description,
            )
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except Exception:
        # Guard absolute: plot pipeline must not crash on memory-layer
        # trouble. The legacy file path remains a complete fallback.
        return None


# ---------- helpers ----------


def _file_fingerprints(paths_cfg: dict[str, str]) -> dict[str, dict[str, Any]]:
    skip = {"output_dir", "cache_dir"}
    out: dict[str, dict[str, Any]] = {}
    for key, value in paths_cfg.items():
        if key in skip or not value:
            continue
        p = Path(value)
        if p.is_file():
            stat = p.stat()
            out[key] = {
                "path": str(p),
                "mtime": stat.st_mtime,
                "size": stat.st_size,
            }
        elif p.is_dir():
            out[key] = {"path": str(p), "kind": "directory"}
        else:
            out[key] = {"path": str(p), "missing": True}
    return out


def _expr_to_dsl(expr: ExprNode) -> str:
    parts = [f"{expr.source.source_type}({expr.source.source_id})"]
    for op in expr.ops:
        parts.append(_op_to_dsl(op))
    return ".".join(parts)


def _op_to_dsl(op: OpNode) -> str:
    if op.kwargs_overrides:
        kw = ", ".join(f"{k}={v!r}" for k, v in op.kwargs_overrides.items())
        return f"{op.op_name}({kw})"
    if op.inner_expr is not None:
        return f"{op.op_name}({_expr_to_dsl(op.inner_expr)})"
    return op.op_name


def _expand_ops(expr: ExprNode, ops_cfg: dict[str, dict]) -> list[dict]:
    """Return a list of {name, params} dicts for every op in the expression."""
    out: list[dict] = []
    for op in expr.ops:
        merged = {**ops_cfg.get(op.op_name, {}), **op.kwargs_overrides}
        entry: dict[str, Any] = {"name": op.op_name, "params": merged}
        if op.inner_expr is not None:
            entry["inner"] = {
                "source": {
                    "type": op.inner_expr.source.source_type,
                    "id": op.inner_expr.source.source_id,
                },
                "ops": _expand_ops(op.inner_expr, ops_cfg),
            }
        out.append(entry)
    return out


def _json_default(obj: Any) -> Any:
    if isinstance(obj, Path):
        return str(obj)
    if is_dataclass(obj):
        return asdict(obj)
    if hasattr(obj, "tolist"):  # numpy arrays
        return obj.tolist()
    if isinstance(obj, (set, tuple)):
        return list(obj)
    return repr(obj)
