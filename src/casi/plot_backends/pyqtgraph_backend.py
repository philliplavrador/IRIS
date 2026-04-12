"""pyqtgraph plot handlers for CASI — live desktop GUI.

Selected via ``globals_cfg["plot_backend"] = "pyqtgraph"``. Each handler opens
a standalone Qt window (or reuses the one from a sibling handler in the same
process) and renders interactively. Suitable for exploration of long
recordings where matplotlib's static figures are too sluggish to pan.

Requires the ``pyqtgraph`` and ``PyQt6`` dependencies (both core deps in
pyproject.toml). The application loop is started in non-blocking mode so
multiple plots can co-exist within a single pipeline run; call
``run_event_loop()`` from a script if you need to keep the windows alive
after the script ends.
"""
from __future__ import annotations

import sys
from typing import Any, Optional

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

_app: Optional[Any] = None
_open_windows: list = []  # keep references so windows aren't garbage-collected


def _ensure_app():
    """Lazy-import pyqtgraph + PyQt6 and ensure a QApplication exists."""
    global _app
    try:
        import pyqtgraph as pg
        from PyQt6 import QtWidgets
    except ImportError as e:
        raise ImportError(
            "pyqtgraph backend requires pyqtgraph and PyQt6.\n"
            "Install with: pip install pyqtgraph PyQt6"
        ) from e

    pg.setConfigOptions(antialias=True, background='w', foreground='k')

    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication(sys.argv if sys.argv else [""])
    _app = app
    return pg, QtWidgets, app


def _new_window(title: str, ctx: PipelineContext, width: int = 1400, height: int = 600):
    """Create and show a GraphicsLayoutWidget. Returns (win, central_layout)."""
    pg, QtWidgets, app = _ensure_app()
    win = pg.GraphicsLayoutWidget(show=True, title=title)
    win.resize(width, height)
    _open_windows.append(win)

    if ctx.show_ops_params and ctx.current_expr:
        params_text = params_text_block(ctx)
        win.setWindowTitle(f"{title}  —  {ctx.current_expr.source.source_type}")
    return win


def _add_params_label(win, ctx: PipelineContext) -> None:
    """Append a text row at the bottom of the layout with the params block."""
    if not ctx.show_ops_params or not ctx.current_expr:
        return
    pg, QtWidgets, app = _ensure_app()
    win.nextRow()
    text = params_text_block(ctx)
    label = pg.LabelItem(text, color='k', size='8pt', justify='left')
    win.addItem(label, colspan=10)


def _time_axis_ms(window_samples, fs) -> np.ndarray:
    start, end = window_samples
    return np.arange(start, end) / fs * 1000


def _window_suffix(window_samples, fs) -> str:
    start, end = window_samples
    return f" [{start/fs*1000:.1f} - {end/fs*1000:.1f} ms]"


# ---------- Handlers ----------

def plot_mea_trace(result: MEATrace, ctx: PipelineContext, last_op) -> None:
    pg, QtWidgets, app = _ensure_app()
    ws = result.window_samples
    t = _time_axis_ms(ws, result.fs_hz)
    data = result.trimmed_data
    if len(data) > len(t):
        data = data[:len(t)]
    elif len(t) > len(data):
        t = t[:len(data)]

    title = f"MEA Electrode {result.channel_idx}: {result.label}{_window_suffix(ws, result.fs_hz)}"
    win = _new_window(title, ctx)
    plot = win.addPlot(title=title)
    plot.plot(t, data, pen=pg.mkPen('b', width=1))
    plot.setLabel('bottom', 'Time (ms)')
    plot.setLabel('left', 'Voltage (µV)')
    plot.showGrid(x=True, y=True, alpha=0.3)
    _add_params_label(win, ctx)
    app.processEvents()


def plot_spike_train(result: SpikeTrain, ctx: PipelineContext, last_op) -> None:
    pg, QtWidgets, app = _ensure_app()
    ws = result.window_samples
    fs = result.fs_hz
    t = _time_axis_ms(ws, fs)
    start_sample = ws[0]

    title = (f"Source {result.source_id}: {result.label} "
             f"({result.num_spikes} spikes){_window_suffix(ws, fs)}")
    win = _new_window(title, ctx)
    plot = win.addPlot(title=title)
    plot.addLegend()
    plot.plot(t, result.source_signal, pen=pg.mkPen('b', width=1), name='Filtered signal')
    plot.plot(t, result.threshold_curve, pen=pg.mkPen('r', width=1), name='Threshold')
    spike_t = (result.spike_indices + start_sample) / fs * 1000
    plot.plot(spike_t, result.spike_values, pen=None,
              symbol='o', symbolBrush='y', symbolPen='k', symbolSize=8,
              name=f'Spikes (n={result.num_spikes})')
    plot.setLabel('bottom', 'Time (ms)')
    plot.setLabel('left', 'Amplitude')
    plot.showGrid(x=True, y=True, alpha=0.3)
    _add_params_label(win, ctx)
    app.processEvents()


def plot_spike_pca(result: SpikePCA, ctx: PipelineContext, last_op) -> None:
    pg, QtWidgets, app = _ensure_app()
    n_spikes = len(result.spike_indices)
    title = f"Source {result.source_id}: PCA waveform space (n={n_spikes})"

    win = _new_window(title, ctx, width=1000, height=900)
    if len(result.pca_components) == 0 or n_spikes == 0:
        plot = win.addPlot(title=title)
        text = pg.TextItem(f"Too few spikes for PCA (n={n_spikes})",
                           color='k', anchor=(0.5, 0.5))
        plot.addItem(text)
        _add_params_label(win, ctx)
        app.processEvents()
        return

    inlier = ~result.outlier_mask
    proj = result.pca_projections
    var = result.explained_variance_ratio * 100

    pca_plot = win.addPlot(title=title)
    pca_plot.addLegend()
    if proj.shape[1] >= 2:
        pca_plot.plot(proj[inlier, 0], proj[inlier, 1], pen=None,
                      symbol='o', symbolSize=6, symbolBrush=(80, 80, 200, 150),
                      name='Inlier')
        if result.n_outliers > 0:
            pca_plot.plot(proj[result.outlier_mask, 0], proj[result.outlier_mask, 1],
                          pen=None, symbol='x', symbolSize=10, symbolBrush='r',
                          name=f'Outliers (n={result.n_outliers})')
        pca_plot.plot([result.centroid[0]], [result.centroid[1]],
                      pen=None, symbol='star', symbolSize=20, symbolBrush='k',
                      name='Centroid')
        pca_plot.setLabel('bottom', f'PC1 ({var[0]:.1f}% var)')
        pca_plot.setLabel('left', f'PC2 ({var[1]:.1f}% var)')
    pca_plot.showGrid(x=True, y=True, alpha=0.3)

    win.nextRow()
    snippet_len = result.waveforms.shape[1]
    half = snippet_len // 2
    t_ms = np.arange(-half, half + 1) / result.fs_hz * 1000
    wf_plot = win.addPlot(title=f"Waveforms ({n_spikes} total, {result.n_outliers} outliers)")
    if inlier.any():
        for wf in result.waveforms[inlier]:
            wf_plot.plot(t_ms[:len(wf)], wf, pen=pg.mkPen((128, 128, 128, 40), width=1))
        mean_wf = result.waveforms[inlier].mean(axis=0)
        wf_plot.plot(t_ms[:len(mean_wf)], mean_wf, pen=pg.mkPen('k', width=2))
    if result.n_outliers > 0:
        for wf in result.waveforms[result.outlier_mask]:
            wf_plot.plot(t_ms[:len(wf)], wf, pen=pg.mkPen((255, 0, 0, 100), width=1))
    wf_plot.setLabel('bottom', 'Time (ms)')
    wf_plot.setLabel('left', 'Amplitude (µV)')
    wf_plot.showGrid(x=True, y=True, alpha=0.3)

    _add_params_label(win, ctx)
    app.processEvents()


def plot_ca_trace(result: CATrace, ctx: PipelineContext, last_op) -> None:
    pg, QtWidgets, app = _ensure_app()
    ws = result.window_samples
    fs = result.fs_hz
    t = _time_axis_ms(ws, fs)

    title = f"Calcium ROI {result.trace_idx}: {result.label}"
    win = _new_window(title, ctx, width=1200, height=600)

    if result.baseline is not None and result.original_data is not None:
        ca_frames = result.original_frames
        orig_interp = np.interp(np.arange(ws[0], ws[1]), ca_frames, result.original_data)
        p1 = win.addPlot(title=f"Calcium ROI {result.trace_idx}: Baseline correction")
        p1.addLegend()
        p1.plot(t, orig_interp, pen=pg.mkPen('m', width=1), name='Raw fluorescence')
        p1.plot(t, result.baseline, pen=pg.mkPen('r', width=1, style=2), name='Baseline')
        p1.setLabel('left', 'Fluorescence')
        p1.showGrid(x=True, y=True, alpha=0.3)
        win.nextRow()
        p2 = win.addPlot()
        p2.addLegend()
        p2.plot(t, result.data, pen=pg.mkPen('m', width=1), name='Baseline-corrected')
        p2.setLabel('bottom', 'Time (ms)')
        p2.setLabel('left', 'Corrected fluorescence')
        p2.showGrid(x=True, y=True, alpha=0.3)
        p2.setXLink(p1)
    else:
        p = win.addPlot(title=title)
        p.plot(t, result.data, pen=pg.mkPen('m', width=1))
        p.setLabel('bottom', 'Time (ms)')
        p.setLabel('left', 'Fluorescence')
        p.showGrid(x=True, y=True, alpha=0.3)

    _add_params_label(win, ctx)
    app.processEvents()


def plot_rt_trace(result: RTTrace, ctx: PipelineContext, last_op) -> None:
    pg, QtWidgets, app = _ensure_app()
    ws = result.window_samples
    t = _time_axis_ms(ws, result.fs_hz)
    ylabel = 'Probability' if result.label == 'sigmoid' else 'Logit'
    title = f"RTSort Channel {result.channel_idx}: {result.label}{_window_suffix(ws, result.fs_hz)}"
    win = _new_window(title, ctx)
    p = win.addPlot(title=title)
    p.plot(t, result.data, pen=pg.mkPen('b', width=1))
    p.setLabel('bottom', 'Time (ms)')
    p.setLabel('left', ylabel)
    p.showGrid(x=True, y=True, alpha=0.3)
    _add_params_label(win, ctx)
    app.processEvents()


def plot_rt_bank(result: RTBank, ctx: PipelineContext, last_op) -> None:
    pg, QtWidgets, app = _ensure_app()
    ws = result.window_samples
    t = _time_axis_ms(ws, result.fs_hz)
    n_ch = result.traces.shape[0]
    show = min(5, n_ch)
    ylabel = 'Probability' if result.label == 'sigmoid' else 'Logit'
    title = f"RTSort Bank ({n_ch} channels): {result.label}{_window_suffix(ws, result.fs_hz)}"
    win = _new_window(title, ctx, height=2000)
    first_plot = None
    for i in range(show):
        if i > 0:
            win.nextRow()
        p = win.addPlot()
        p.plot(t, result.traces[i], pen=pg.mkPen('b', width=1))
        p.setLabel('left', f'Ch {result.channel_ids[i]}\n{ylabel}')
        p.showGrid(x=True, y=True, alpha=0.3)
        if first_plot is None:
            first_plot = p
            p.setTitle(title)
        else:
            p.setXLink(first_plot)
        if i == show - 1:
            p.setLabel('bottom', 'Time (ms)')
    _add_params_label(win, ctx)
    app.processEvents()


def plot_sim_calcium(result: SimCalcium, ctx: PipelineContext, last_op) -> None:
    pg, QtWidgets, app = _ensure_app()
    ws = result.window_samples
    t = _time_axis_ms(ws, result.fs_hz)
    title = f"Source {result.source_id}: simulated GCaMP{_window_suffix(ws, result.fs_hz)}"
    win = _new_window(title, ctx)
    p = win.addPlot(title=title)
    p.plot(t, result.data, pen=pg.mkPen('g', width=1))
    if len(result.spike_indices) > 0:
        spike_t = t[result.spike_indices[result.spike_indices < len(t)]]
        spike_y = result.data[result.spike_indices[result.spike_indices < len(result.data)]]
        p.plot(spike_t, spike_y, pen=None, symbol='|', symbolSize=14, symbolBrush='k')
    p.setLabel('bottom', 'Time (ms)')
    p.setLabel('left', 'Simulated dF/F0')
    p.showGrid(x=True, y=True, alpha=0.3)
    _add_params_label(win, ctx)
    app.processEvents()


def plot_correlation(result: CorrelationResult, ctx: PipelineContext, last_op) -> None:
    pg, QtWidgets, app = _ensure_app()
    title = f"Spatial correlation map: Ca ROI {result.ca_trace_idx}"
    win = _new_window(title, ctx, width=900, height=900)

    p = win.addPlot(title=title)
    vmax = float(np.max(np.abs(result.correlations)))
    if result.pct_masked is not None:
        frac_clean = np.clip(1 - result.pct_masked / 100, 0, 1)
        sizes = 6 + 18 * frac_clean ** 2
    else:
        sizes = np.full_like(result.correlations, 14, dtype=float)

    cmap = pg.colormap.get('CET-D1')
    norm = (result.correlations + vmax) / (2 * vmax + 1e-12)
    colors = [cmap.map(float(v), mode='qcolor') for v in norm]

    spots = [
        {
            'pos': (float(result.x_coords[i]), float(result.y_coords[i])),
            'size': float(sizes[i]) if hasattr(sizes, '__len__') else float(sizes),
            'brush': colors[i],
            'pen': pg.mkPen('k', width=0.5),
        }
        for i in range(len(result.correlations))
    ]
    sp = pg.ScatterPlotItem()
    sp.addPoints(spots)
    p.addItem(sp)

    best = result.best_idx
    p.plot([float(result.x_coords[best])], [float(result.y_coords[best])],
           pen=None, symbol='star', symbolSize=24, symbolBrush='y',
           symbolPen=pg.mkPen('k', width=1.5))
    p.setLabel('bottom', 'Electrode X (µm)')
    p.setLabel('left', 'Electrode Y (µm)')
    p.setAspectLocked(True)
    p.showGrid(x=True, y=True, alpha=0.2)

    win.nextRow()
    ws = result.window_samples
    t = _time_axis_ms(ws, result.fs_hz)
    min_len = min(len(result.ca_signal), len(result.best_sim_trace), len(t))
    overlay = win.addPlot(title=f"Best match: electrode {result.electrode_info[best]['channel']} "
                                f"r={result.best_corr:.4f}")
    overlay.addLegend()
    overlay.plot(t[:min_len], result.ca_signal[:min_len],
                 pen=pg.mkPen('m', width=1), name='Recorded Ca')
    overlay.plot(t[:min_len], result.best_sim_trace[:min_len],
                 pen=pg.mkPen('g', width=1), name='Simulated GCaMP')
    overlay.setLabel('bottom', 'Time (ms)')
    overlay.showGrid(x=True, y=True, alpha=0.3)

    _add_params_label(win, ctx)
    app.processEvents()


def plot_spectrogram(result: Spectrogram, ctx: PipelineContext, last_op) -> None:
    pg, QtWidgets, app = _ensure_app()
    title = f"MEA Electrode {result.source_id}: spectrogram{_window_suffix(result.window_samples, result.fs_hz)}"
    win = _new_window(title, ctx, width=1400, height=700)
    p = win.addPlot(title=title)

    img = pg.ImageItem()
    img.setImage(result.power.T)
    nf = result.power.shape[0]
    nt = result.power.shape[1]
    if nt > 1 and nf > 1:
        x_scale = (result.times[-1] - result.times[0]) / (nt - 1)
        y_scale = (result.frequencies[-1] - result.frequencies[0]) / (nf - 1)
        img.setRect(pg.QtCore.QRectF(
            float(result.times[0]), float(result.frequencies[0]),
            float(x_scale * nt), float(y_scale * nf),
        ))
    cmap = pg.colormap.get('viridis')
    img.setLookupTable(cmap.getLookupTable(0.0, 1.0, 256))
    p.addItem(img)

    p.setLabel('bottom', 'Time (ms)')
    p.setLabel('left', 'Frequency (Hz)')
    p.showGrid(x=True, y=True, alpha=0.3)

    _add_params_label(win, ctx)
    app.processEvents()


def plot_freq_traces(result: FreqPowerTraces, ctx: PipelineContext, last_op) -> None:
    pg, QtWidgets, app = _ensure_app()
    title = f"MEA Electrode {result.source_id}: frequency power traces"
    win = _new_window(title, ctx, width=1400, height=200 + 150 * (len(result.freq_traces) + 1))

    first_plot = None
    colors = [(31, 119, 180), (255, 127, 14), (44, 160, 44),
              (214, 39, 40), (148, 103, 189), (140, 86, 75)]
    items = list(result.freq_traces.items())
    for i, (hz, power) in enumerate(items):
        if i > 0:
            win.nextRow()
        p = win.addPlot()
        p.plot(result.times, power, pen=pg.mkPen(colors[i % len(colors)], width=1))
        p.setLabel('left', f'{hz:.0f} Hz\nPower')
        p.showGrid(x=True, y=True, alpha=0.3)
        if first_plot is None:
            first_plot = p
            p.setTitle(title)
        else:
            p.setXLink(first_plot)

    win.nextRow()
    bb = win.addPlot()
    bb.plot(result.times, result.broadband_power, pen=pg.mkPen('k', width=1))
    bb_low, bb_high = result.broadband_range_hz
    bb.setLabel('left', f'Broadband\n{bb_low:.0f}-{bb_high:.0f} Hz')
    bb.setLabel('bottom', 'Time (ms)')
    bb.showGrid(x=True, y=True, alpha=0.3)
    if first_plot is not None:
        bb.setXLink(first_plot)

    _add_params_label(win, ctx)
    app.processEvents()


def plot_saturation_report(result: SaturationReport, ctx: PipelineContext, last_op) -> None:
    pg, QtWidgets, app = _ensure_app()
    counts = result.samples_masked
    n = len(counts)
    total = result.total_samples
    pct_masked = counts / total * 100 if total > 0 else np.zeros(n)

    ws = result.window_samples
    title = (
        f"Saturation Survey: {n} electrodes "
        f"[{ws[0]/result.fs_hz*1000:.0f}-{ws[1]/result.fs_hz*1000:.0f} ms]"
    )
    win = _new_window(title, ctx, width=1100, height=700)
    p = win.addPlot(title=title)

    if result.plot_type == "scatter":
        locs = result.locations
        cmap = pg.colormap.get('inferno')
        norm = pct_masked / max(pct_masked.max(), 1.0)
        spots = [
            {
                'pos': (float(locs[i, 0]), float(locs[i, 1])),
                'size': 12,
                'brush': cmap.map(float(norm[i]), mode='qcolor'),
                'pen': pg.mkPen('k', width=0.5),
            }
            for i in range(n)
        ]
        sp = pg.ScatterPlotItem()
        sp.addPoints(spots)
        p.addItem(sp)
        p.setLabel('bottom', 'X (µm)')
        p.setLabel('left', 'Y (µm)')
        p.setAspectLocked(True)
    elif result.plot_type == "survival":
        bins = np.arange(0, 101, 1)
        survival = np.array([np.sum(pct_masked >= t) for t in bins])
        p.plot(bins, survival, pen=pg.mkPen((70, 130, 180), width=2))
        p.setLabel('bottom', '% of window masked (threshold)')
        p.setLabel('left', '# electrodes ≥ threshold')
    else:
        bg = pg.BarGraphItem(x=np.arange(n), height=counts, width=1.0,
                             brush=(70, 130, 180))
        p.addItem(bg)
        p.setLabel('bottom', 'Channel index')
        p.setLabel('left', 'Samples masked')

    p.showGrid(x=True, y=True, alpha=0.3)
    _add_params_label(win, ctx)
    app.processEvents()


def plot_overlay(results, labels, ctx: PipelineContext) -> None:
    pg, QtWidgets, app = _ensure_app()
    ws = ctx.window_samples_mea
    fs = ctx.mea_fs_hz
    t = _time_axis_ms(ws, fs)
    title = f"Overlay (normalized){_window_suffix(ws, fs)}"
    win = _new_window(title, ctx)
    p = win.addPlot(title=title)
    p.addLegend()
    colors = [(31, 119, 180), (214, 39, 40), (44, 160, 44),
              (148, 103, 189), (255, 127, 14), (23, 190, 207)]
    for i, (result, label) in enumerate(zip(results, labels)):
        if hasattr(result, 'trimmed_data'):
            data = result.trimmed_data
        elif hasattr(result, 'data'):
            data = result.data
        elif isinstance(result, SpikeTrain):
            data = result.source_signal
        else:
            continue
        min_len = min(len(data), len(t))
        d = data[:min_len].astype(float)
        d_range = d.max() - d.min()
        d_norm = (d - d.min()) / (d_range + 1e-10) if d_range > 0 else d
        p.plot(t[:min_len], d_norm, pen=pg.mkPen(colors[i % len(colors)], width=1),
               name=label)
    p.setLabel('bottom', 'Time (ms)')
    p.setLabel('left', 'Normalized')
    p.showGrid(x=True, y=True, alpha=0.3)
    _add_params_label(win, ctx)
    app.processEvents()


def run_event_loop() -> None:
    """Block until all open pyqtgraph windows are closed.

    Call from a script (not a notebook) when you want the windows to remain
    interactive after the pipeline finishes. In Jupyter, ``%gui qt`` enables
    interactive non-blocking mode automatically.
    """
    if _app is not None:
        _app.exec()


def register(registry: OpRegistry) -> None:
    """Register all pyqtgraph plot handlers + the overlay handler."""
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
