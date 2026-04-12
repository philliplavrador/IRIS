"""pyqplot plot handlers for CASI — publication-quality PDF / PNG / SVG.

Selected via ``globals_cfg["plot_backend"] = "pyqplot"``. Renders each plot
to PDF + PNG inside the active session output directory using the qplot C++
backend (https://github.com/wagenadl/qplot).

Requirements:
    1. Install the optional extra:  ``pip install casi[publication]``
       (this installs the ``pyqplot`` Python wrapper)
    2. Install the C++ ``qplot`` binary and put it on your PATH:
       https://github.com/wagenadl/qplot/releases

Stage 1 (smoke test) is in ``docs/development/qplot_smoke_test.ipynb``. Stage 2
(this file) wires the 11 dataclass-specific handlers to the qplot API. The
mea_trace, spike_train, spectrogram, ca_trace, sim_calcium, freq_traces,
overlay, and saturation_report handlers are fully implemented; the more
visually-complex CorrelationResult plot uses a simplified two-panel layout.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np

from casi.engine import (
    CATrace,
    CorrelationResult,
    FreqPowerTraces,
    MEATrace,
    OpRegistry,
    PipelineContext,
    RTBank,
    RTTrace,
    SaturationReport,
    SimCalcium,
    SpikePCA,
    SpikeTrain,
    Spectrogram,
)
from casi.plot_backends._common import params_text_block

_qp = None
_plot_counter = [0]


def _ensure_qp():
    global _qp
    if _qp is not None:
        return _qp
    try:
        import qplot as qp
    except ImportError as e:
        raise ImportError(
            "pyqplot backend requires the 'pyqplot' Python package and the "
            "qplot C++ binary on PATH.\n"
            "Install:  pip install casi[publication]\n"
            "Binary:   https://github.com/wagenadl/qplot/releases"
        ) from e
    _qp = qp
    return qp


def _next_basename(ctx: PipelineContext, suffix: str) -> Path:
    """Build outputs/<session>/plot_NNN_<suffix> base path (no extension)."""
    out_dir = Path(ctx.output_dir or "outputs")
    out_dir.mkdir(parents=True, exist_ok=True)
    _plot_counter[0] += 1
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in suffix)[:80]
    return out_dir / f"plot_{_plot_counter[0]:03d}_{safe}"


def _save_both(qp, base: Path) -> tuple[Path, Path]:
    """Save current qplot figure to both PDF and PNG. Returns the (pdf, png) paths."""
    pdf = base.with_suffix(".pdf")
    png = base.with_suffix(".png")
    qp.save(str(pdf))
    qp.save(str(png))
    return pdf, png


def _stamp_params_footer(qp, ctx: PipelineContext) -> None:
    """Render the params block as a small footer underneath the figure."""
    if not ctx.show_ops_params or not ctx.current_expr:
        return
    text = params_text_block(ctx)
    if not text:
        return
    first_line = text.split("\n", 1)[0]
    qp.font('Helvetica', 7)
    qp.text(0.5, -0.18, first_line[:160], align='center')


def _time_axis_ms(window_samples, fs) -> np.ndarray:
    start, end = window_samples
    return np.arange(start, end) / fs * 1000


# ---------- Handlers ----------

def plot_mea_trace(result: MEATrace, ctx: PipelineContext, last_op) -> None:
    qp = _ensure_qp()
    ws = result.window_samples
    t = _time_axis_ms(ws, result.fs_hz)
    data = result.trimmed_data
    n = min(len(t), len(data))
    base = _next_basename(ctx, f"mea_trace_{result.channel_idx}_{result.label}")
    qp.figure(str(base), 10, 3)
    qp.pen('b')
    qp.plot(t[:n], data[:n])
    qp.xaxis('Time (ms)')
    qp.yaxis('Voltage (uV)')
    qp.title(f'MEA Electrode {result.channel_idx}: {result.label}')
    _stamp_params_footer(qp, ctx)
    _save_both(qp, base)


def plot_spike_train(result: SpikeTrain, ctx: PipelineContext, last_op) -> None:
    qp = _ensure_qp()
    ws = result.window_samples
    fs = result.fs_hz
    t = _time_axis_ms(ws, fs)
    n = min(len(t), len(result.source_signal))
    base = _next_basename(ctx, f"spike_train_{result.source_id}")
    qp.figure(str(base), 10, 3)
    qp.pen('b')
    qp.plot(t[:n], result.source_signal[:n])
    qp.legend('Filtered signal')
    qp.pen('r')
    qp.plot(t[:n], result.threshold_curve[:n])
    qp.legend('Threshold')
    spike_t = (result.spike_indices + ws[0]) / fs * 1000
    qp.pen('y')
    qp.brush('yyy')
    qp.marker('o', 4)
    qp.mark(spike_t, result.spike_values)
    qp.legend(f'Spikes (n={result.num_spikes})')
    qp.xaxis('Time (ms)')
    qp.yaxis('Amplitude')
    qp.title(f'Source {result.source_id}: {result.label} ({result.num_spikes} spikes)')
    _stamp_params_footer(qp, ctx)
    _save_both(qp, base)


def plot_spike_pca(result: SpikePCA, ctx: PipelineContext, last_op) -> None:
    qp = _ensure_qp()
    base = _next_basename(ctx, f"spike_pca_{result.source_id}")
    n_spikes = len(result.spike_indices)
    if n_spikes == 0 or len(result.pca_components) == 0:
        qp.figure(str(base), 6, 3)
        qp.text(0.5, 0.5, f'Too few spikes for PCA (n={n_spikes})', align='center')
        _save_both(qp, base)
        return

    inlier = ~result.outlier_mask
    proj = result.pca_projections
    var = result.explained_variance_ratio * 100

    qp.figure(str(base), 8, 8)
    qp.panel('A', [0.10, 0.10, 0.85, 0.38])
    if proj.shape[1] >= 2:
        qp.pen('b')
        qp.brush('44a')
        qp.marker('o', 3)
        qp.mark(proj[inlier, 0], proj[inlier, 1])
        if result.n_outliers > 0:
            qp.pen('r')
            qp.marker('x', 4)
            qp.mark(proj[result.outlier_mask, 0], proj[result.outlier_mask, 1])
        qp.pen('k')
        qp.marker('+', 6)
        qp.mark([float(result.centroid[0])], [float(result.centroid[1])])
    qp.xaxis(f'PC1 ({var[0]:.1f}%)')
    qp.yaxis(f'PC2 ({var[1]:.1f}%)')

    qp.panel('B', [0.10, 0.55, 0.85, 0.38])
    snippet_len = result.waveforms.shape[1]
    half = snippet_len // 2
    t_ms = np.arange(-half, half + 1) / result.fs_hz * 1000
    n_t = min(len(t_ms), result.waveforms.shape[1])
    if inlier.any():
        mean_wf = result.waveforms[inlier].mean(axis=0)
        qp.pen('k')
        qp.plot(t_ms[:n_t], mean_wf[:n_t])
        qp.legend('Mean waveform')
    qp.xaxis('Time (ms)')
    qp.yaxis('Amplitude (uV)')
    _stamp_params_footer(qp, ctx)
    _save_both(qp, base)


def plot_ca_trace(result: CATrace, ctx: PipelineContext, last_op) -> None:
    qp = _ensure_qp()
    ws = result.window_samples
    fs = result.fs_hz
    t = _time_axis_ms(ws, fs)
    n = min(len(t), len(result.data))
    base = _next_basename(ctx, f"ca_trace_{result.trace_idx}")

    if result.baseline is not None and result.original_data is not None:
        ca_frames = result.original_frames
        orig_interp = np.interp(np.arange(ws[0], ws[1]), ca_frames, result.original_data)
        qp.figure(str(base), 10, 6)
        qp.panel('A', [0.10, 0.10, 0.85, 0.38])
        qp.pen('m')
        qp.plot(t[:n], orig_interp[:n])
        qp.legend('Raw fluorescence')
        qp.pen('r')
        qp.plot(t[:n], result.baseline[:n])
        qp.legend('Baseline')
        qp.yaxis('Fluorescence')
        qp.title(f'Calcium ROI {result.trace_idx}: Baseline correction')

        qp.panel('B', [0.10, 0.55, 0.85, 0.38])
        qp.pen('m')
        qp.plot(t[:n], result.data[:n])
        qp.xaxis('Time (ms)')
        qp.yaxis('Corrected')
    else:
        qp.figure(str(base), 10, 3)
        qp.pen('m')
        qp.plot(t[:n], result.data[:n])
        qp.xaxis('Time (ms)')
        qp.yaxis('Fluorescence')
        qp.title(f'Calcium ROI {result.trace_idx}: {result.label}')
    _stamp_params_footer(qp, ctx)
    _save_both(qp, base)


def plot_rt_trace(result: RTTrace, ctx: PipelineContext, last_op) -> None:
    qp = _ensure_qp()
    ws = result.window_samples
    t = _time_axis_ms(ws, result.fs_hz)
    n = min(len(t), len(result.data))
    base = _next_basename(ctx, f"rt_trace_{result.channel_idx}_{result.label}")
    qp.figure(str(base), 10, 3)
    qp.pen('b')
    qp.plot(t[:n], result.data[:n])
    qp.xaxis('Time (ms)')
    qp.yaxis('Probability' if result.label == 'sigmoid' else 'Logit')
    qp.title(f'RTSort Channel {result.channel_idx}: {result.label}')
    _stamp_params_footer(qp, ctx)
    _save_both(qp, base)


def plot_rt_bank(result: RTBank, ctx: PipelineContext, last_op) -> None:
    qp = _ensure_qp()
    ws = result.window_samples
    t = _time_axis_ms(ws, result.fs_hz)
    show = min(5, result.traces.shape[0])
    base = _next_basename(ctx, f"rt_bank_{result.label}")
    qp.figure(str(base), 10, 2.5 * show)
    panel_h = 0.85 / show
    for i in range(show):
        y0 = 0.10 + (show - 1 - i) * panel_h
        qp.panel(chr(ord('A') + i), [0.10, y0, 0.85, panel_h * 0.85])
        n = min(len(t), len(result.traces[i]))
        qp.pen('b')
        qp.plot(t[:n], result.traces[i][:n])
        qp.yaxis(f'Ch {result.channel_ids[i]}')
        if i == show - 1:
            qp.xaxis('Time (ms)')
        if i == 0:
            qp.title(f'RTSort Bank ({result.traces.shape[0]} channels): {result.label}')
    _stamp_params_footer(qp, ctx)
    _save_both(qp, base)


def plot_sim_calcium(result: SimCalcium, ctx: PipelineContext, last_op) -> None:
    qp = _ensure_qp()
    ws = result.window_samples
    t = _time_axis_ms(ws, result.fs_hz)
    n = min(len(t), len(result.data))
    base = _next_basename(ctx, f"sim_calcium_{result.source_id}")
    qp.figure(str(base), 10, 3)
    qp.pen('g')
    qp.plot(t[:n], result.data[:n])
    qp.legend('Simulated GCaMP')
    qp.xaxis('Time (ms)')
    qp.yaxis('Simulated dF/F0')
    qp.title(f'Source {result.source_id}: simulated GCaMP')
    _stamp_params_footer(qp, ctx)
    _save_both(qp, base)


def plot_correlation(result: CorrelationResult, ctx: PipelineContext, last_op) -> None:
    qp = _ensure_qp()
    base = _next_basename(ctx, f"correlation_ca_{result.ca_trace_idx}")
    qp.figure(str(base), 8, 9)

    qp.panel('A', [0.10, 0.55, 0.85, 0.38])
    qp.pen('k')
    qp.brush('44a')
    qp.marker('o', 3)
    qp.mark(result.x_coords, result.y_coords)
    qp.pen('r')
    qp.brush('a44')
    qp.marker('o', 6)
    qp.mark([float(result.x_coords[result.best_idx])],
            [float(result.y_coords[result.best_idx])])
    qp.xaxis('Electrode X (um)')
    qp.yaxis('Electrode Y (um)')
    qp.title(f'Spatial map: Ca ROI {result.ca_trace_idx}')

    qp.panel('B', [0.10, 0.10, 0.85, 0.38])
    ws = result.window_samples
    t = _time_axis_ms(ws, result.fs_hz)
    min_len = min(len(result.ca_signal), len(result.best_sim_trace), len(t))
    qp.pen('m')
    qp.plot(t[:min_len], result.ca_signal[:min_len])
    qp.legend('Recorded Ca')
    qp.pen('g')
    qp.plot(t[:min_len], result.best_sim_trace[:min_len])
    qp.legend('Simulated GCaMP')
    qp.xaxis('Time (ms)')
    qp.yaxis('Signal')
    _stamp_params_footer(qp, ctx)
    _save_both(qp, base)


def plot_spectrogram(result: Spectrogram, ctx: PipelineContext, last_op) -> None:
    qp = _ensure_qp()
    base = _next_basename(ctx, f"spectrogram_{result.source_id}")
    qp.figure(str(base), 10, 5)
    qp.luts.set('viridis', 256)
    qp.imsc(result.power, c0=float(np.nanmin(result.power)),
            c1=float(np.nanmax(result.power)))
    qp.xaxis('Time (ms)')
    qp.yaxis('Frequency (Hz)')
    qp.cbar(width=10)
    qp.caxis()
    qp.title(f'MEA Electrode {result.source_id}: spectrogram')
    _stamp_params_footer(qp, ctx)
    _save_both(qp, base)


def plot_freq_traces(result: FreqPowerTraces, ctx: PipelineContext, last_op) -> None:
    qp = _ensure_qp()
    base = _next_basename(ctx, f"freq_traces_{result.source_id}")
    items = list(result.freq_traces.items())
    n_panels = len(items) + 1
    fig_h = 2 * n_panels
    qp.figure(str(base), 10, fig_h)
    panel_h = 0.85 / n_panels
    for i, (hz, power) in enumerate(items):
        y0 = 0.10 + (n_panels - 1 - i) * panel_h
        qp.panel(chr(ord('A') + i), [0.10, y0, 0.85, panel_h * 0.80])
        qp.pen('b')
        qp.plot(result.times, power)
        qp.yaxis(f'{hz:.0f} Hz')
        if i == 0:
            qp.title(f'MEA Electrode {result.source_id}: frequency power')
    qp.panel(chr(ord('A') + len(items)), [0.10, 0.10, 0.85, panel_h * 0.80])
    qp.pen('k')
    qp.plot(result.times, result.broadband_power)
    bb_low, bb_high = result.broadband_range_hz
    qp.yaxis(f'Broadband\n{bb_low:.0f}-{bb_high:.0f}')
    qp.xaxis('Time (ms)')
    _stamp_params_footer(qp, ctx)
    _save_both(qp, base)


def plot_saturation_report(result: SaturationReport, ctx: PipelineContext, last_op) -> None:
    qp = _ensure_qp()
    base = _next_basename(ctx, f"saturation_{result.plot_type}")
    counts = result.samples_masked
    n = len(counts)
    total = result.total_samples
    pct_masked = counts / total * 100 if total > 0 else np.zeros(n)

    qp.figure(str(base), 10, 5)
    if result.plot_type == "scatter":
        qp.luts.set('YlOrRd', 256)
        qp.pen('k')
        for i in range(n):
            qp.brush('a55')
            qp.marker('o', 4)
            qp.mark([float(result.locations[i, 0])], [float(result.locations[i, 1])])
        qp.xaxis('X (um)')
        qp.yaxis('Y (um)')
    elif result.plot_type == "survival":
        bins = np.arange(0, 101, 1)
        survival = np.array([np.sum(pct_masked >= t) for t in bins])
        qp.pen('b')
        qp.plot(bins, survival)
        qp.xaxis('% masked threshold')
        qp.yaxis('# electrodes')
    else:
        qp.pen('b')
        qp.plot(np.arange(n), counts)
        qp.xaxis('Channel index')
        qp.yaxis('Samples masked')
    qp.title(f'Saturation Survey ({n} electrodes)')
    _stamp_params_footer(qp, ctx)
    _save_both(qp, base)


def plot_overlay(results, labels, ctx: PipelineContext) -> None:
    qp = _ensure_qp()
    ws = ctx.window_samples_mea
    fs = ctx.mea_fs_hz
    t = _time_axis_ms(ws, fs)
    base = _next_basename(ctx, "overlay")
    qp.figure(str(base), 10, 3)
    pens = ['b', 'r', 'g', 'm', '0a0', 'a00']
    for i, (result, label) in enumerate(zip(results, labels)):
        if hasattr(result, 'trimmed_data'):
            data = result.trimmed_data
        elif hasattr(result, 'data'):
            data = result.data
        elif isinstance(result, SpikeTrain):
            data = result.source_signal
        else:
            continue
        n = min(len(t), len(data))
        d = data[:n].astype(float)
        d_range = d.max() - d.min()
        d_norm = (d - d.min()) / (d_range + 1e-10) if d_range > 0 else d
        qp.pen(pens[i % len(pens)])
        qp.plot(t[:n], d_norm)
        qp.legend(label)
    qp.xaxis('Time (ms)')
    qp.yaxis('Normalized')
    qp.title('Overlay')
    _stamp_params_footer(qp, ctx)
    _save_both(qp, base)


def register(registry: OpRegistry) -> None:
    """Register all pyqplot plot handlers + the overlay handler."""
    registry.register_plot(MEATrace,          plot_mea_trace)
    registry.register_plot(SpikeTrain,        plot_spike_train)
    registry.register_plot(SpikePCA,          plot_spike_pca)
    registry.register_plot(CATrace,           plot_ca_trace)
    registry.register_plot(RTTrace,           plot_rt_trace)
    registry.register_plot(RTBank,            plot_rt_bank)
    registry.register_plot(SimCalcium,        plot_sim_calcium)
    registry.register_plot(CorrelationResult, plot_correlation)
    registry.register_plot(Spectrogram,       plot_spectrogram)
    registry.register_plot(FreqPowerTraces,   plot_freq_traces)
    registry.register_plot(SaturationReport,  plot_saturation_report)
    registry.register_overlay_plot(plot_overlay)
