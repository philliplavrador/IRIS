"""Matplotlib plot handlers for CASI.

Handlers are moved verbatim from the original ``engine.py`` "PLOT HANDLERS"
section. Behavior is unchanged from the legacy pipeline. Selected via
``globals_cfg["plot_backend"] = "matplotlib"`` (default) or ``"matplotlib_widget"``.
"""
from __future__ import annotations

import matplotlib.pyplot as plt
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
from casi.plot_backends._common import (
    _show_params_panel,
    _time_axis_ms,
    _window_suffix,
)


def plot_mea_trace(result: MEATrace, ctx: PipelineContext, last_op) -> None:
    """Auto-plot for MEATrace (raw or filtered)."""
    ws = result.window_samples
    fs = result.fs_hz
    t = _time_axis_ms(ws, fs)
    data = result.trimmed_data

    print(f"  [plot_mea_trace] t.shape={t.shape}, data.shape={data.shape}, "
          f"nan_count={np.sum(np.isnan(data))}, label={result.label}")

    label_map = {
        "raw":             "Raw Extracellular Recording",
        "bandpass":        "Butterworth Bandpass Filtered",
        "notch":           "Notch Filtered",
        "saturation_mask": "Saturation Masked",
    }
    title_desc = label_map.get(result.label, result.label)

    fig, ax = plt.subplots(1, 1, figsize=(15, 4))
    ax.plot(t, data, linewidth=0.5, color='blue')
    ax.set_xlabel('Time (ms)')
    ax.set_ylabel('Voltage (\u03bcV)')
    ax.set_title(f'MEA Electrode {result.channel_idx}: {title_desc}' + _window_suffix(ws, fs))
    ax.grid(True, alpha=0.3)
    ax.margins(x=0)
    fig.tight_layout()
    _show_params_panel(ctx)
    plt.show()


def plot_spike_train(result: SpikeTrain, ctx: PipelineContext, last_op) -> None:
    """Auto-plot for SpikeTrain (signal + threshold + spike markers)."""
    ws = result.window_samples
    fs = result.fs_hz
    t = _time_axis_ms(ws, fs)
    start_sample = ws[0]

    mode_map = {
        "sliding_rms":  "Adaptive",
        "constant_rms": "Constant",
        "rt_thresh":    "RT Threshold",
    }
    mode_label = mode_map.get(result.label, result.label)

    plt.figure(figsize=(15, 4))
    plt.plot(t, result.source_signal, linewidth=0.5, color='blue', label='Filtered signal')
    plt.plot(t, result.threshold_curve, linewidth=0.5, color='red',
             label=f'Detection threshold ({mode_label.lower()})')

    spike_t = (result.spike_indices + start_sample) / fs * 1000
    plt.scatter(spike_t, result.spike_values, color='yellow', marker='o',
                s=30, edgecolors='black', linewidths=0.5, zorder=5,
                label=f'Detected spikes (n={result.num_spikes})')

    plt.xlabel('Time (ms)')
    plt.ylabel('Amplitude')
    plt.title(f'Source {result.source_id}: {mode_label} Thresholding ({result.num_spikes} spikes)'
              + _window_suffix(ws, fs))
    plt.legend(loc='upper right')
    plt.grid(True, alpha=0.3)
    plt.gca().margins(x=0)
    plt.tight_layout()
    _show_params_panel(ctx)
    plt.show()


def plot_spike_pca(result: SpikePCA, ctx: PipelineContext, last_op) -> None:
    """Auto-plot for SpikePCA (PCA scatter + waveform overlay)."""
    n_spikes = len(result.spike_indices)

    if len(result.pca_components) == 0 or n_spikes == 0:
        plt.figure(figsize=(8, 4))
        plt.text(0.5, 0.5, f"Too few spikes for PCA (n={n_spikes})",
                 ha='center', va='center', fontsize=14, transform=plt.gca().transAxes)
        plt.title(f'Source {result.source_id}: PCA Waveform Space'
                  + _window_suffix(result.window_samples, result.fs_hz))
        plt.axis('off')
        plt.tight_layout()
        _show_params_panel(ctx)
        plt.show()
        return

    inlier = ~result.outlier_mask
    proj = result.pca_projections
    var = result.explained_variance_ratio * 100

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 10))

    if proj.shape[1] >= 2:
        sc = ax1.scatter(proj[inlier, 0], proj[inlier, 1],
                         c=result.distances[inlier], cmap='viridis',
                         s=20, alpha=0.7, edgecolors='none')
        fig.colorbar(sc, ax=ax1, label='Distance from centroid')
        if result.n_outliers > 0:
            ax1.scatter(proj[result.outlier_mask, 0], proj[result.outlier_mask, 1],
                        c='red', marker='x', s=50, linewidths=1.5, zorder=5,
                        label=f'Outliers (n={result.n_outliers})')
        ax1.scatter(result.centroid[0], result.centroid[1],
                    c='black', marker='*', s=200, zorder=6, label='Centroid')
        ax1.set_xlabel(f'PC1 ({var[0]:.1f}% var)')
        ax1.set_ylabel(f'PC2 ({var[1]:.1f}% var)')
    else:
        ax1.scatter(proj[inlier, 0], np.zeros(inlier.sum()),
                    c=result.distances[inlier], cmap='viridis',
                    s=20, alpha=0.7, edgecolors='none')
        if result.n_outliers > 0:
            ax1.scatter(proj[result.outlier_mask, 0],
                        np.zeros(result.n_outliers),
                        c='red', marker='x', s=50, linewidths=1.5, zorder=5,
                        label=f'Outliers (n={result.n_outliers})')
        ax1.set_xlabel(f'PC1 ({var[0]:.1f}% var)')
        ax1.set_ylabel('')
    ax1.set_title(f'Source {result.source_id}: PCA Waveform Space'
                  + _window_suffix(result.window_samples, result.fs_hz))
    ax1.legend(loc='upper right')
    ax1.grid(True, alpha=0.3)

    snippet_len = result.waveforms.shape[1]
    half = snippet_len // 2
    t_ms = np.arange(-half, half + 1) / result.fs_hz * 1000

    if inlier.any():
        ax2.plot(t_ms, result.waveforms[inlier].T,
                 color='gray', alpha=0.15, linewidth=0.5)
    if result.n_outliers > 0:
        ax2.plot(t_ms, result.waveforms[result.outlier_mask].T,
                 color='red', alpha=0.4, linewidth=0.5)
    if inlier.any():
        mean_wf = result.waveforms[inlier].mean(axis=0)
        ax2.plot(t_ms, mean_wf, color='black', linewidth=2, label='Mean waveform')
    ax2.plot([], [], color='gray', linewidth=1, label='Inlier')
    if result.n_outliers > 0:
        ax2.plot([], [], color='red', linewidth=1, label='Outlier')
    ax2.set_xlabel('Time (ms)')
    ax2.set_ylabel('Amplitude (µV)')
    ax2.set_title(f'Spike Waveforms ({n_spikes} total, {result.n_outliers} outliers)')
    ax2.legend(loc='upper right')
    ax2.grid(True, alpha=0.3)

    fig.tight_layout()
    _show_params_panel(ctx)
    plt.show()


def plot_ca_trace(result: CATrace, ctx: PipelineContext, last_op) -> None:
    """Auto-plot for CATrace (with baseline correction if available)."""
    ws = result.window_samples
    fs = result.fs_hz

    if result.baseline is not None and result.original_data is not None:
        ca_frames = result.original_frames
        t_interp = _time_axis_ms(ws, fs)
        orig_interp = np.interp(np.arange(ws[0], ws[1]), ca_frames, result.original_data)

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 6), sharex=True)
        ax1.plot(t_interp, orig_interp, color='purple', linewidth=1, label='Raw fluorescence')
        ax1.plot(t_interp, result.baseline, color='red', linewidth=1,
                 linestyle='--', label='Estimated baseline')
        ax1.set_ylabel('Fluorescence (a.u.)')
        ax1.set_title(f'Calcium ROI {result.trace_idx}: Baseline Correction')
        ax1.legend(loc='upper right')
        ax1.grid(True, alpha=0.3)

        ax2.plot(t_interp, result.data, color='purple', linewidth=1, label='Baseline-corrected')
        ax2.set_xlabel('Time (ms)')
        ax2.set_ylabel('Corrected Fluorescence (a.u.)')
        ax2.legend(loc='upper right')
        ax2.grid(True, alpha=0.3)

        plt.gca().margins(x=0)
        plt.tight_layout()
    else:
        t = _time_axis_ms(ws, fs)
        plt.figure(figsize=(12, 4))
        plt.plot(t, result.data, linewidth=1, color='purple', label=f'ROI {result.trace_idx}')
        plt.xlabel('Time (ms)')
        plt.ylabel('Fluorescence (a.u.)')
        plt.title(f'Calcium ROI {result.trace_idx}: {result.label}')
        plt.legend(loc='upper right')
        plt.grid(True, alpha=0.3)
        plt.gca().margins(x=0)
        plt.tight_layout()
    _show_params_panel(ctx)
    plt.show()


def plot_rt_trace(result: RTTrace, ctx: PipelineContext, last_op) -> None:
    """Auto-plot for RTTrace."""
    ws = result.window_samples
    fs = result.fs_hz
    t = _time_axis_ms(ws, fs)
    ylabel = 'Probability' if result.label == 'sigmoid' else 'Logit'

    plt.figure(figsize=(15, 4))
    plt.plot(t, result.data, linewidth=0.5, color='blue')
    plt.xlabel('Time (ms)')
    plt.ylabel(ylabel)
    plt.title(f'RTSort Channel {result.channel_idx}: {result.label}' + _window_suffix(ws, fs))
    plt.grid(True, alpha=0.3)
    plt.gca().margins(x=0)
    plt.tight_layout()
    _show_params_panel(ctx)
    plt.show()


def plot_rt_bank(result: RTBank, ctx: PipelineContext, last_op) -> None:
    """Auto-plot for RTBank — show first few channels."""
    ws = result.window_samples
    fs = result.fs_hz
    t = _time_axis_ms(ws, fs)
    n_ch = result.traces.shape[0]
    show = min(5, n_ch)
    ylabel = 'Probability' if result.label == 'sigmoid' else 'Logit'

    fig, axes = plt.subplots(show, 1, figsize=(15, 2.5 * show), sharex=True)
    if show == 1:
        axes = [axes]
    for i, ax in enumerate(axes):
        ax.plot(t, result.traces[i], linewidth=0.5, color='blue')
        ax.set_ylabel(f'Ch {result.channel_ids[i]}\n{ylabel}')
        ax.grid(True, alpha=0.3)
        ax.margins(x=0)
    axes[-1].set_xlabel('Time (ms)')
    axes[0].set_title(f'RTSort Bank ({n_ch} channels): {result.label}' + _window_suffix(ws, fs))
    plt.tight_layout()
    _show_params_panel(ctx)
    plt.show()


def plot_sim_calcium(result: SimCalcium, ctx: PipelineContext, last_op) -> None:
    """Auto-plot for SimCalcium."""
    ws = result.window_samples
    fs = result.fs_hz
    t = _time_axis_ms(ws, fs)

    plt.figure(figsize=(15, 4))
    plt.plot(t, result.data, color='green', linewidth=1, label='Simulated calcium trace')

    if len(result.spike_indices) > 0:
        plt.plot([], [], color='black', linewidth=2,
                 label=f'Detected spikes (n={len(result.spike_indices)})')
    for si in result.spike_indices:
        if si < len(result.data):
            x = t[si]
            y = result.data[si]
            plt.plot([x, x], [y + 0.02, y + 0.07], color='black', linewidth=2)

    plt.xlabel('Time (ms)')
    plt.ylabel('Simulated dF/F0')
    plt.title(f'Source {result.source_id}: Simulated GCaMP Trace' + _window_suffix(ws, fs))
    plt.legend(loc='upper right')
    plt.grid(True, alpha=0.3)
    plt.gca().margins(x=0)
    plt.tight_layout()
    _show_params_panel(ctx)
    plt.show()


def plot_correlation(result: CorrelationResult, ctx: PipelineContext, last_op) -> None:
    """Auto-plot for CorrelationResult: spatial heatmap + best match overlay."""
    vmax = np.max(np.abs(result.correlations))
    cmap_name = 'RdBu_r'
    cmap = plt.cm.get_cmap(cmap_name)

    plt.figure(figsize=(12, 10))
    if result.pct_masked is not None:
        frac_clean = np.clip(1 - result.pct_masked / 100, 0, 1)
        sizes = 10 + 240 * frac_clean ** 2
    else:
        sizes = 250
    sc = plt.scatter(result.x_coords, result.y_coords, c=result.correlations,
                     cmap=cmap_name, s=sizes, vmin=-vmax, vmax=vmax,
                     edgecolors='black', linewidths=0.5, alpha=0.8)
    best_info = result.electrode_info[result.best_idx]
    norm_val = (result.best_corr + vmax) / (2 * vmax)
    best_color = cmap(norm_val)
    plt.scatter(result.x_coords[result.best_idx], result.y_coords[result.best_idx],
                marker='*', s=500, c=[best_color],
                edgecolors='black', linewidths=1.5, zorder=10)
    plt.colorbar(sc, label='Normalized Cross-Correlation (Pearson r)')
    plt.xlabel('Electrode X Position (um)')
    plt.ylabel('Electrode Y Position (um)')
    plt.title(f'Spatial Correlation Map: Ca ROI {result.ca_trace_idx}\n'
              f'Best Match: Electrode {best_info["channel"]} '
              f'(r={result.best_corr:.4f}, {best_info["num_spikes"]} spikes)')
    plt.grid(True, alpha=0.2)
    plt.axis('equal')
    plt.gca().margins(x=0)
    plt.tight_layout()
    _show_params_panel(ctx)
    plt.show()

    ws = result.window_samples
    t = _time_axis_ms(ws, result.fs_hz)
    min_len = min(len(result.ca_signal), len(result.best_sim_trace), len(t))

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(15, 8), sharex=True)
    ax1.plot(t[:min_len], result.ca_signal[:min_len], color='purple', linewidth=1,
             label=f'Recorded Ca (ROI {result.ca_trace_idx}, baseline-corrected)')
    ax1.set_ylabel('Corrected Fluorescence (a.u.)')
    ax1.set_title(f'Best Match: Electrode {best_info["channel"]} '
                  f'at ({best_info["x"]:.0f}, {best_info["y"]:.0f}) um | '
                  f'r={result.best_corr:.4f} | {best_info["num_spikes"]} spikes')
    ax1.grid(True, alpha=0.3)
    ax1.legend(loc='upper right')
    ax2.plot(t[:min_len], result.best_sim_trace[:min_len], color='green', linewidth=1,
             label=f'Simulated GCaMP (electrode {best_info["channel"]}, '
                   f'{best_info["num_spikes"]} spikes)')
    ax2.set_xlabel('Time (ms)')
    ax2.set_ylabel('Simulated dF/F0')
    ax2.grid(True, alpha=0.3)
    ax2.legend(loc='upper right')
    plt.gca().margins(x=0)
    plt.tight_layout()
    plt.show()


def plot_spectrogram(result: Spectrogram, ctx: PipelineContext, last_op) -> None:
    """Auto-plot for Spectrogram (time-frequency heatmap)."""
    ws = result.window_samples
    fs = result.fs_hz

    plt.figure(figsize=(15, 6))
    im = plt.pcolormesh(result.times, result.frequencies, result.power,
                        shading='auto', cmap='viridis')
    plt.colorbar(im, label='Power Spectral Density (dB)')
    plt.ylabel('Frequency (Hz)')
    plt.xlabel('Time (ms)')
    plt.title(f'MEA Electrode {result.source_id}: Spectrogram' + _window_suffix(ws, fs))
    plt.ylim(result.frequencies[0], result.frequencies[-1])
    plt.gca().margins(x=0)
    plt.tight_layout()
    _show_params_panel(ctx)
    plt.show()


def plot_freq_traces(result: FreqPowerTraces, ctx: PipelineContext, last_op) -> None:
    """Plot power vs time at specific frequencies + broadband, linear y-axis."""
    t = result.times
    num_traces = len(result.freq_traces) + 1
    colors = plt.cm.tab10.colors

    fig, axes = plt.subplots(num_traces, 1, figsize=(15, 2.5 * num_traces), sharex=True)
    if num_traces == 1:
        axes = [axes]

    for ax, (hz, power), color in zip(axes, result.freq_traces.items(), colors):
        ax.plot(t, power, linewidth=0.8, color=color)
        ax.set_ylabel('Power\n(linear)', fontsize=8)
        ax.set_title(f'{hz:.0f} Hz', fontsize=9)
        ax.grid(True, alpha=0.3)
        ax.margins(x=0)

    bb_low, bb_high = result.broadband_range_hz
    axes[-1].plot(t, result.broadband_power, linewidth=0.8, color='black')
    axes[-1].set_ylabel('Power\n(linear)', fontsize=8)
    axes[-1].set_title(f'Broadband ({bb_low:.0f}\u2013{bb_high:.0f} Hz)', fontsize=9)
    axes[-1].grid(True, alpha=0.3)
    axes[-1].margins(x=0)
    axes[-1].set_xlabel('Time (ms)')

    fig.suptitle(f'MEA Electrode {result.source_id}: Frequency Power Traces', fontsize=12)
    plt.tight_layout()
    _show_params_panel(ctx)
    plt.show()


def plot_saturation_report(result: SaturationReport, ctx: PipelineContext, last_op) -> None:
    """Visualize saturation per electrode as histogram or electrode map scatter plot."""
    ch_ids = result.channel_ids
    counts = result.samples_masked
    n = len(counts)
    nonzero = int(np.sum(counts > 0))
    total = result.total_samples
    pct_masked = counts / total * 100 if total > 0 else np.zeros(n)

    ws = result.window_samples
    w_ms = (ws[1] - ws[0]) / result.fs_hz * 1000
    title = (
        f'Saturation Survey: {n} electrodes, {nonzero} with saturation\n'
        f'Window: {ws[0]/result.fs_hz*1000:.1f}–{ws[1]/result.fs_hz*1000:.1f} ms '
        f'({w_ms:.0f} ms, {result.total_samples} samples/electrode)'
    )

    if result.plot_type == "scatter":
        fig, ax = plt.subplots(figsize=(10, 10))
        locs = result.locations

        scatter = ax.scatter(locs[:, 0], locs[:, 1], c=pct_masked, s=100,
                            cmap='YlOrRd', edgecolors='black', linewidth=0.5, alpha=0.8)
        cbar = plt.colorbar(scatter, ax=ax)
        cbar.set_label('% of window masked', fontsize=10)

        ax.set_xlabel('X coordinate (µm)', fontsize=10)
        ax.set_ylabel('Y coordinate (µm)', fontsize=10)
        ax.set_title(title, fontsize=11)
        ax.grid(True, alpha=0.3)
        ax.set_aspect('equal', adjustable='box')

        top_order = np.argsort(counts)[::-1]
        top = min(10, nonzero)
        if top > 0:
            lines = [f'Top {top} worst:'] + [
                f'  ch {ch_ids[top_order[k]]}: {counts[top_order[k]]:,} ({pct_masked[top_order[k]]:.1f}%)'
                for k in range(top)
            ]
            ax.text(0.02, 0.98, '\n'.join(lines), transform=ax.transAxes,
                    ha='left', va='top', fontsize=7, family='monospace',
                    bbox=dict(boxstyle='round', facecolor='white', alpha=0.85, edgecolor='gray'))
    elif result.plot_type == "survival":
        bins = np.arange(0, 101, 1)
        survival = np.array([np.sum(pct_masked >= t) for t in bins])

        fig, ax = plt.subplots(figsize=(12, 5))
        ax.plot(bins, survival, color='steelblue', linewidth=2)

        ax.set_xlabel('% of window masked (threshold)')
        ax.set_ylabel('# electrodes with saturation ≥ threshold')
        ax.set_xlim(0, 100)
        ax.set_ylim(0, n * 1.05)
        ax.set_title(title)
        ax.grid(True, alpha=0.3)
    else:
        fig, ax = plt.subplots(figsize=(10, 5))
        ax.bar(np.arange(n), counts, width=1.0, color='steelblue', edgecolor='none')

        max_count = int(np.max(counts)) if len(counts) > 0 else 1
        ax.set_xlim(-0.5, n - 0.5)
        ax.set_ylim(0, max_count * 1.05)
        tick_pos = [int(p) for p in np.linspace(0, n - 1, min(6, n))]
        ax.set_xticks(tick_pos)
        ax.set_xticklabels([str(ch_ids[p]) for p in tick_pos], fontsize=8)
        ax.set_xlabel('Channel ID (recording file order)')
        ax.set_ylabel('Samples masked')

        secax = ax.secondary_yaxis('right', functions=(
            lambda x: x / total * 100,
            lambda x: x * total / 100,
        ))
        secax.set_ylabel('% of window masked')

        ax.set_title(title)

        top_order = np.argsort(counts)[::-1]
        top = min(10, nonzero)
        if top > 0:
            lines = [f'Top {top} worst:'] + [
                f'  ch {ch_ids[top_order[k]]}: {counts[top_order[k]]:,} ({pct_masked[top_order[k]]:.1f}%)'
                for k in range(top)
            ]
            ax.text(0.98, 0.97, '\n'.join(lines), transform=ax.transAxes,
                    ha='right', va='top', fontsize=7, family='monospace',
                    bbox=dict(boxstyle='round', facecolor='white', alpha=0.85, edgecolor='gray'))

        ax.grid(True, axis='y', alpha=0.3)

    fig.tight_layout()
    _show_params_panel(ctx)
    plt.show()


def plot_overlay(results, labels, ctx: PipelineContext) -> None:
    """Plot multiple results overlaid on same axes (normalized 0-1)."""
    ws = ctx.window_samples_mea
    fs = ctx.mea_fs_hz
    t = _time_axis_ms(ws, fs)
    colors = ['blue', 'red', 'green', 'purple', 'orange', 'cyan']

    plt.figure(figsize=(15, 4))
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
        plt.plot(t[:min_len], d_norm, linewidth=1, alpha=0.7,
                 color=colors[i % len(colors)], label=label)

    plt.xlabel('Time (ms)')
    plt.ylabel('Normalized Amplitude (0-1)')
    plt.title('Overlay: Signals normalized to [0, 1] for visual comparison'
              + _window_suffix(ws, fs))
    plt.legend(loc='upper right')
    plt.grid(True, alpha=0.3)
    plt.gca().margins(x=0)
    plt.tight_layout()
    _show_params_panel(ctx)
    plt.show()


def register(registry: OpRegistry) -> None:
    """Register all matplotlib plot handlers + the overlay handler."""
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
