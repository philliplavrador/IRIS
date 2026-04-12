"""Plot backend dispatcher for IRIS.

The pipeline supports two matplotlib-based backends, selected via
``globals_cfg["plot_backend"]``:

    "matplotlib"        — static PNG via matplotlib (default, headless-safe)
    "matplotlib_widget" — interactive ipympl widget (Jupyter notebooks)

Each backend module exposes a ``register(registry)`` function that registers
its plot handlers against an :class:`iris.engine.OpRegistry`.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from iris.engine import OpRegistry


VALID_BACKENDS = ("matplotlib", "matplotlib_widget")


def register_for_backend(registry: "OpRegistry", plot_backend: str) -> None:
    """Register the plot handlers for the chosen backend on ``registry``."""
    if plot_backend in ("matplotlib", "matplotlib_widget"):
        from iris.plot_backends import matplotlib_backend
        matplotlib_backend.register(registry)
    else:
        raise ValueError(
            f"Unknown plot_backend: {plot_backend!r}. "
            f"Valid choices: {VALID_BACKENDS}"
        )
