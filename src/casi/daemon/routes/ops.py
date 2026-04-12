"""Operations listing routes for the CASI daemon."""
from __future__ import annotations

from fastapi import APIRouter

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
                "input_type": in_type,
                "output_type": out_type,
            })
    return ops
