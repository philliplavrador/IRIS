"""CASI — Calcium-Assisted Spike Identity.

Construction of optically-grounded ground-truth datasets for spike sorting
benchmarks via simultaneous calcium imaging and multi-electrode array recording.
"""
from __future__ import annotations

__version__ = "0.1.0"

from casi.engine import (
    create_registry,
    run_pipeline,
    clear_data_caches,
    clear_pipeline_cache,
    get_recording_duration_ms,
)

__all__ = [
    "__version__",
    "create_registry",
    "run_pipeline",
    "clear_data_caches",
    "clear_pipeline_cache",
    "get_recording_duration_ms",
]
