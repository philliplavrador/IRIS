"""Config routes for the CASI daemon."""
from __future__ import annotations

from fastapi import APIRouter

from casi.daemon.app import get_config

router = APIRouter(tags=["config"])


@router.get("/config")
async def show_config():
    """Return the loaded configuration as JSON."""
    config = get_config()
    return {
        "paths": config.paths,
        "ops": config.ops,
        "globals": config.globals,
        "missing_paths": config.missing_paths,
    }
