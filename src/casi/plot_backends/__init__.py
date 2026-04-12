"""Plot backend dispatcher for CASI.

The pipeline supports four interchangeable plot backends, selected via
``globals_cfg["plot_backend"]``:

    "matplotlib"        — static PNG via matplotlib (default, headless-safe)
    "matplotlib_widget" — interactive ipympl widget (Jupyter notebooks)
    "pyqtgraph"         — standalone Qt desktop GUI window
    "pyqplot"           — publication-quality PDF / PNG / SVG via qplot

Each backend module exposes a ``register(registry)`` function that registers
its plot handlers against an :class:`casi.engine.OpRegistry`.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from casi.engine import OpRegistry


VALID_BACKENDS = ("matplotlib", "matplotlib_widget", "pyqtgraph", "pyqplot")


def register_for_backend(registry: "OpRegistry", plot_backend: str) -> None:
    """Register the plot handlers for the chosen backend on ``registry``."""
    if plot_backend in ("matplotlib", "matplotlib_widget"):
        from casi.plot_backends import matplotlib_backend
        matplotlib_backend.register(registry)
    elif plot_backend == "pyqtgraph":
        from casi.plot_backends import pyqtgraph_backend
        pyqtgraph_backend.register(registry)
    elif plot_backend == "pyqplot":
        from casi.plot_backends import pyqplot_backend
        pyqplot_backend.register(registry)
    else:
        raise ValueError(
            f"Unknown plot_backend: {plot_backend!r}. "
            f"Valid choices: {VALID_BACKENDS}"
        )
