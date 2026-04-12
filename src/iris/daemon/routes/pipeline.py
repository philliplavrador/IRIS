"""Pipeline execution routes for the IRIS daemon."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(tags=["pipeline"])


class RunRequest(BaseModel):
    dsl: str
    window: str = "full"
    force: bool = False
    backend: Optional[str] = None
    session_label: Optional[str] = None


@router.post("/run")
async def run_pipeline(req: RunRequest):
    """Execute a DSL pipeline with active project resolution and session tracking."""
    from iris.daemon.app import _config, _registry, _source_loaders

    if _config is None or _registry is None:
        raise HTTPException(status_code=503, detail="Daemon not initialized")

    # Resolve active project
    from iris.projects import (
        find_cached_plots,
        project_cache_dir,
        project_output_dir,
        resolve_active_project,
    )

    project_path = resolve_active_project()
    if project_path is None:
        raise HTTPException(
            status_code=400,
            detail="No active project. Open a project first via POST /api/projects/open."
        )

    # Parse window directive
    if req.window == "full":
        window_ms = "full"
    else:
        try:
            parts = [float(x.strip()) for x in req.window.split(",")]
            if len(parts) != 2:
                raise ValueError
            window_ms = parts
        except (ValueError, AttributeError):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid window format: '{req.window}'. Use 'full' or 'start,end'."
            )

    # Check for cached plots (skip if --force)
    if not req.force:
        try:
            cached = find_cached_plots(
                project_path, req.dsl, _config.get("paths", {}), window_ms
            )
            if cached:
                return {
                    "ok": True,
                    "cached": True,
                    "plot_path": str(cached[0].plot_path),
                    "sidecar_path": str(cached[0].sidecar_path),
                }
        except Exception:
            pass  # best-effort cache check, don't block execution

    # Create session for this run
    from iris.sessions import new_session

    output_dir = project_output_dir(project_path)
    session_dir = new_session(label=req.session_label, output_root=output_dir)

    # Build pipeline config with project overrides
    from iris.config import apply_project_overrides

    paths_cfg = dict(_config.get("paths", {}))
    ops_cfg = dict(_config.get("ops", {}))
    globals_cfg = dict(_config.get("globals", {}))

    try:
        apply_project_overrides(paths_cfg, ops_cfg, globals_cfg, project_path)
    except Exception:
        pass  # project may not have overrides

    # Set output and cache dirs
    paths_cfg["output_dir"] = str(session_dir)
    paths_cfg["cache_dir"] = str(project_cache_dir(project_path))

    # Apply window
    if window_ms == "full":
        globals_cfg["window_ms"] = "full"
    else:
        globals_cfg["window_ms"] = window_ms

    # Apply backend override
    if req.backend:
        globals_cfg["plot_backend"] = req.backend

    globals_cfg["save_plots"] = True

    try:
        from iris.engine import run_pipeline as _run_pipeline

        pipeline_cfg = [req.dsl]

        # Determine registry — use override backend if provided
        registry = _registry
        source_loaders = _source_loaders
        if req.backend and req.backend != globals_cfg.get("plot_backend", "matplotlib"):
            from iris.engine import create_registry
            registry, source_loaders = create_registry(plot_backend=req.backend)

        results = _run_pipeline(
            paths_cfg=paths_cfg,
            ops_cfg=ops_cfg,
            pipeline_cfg=pipeline_cfg,
            registry=registry,
            source_loaders=source_loaders,
            globals_cfg=globals_cfg,
            verbose=False,
            plot=True,
        )

        result_type = None
        if results:
            _, last_result = results[-1]
            if last_result is not None:
                result_type = type(last_result).__name__

        return {
            "ok": True,
            "cached": False,
            "result_type": result_type,
            "session_dir": str(session_dir),
        }
    except TypeError as e:
        raise HTTPException(status_code=400, detail=f"Type error in pipeline: {e}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid pipeline: {e}")
    except KeyError as e:
        raise HTTPException(status_code=400, detail=f"Missing key: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
