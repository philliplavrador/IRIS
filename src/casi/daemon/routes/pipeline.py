"""Pipeline execution routes for the CASI daemon."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(tags=["pipeline"])


class RunRequest(BaseModel):
    dsl: str
    window: str = "full"
    force: bool = False


@router.post("/run")
async def run_pipeline(req: RunRequest):
    """Execute a DSL pipeline using the warm registry and caches."""
    from casi.daemon.app import _config, _registry, _source_loaders, get_casi_root

    if _config is None or _registry is None:
        raise HTTPException(status_code=503, detail="Daemon not initialized")

    try:
        from casi.engine import run_pipeline as _run_pipeline

        result = _run_pipeline(
            req.dsl,
            config=_config,
            registry=_registry,
            source_loaders=_source_loaders,
            casi_root=str(get_casi_root()),
            window=req.window,
            force=req.force,
        )

        return {
            "ok": True,
            "result_type": type(result).__name__ if result else None,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
