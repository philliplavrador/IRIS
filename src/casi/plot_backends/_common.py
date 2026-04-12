"""Shared helpers used by every plot backend.

These functions are extracted verbatim from the original engine.py "PLOT
UTILITIES" section so the matplotlib and pyqtgraph backends can both render
the same parameter panel and time-axis labels.
"""
from __future__ import annotations

from typing import Tuple

import matplotlib.pyplot as plt
import numpy as np

from casi.engine import PipelineContext


def _show_params_panel(ctx: PipelineContext) -> None:
    """Embed operation parameters panel into the current figure's bottom margin."""
    if not ctx.show_ops_params or not ctx.current_expr:
        return

    source_type_names = {
        'mea_trace': 'Raw MEA trace',
        'ca_trace':  'Calcium trace (ROI',
        'rtsort':    'RTSort output',
    }
    op_names = {
        'butter_bandpass':    'Butterworth Bandpass Filter',
        'notch_filter':       'Notch Filter',
        'sliding_rms':        'Sliding RMS Spike Detection',
        'constant_rms':       'Constant RMS Spike Detection',
        'baseline_correction':'Baseline Correction',
        'sigmoid':            'Sigmoid Transform',
        'rt_thresh':          'RT Threshold Detection',
        'rt_detect':          'RT Detection (CNN)',
        'gcamp_sim':          'GCaMP Simulation',
        'x_corr':             'Cross-Correlation',
        'spectrogram':        'Spectrogram',
        'freq_traces':        'Frequency Power Traces',
        'spike_pca':          'PCA Waveform Outlier Detection',
        'spike_curate':       'Spike Train Curation',
    }

    expr = ctx.current_expr
    source_type = expr.source.source_type
    source_id = expr.source.source_id

    if source_type == 'ca_trace':
        source_desc = f"{source_type_names[source_type]}: {source_id})"
    else:
        source_desc = f"{source_type_names.get(source_type, source_type)} (channel_id: {source_id})"

    start_ms, end_ms = ctx.window_ms
    lines = [
        "Data Processing Pipeline",
        "",
        "Initial Data:",
        f"{source_desc} over window: [{start_ms:.2f}, {end_ms:.2f}] ms",
        "",
        "Operations:",
    ]

    if not expr.ops:
        lines.append("None")
    else:
        for i, op_node in enumerate(expr.ops, 1):
            op_display_name = op_names.get(op_node.op_name, op_node.op_name)
            merged_params = {
                **ctx.ops_cfg.get(op_node.op_name, {}),
                **op_node.kwargs_overrides,
            }
            lines.append(f"{i}. {op_display_name}")
            for key, value in merged_params.items():
                lines.append(f"    {key} = {repr(value)}")

    param_text = "\n".join(lines)
    num_lines = len(lines)

    fig = plt.gcf()
    w, h = fig.get_size_inches()
    panel_h = min(max(1.5, num_lines * 0.22), 6)
    pad_below = 0.3
    new_h = h + panel_h + pad_below
    fig.set_size_inches(w, new_h)

    bottom_frac = (panel_h + pad_below) / new_h
    fig.tight_layout(rect=[0, bottom_frac, 1, 1])

    fig.text(0.05, bottom_frac - 0.01, param_text, fontsize=9,
             verticalalignment="top", family="monospace",
             bbox=dict(boxstyle="round", facecolor="lightyellow",
                       alpha=0.9, pad=1.0, edgecolor="gray", linewidth=1))


def _time_axis_ms(window_samples: Tuple[int, int], fs: float) -> np.ndarray:
    start, end = window_samples
    return np.arange(start, end) / fs * 1000


def _window_suffix(window_samples: Tuple[int, int], fs: float) -> str:
    start, end = window_samples
    s_ms, e_ms = start / fs * 1000, end / fs * 1000
    return f" [{s_ms:.1f} - {e_ms:.1f} ms]"


def params_text_block(ctx: PipelineContext) -> str:
    """Plain-text version of the params panel for non-matplotlib backends.

    Used by pyqtgraph (overlay) and pyqplot (sidecar / footer text).
    """
    if not ctx.show_ops_params or not ctx.current_expr:
        return ""

    expr = ctx.current_expr
    lines = [
        f"Source: {expr.source.source_type}({expr.source.source_id})",
        f"Window: [{ctx.window_ms[0]:.2f}, {ctx.window_ms[1]:.2f}] ms",
        "Operations:",
    ]
    if not expr.ops:
        lines.append("  (none)")
    else:
        for i, op_node in enumerate(expr.ops, 1):
            merged = {**ctx.ops_cfg.get(op_node.op_name, {}), **op_node.kwargs_overrides}
            lines.append(f"  {i}. {op_node.op_name}")
            for key, value in merged.items():
                lines.append(f"      {key} = {value!r}")
    return "\n".join(lines)
