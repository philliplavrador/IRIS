"""Margin calculators for filter operations."""
from __future__ import annotations

from typing import Dict

from casi.engine.types import PipelineContext


def margin_butter_bandpass(params: Dict, ctx: PipelineContext) -> int:
    order = params.get('order', 10)
    low_hz = params.get('low_hz', 300)
    return int(3 * order * ctx.mea_fs_hz / low_hz)


def margin_notch_filter(params: Dict, ctx: PipelineContext) -> int:
    q = params.get('notch_q', 30.0)
    freq = params.get('notch_freq_hz', 60.0)
    return 3 * int(q * ctx.mea_fs_hz / freq)
