"""Operations listing routes for the CASI daemon."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

router = APIRouter(tags=["ops"])


@router.get("/ops")
async def list_ops():
    """List all registered operations with type transitions."""
    from casi.engine import TYPE_TRANSITIONS
    ops = []
    for op_name, transitions in TYPE_TRANSITIONS.items():
        for in_type, out_type in transitions.items():
            ops.append({
                "name": op_name,
                "input_type": in_type.__name__,
                "output_type": out_type.__name__,
            })
    return ops


@router.get("/ops/{name}")
async def get_op(name: str):
    """Get details for a single operation including param schema from ops.yaml."""
    from casi.engine import TYPE_TRANSITIONS

    if name not in TYPE_TRANSITIONS:
        raise HTTPException(status_code=404, detail=f"Unknown op: '{name}'")

    transitions = TYPE_TRANSITIONS[name]
    type_info = [
        {"input_type": in_t.__name__, "output_type": out_t.__name__}
        for in_t, out_t in transitions.items()
    ]

    # Load param defaults from config
    from casi.daemon.app import _config
    params = {}
    if _config:
        params = _config.get("ops", {}).get(name, {}) or {}

    return {
        "name": name,
        "transitions": type_info,
        "default_params": params,
    }


@router.get("/sources")
async def list_sources():
    """List available source types."""
    return [
        {"name": "mea_trace", "description": "MEA voltage trace (single channel or all)"},
        {"name": "ca_trace", "description": "Calcium imaging trace (single ROI)"},
        {"name": "rtsort", "description": "RTSort model output trace"},
    ]
