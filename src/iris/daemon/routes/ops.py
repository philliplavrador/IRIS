"""Operations listing routes for the IRIS daemon."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

router = APIRouter(tags=["ops"])


@router.get("/ops")
async def list_ops():
    """List all registered operations with type transitions.

    Every op registered in ``create_registry()`` (17 hardcoded ops today)
    appears here. Binary function-ops (``spike_curate``, ``x_corr``) carry
    their right-operand type via the ``right_input_type`` field; unary
    ops set it to ``None``.
    """
    from iris.engine.type_system import BINARY_OP_SIGNATURES, TYPE_TRANSITIONS

    ops = []
    for op_name, transitions in TYPE_TRANSITIONS.items():
        right_type = BINARY_OP_SIGNATURES.get(op_name)
        right_name = right_type.__name__ if right_type is not None else None
        for in_type, out_type in transitions.items():
            ops.append(
                {
                    "name": op_name,
                    "input_type": in_type.__name__,
                    "output_type": out_type.__name__,
                    "right_input_type": right_name,
                    "kind": "binary" if right_name else "unary",
                }
            )
    return ops


@router.get("/ops/{name}")
async def get_op(name: str):
    """Get details for a single operation including param schema from ops.yaml."""
    from iris.engine import TYPE_TRANSITIONS

    if name not in TYPE_TRANSITIONS:
        raise HTTPException(status_code=404, detail=f"Unknown op: '{name}'")

    transitions = TYPE_TRANSITIONS[name]
    type_info = [
        {"input_type": in_t.__name__, "output_type": out_t.__name__}
        for in_t, out_t in transitions.items()
    ]

    # Load param defaults from config
    from iris.daemon.app import _config

    params: dict = {}
    if _config is not None:
        ops_cfg = getattr(_config, "ops", None) or {}
        params = ops_cfg.get(name, {}) or {}

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
