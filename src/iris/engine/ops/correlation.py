"""Correlation op handlers: x_corr."""
from __future__ import annotations

import numpy as np
from tqdm.auto import tqdm

from iris.engine.helpers import cross_correlate_pair
from iris.engine.types import (
    CATrace, CorrelationResult, PipelineContext, SaturationReport, SimCalciumBank,
)


def op_x_corr(left: CATrace, right: SimCalciumBank, ctx: PipelineContext, *,
              max_lag_ms=500.0, normalize=True, adapt_circle_size=False) -> CorrelationResult:
    """Cross-correlate a calcium trace against a bank of simulated calcium traces."""
    if not isinstance(left, CATrace):
        raise TypeError(f"x_corr left operand must be CATrace, got {type(left).__name__}")
    if not isinstance(right, SimCalciumBank):
        raise TypeError(f"x_corr right operand must be SimCalciumBank, got {type(right).__name__}")

    max_lag_samples = int(max_lag_ms * left.fs_hz / 1000)
    ca_signal = left.data

    correlations = np.array([
        cross_correlate_pair(ca_signal, right.traces[i], max_lag_samples, normalize)
        for i in tqdm(range(right.traces.shape[0]), desc="  x_corr", leave=False)
    ])

    best_idx = int(np.argmax(correlations))
    x_coords = np.array([info["x"] for info in right.electrode_info])
    y_coords = np.array([info["y"] for info in right.electrode_info])

    pct_masked = None
    if adapt_circle_size:
        for cached_val in ctx.cache._memory.values():
            if isinstance(cached_val, SaturationReport):
                total = cached_val.total_samples
                sat_map = {
                    int(ch): (cached_val.samples_masked[i] / total * 100 if total > 0 else 0.0)
                    for i, ch in enumerate(cached_val.channel_ids)
                }
                pct_masked = np.array([sat_map.get(info["channel"], 0.0)
                                       for info in right.electrode_info])
                break

    return CorrelationResult(
        correlations=correlations,
        best_idx=best_idx,
        best_corr=correlations[best_idx],
        electrode_info=right.electrode_info,
        ca_trace_idx=left.trace_idx,
        x_coords=x_coords,
        y_coords=y_coords,
        ca_signal=ca_signal,
        best_sim_trace=right.traces[best_idx],
        window_samples=left.window_samples,
        fs_hz=left.fs_hz,
        label="x_corr",
        pct_masked=pct_masked,
    )
