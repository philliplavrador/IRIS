"""Analysis op handlers: spike_pca, spike_curate, baseline_correction."""
from __future__ import annotations

import numpy as np
from scipy.ndimage import percentile_filter
from scipy.signal import convolve

from iris.engine.helpers import cross_correlate_pair
from iris.engine.types import CATrace, PipelineContext, SpikePCA, SpikeTrain


def op_spike_pca(inp: SpikeTrain, ctx: PipelineContext, *,
                 snippet_ms=1.5, n_components=3, outlier_std=2.5,
                 min_spikes=10) -> SpikePCA:
    """Project spike waveforms into PCA space and flag outliers by centroid distance."""
    fs = inp.fs_hz
    snippet_len = int(snippet_ms * fs / 1000)
    if snippet_len % 2 == 0:
        snippet_len += 1
    half = snippet_len // 2

    def _degenerate(indices, values):
        n = len(indices)
        return SpikePCA(
            spike_indices=indices,
            spike_values=values,
            waveforms=np.empty((n, snippet_len)),
            pca_projections=np.empty((n, 0)),
            pca_components=np.empty((0, snippet_len)),
            explained_variance_ratio=np.array([]),
            centroid=np.array([]),
            distances=np.zeros(n),
            outlier_mask=np.zeros(n, dtype=bool),
            source_signal=inp.source_signal,
            threshold_curve=inp.threshold_curve,
            fs_hz=fs,
            source_id=inp.source_id,
            window_samples=inp.window_samples,
            label="spike_pca",
        )

    if inp.num_spikes < min_spikes:
        print(f"  spike_pca: too few spikes ({inp.num_spikes} < {min_spikes}), skipping PCA")
        return _degenerate(inp.spike_indices, inp.spike_values)

    sig = inp.source_signal
    sig_len = len(sig)
    valid_idx = []
    waveform_list = []
    for i, idx in enumerate(inp.spike_indices):
        start = idx - half
        end = idx + half + 1
        if start < 0 or end > sig_len:
            continue
        waveform_list.append(sig[start:end])
        valid_idx.append(i)

    n_valid = len(valid_idx)
    if n_valid < min_spikes:
        print(f"  spike_pca: too few valid waveforms after boundary check "
              f"({n_valid} < {min_spikes}), skipping PCA")
        return _degenerate(inp.spike_indices, inp.spike_values)

    valid_idx = np.array(valid_idx)
    spike_indices = inp.spike_indices[valid_idx]
    spike_values = inp.spike_values[valid_idx]
    waveforms = np.array(waveform_list)

    nc = min(n_components, n_valid - 1, snippet_len)
    if nc < 1:
        print(f"  spike_pca: cannot compute PCA (n_valid={n_valid}), skipping")
        return _degenerate(spike_indices, spike_values)

    centered = waveforms - waveforms.mean(axis=0)
    U, S, Vt = np.linalg.svd(centered, full_matrices=False)

    pca_components = Vt[:nc]
    projections = centered @ pca_components.T
    total_var = (S ** 2).sum()
    explained_variance_ratio = (S[:nc] ** 2) / total_var if total_var > 0 else np.zeros(nc)

    centroid = projections.mean(axis=0)
    distances = np.linalg.norm(projections - centroid, axis=1)
    dist_mean = distances.mean()
    dist_std = distances.std()
    outlier_mask = distances > (dist_mean + outlier_std * dist_std)

    n_out = int(outlier_mask.sum())
    print(f"  spike_pca: {n_valid} waveforms, {nc} components "
          f"({explained_variance_ratio.sum() * 100:.1f}% var), "
          f"{n_out} outliers ({n_out / n_valid * 100:.1f}%)")

    return SpikePCA(
        spike_indices=spike_indices,
        spike_values=spike_values,
        waveforms=waveforms,
        pca_projections=projections,
        pca_components=pca_components,
        explained_variance_ratio=explained_variance_ratio,
        centroid=centroid,
        distances=distances,
        outlier_mask=outlier_mask,
        source_signal=inp.source_signal,
        threshold_curve=inp.threshold_curve,
        fs_hz=fs,
        source_id=inp.source_id,
        window_samples=inp.window_samples,
        label="spike_pca",
    )


def op_spike_curate(left: SpikePCA, right: CATrace, ctx: PipelineContext, *,
                    corr_threshold=0.005, max_lag_ms=500.0) -> SpikeTrain:
    """Iteratively remove PCA outlier spikes guided by cross-correlation improvement."""
    if not isinstance(left, SpikePCA):
        raise TypeError(f"spike_curate left operand must be SpikePCA, got {type(left).__name__}")
    if not isinstance(right, CATrace):
        raise TypeError(f"spike_curate right operand must be CATrace, got {type(right).__name__}")

    inp = left
    n_total = len(inp.spike_indices)
    if n_total == 0:
        print("  spike_curate: no spikes to curate")
        return SpikeTrain(
            spike_indices=inp.spike_indices, spike_values=inp.spike_values,
            threshold_curve=inp.threshold_curve, source_signal=inp.source_signal,
            fs_hz=inp.fs_hz, source_id=inp.source_id,
            window_samples=inp.window_samples, label="spike_curate",
        )

    # Build GCaMP kernel from ops_cfg
    from iris.engine.ops.simulation import _build_gcamp_kernel

    gcamp_cfg = ctx.ops_cfg.get("gcamp_sim", {})
    kernel = _build_gcamp_kernel(
        inp.fs_hz,
        gcamp_cfg.get("half_rise_ms", 80.0),
        gcamp_cfg.get("half_decay_ms", 500.0),
        gcamp_cfg.get("duration_ms", 2500.0),
        gcamp_cfg.get("peak_dff", 0.20),
    )
    max_lag_samples = int(max_lag_ms * right.fs_hz / 1000)
    ca_signal = right.data
    num_samples = len(inp.source_signal)

    def _sim_and_correlate(indices):
        """Generate sim calcium from spike indices and correlate with real CA."""
        spike_arr = np.zeros(num_samples)
        if len(indices) > 0:
            spike_arr[indices] = 1
        sim = convolve(spike_arr, kernel, mode='full')[:num_samples]
        return cross_correlate_pair(ca_signal, sim, max_lag_samples)

    # Baseline correlation with all spikes
    keep_mask = np.ones(n_total, dtype=bool)
    baseline_corr = _sim_and_correlate(inp.spike_indices)

    # Rank outlier candidates by distance (farthest first)
    candidate_idx = np.where(inp.outlier_mask)[0]
    candidate_idx = candidate_idx[np.argsort(-inp.distances[candidate_idx])]

    n_removed = 0
    current_corr = baseline_corr
    for ci in candidate_idx:
        # Temporarily remove this spike
        test_mask = keep_mask.copy()
        test_mask[ci] = False
        test_corr = _sim_and_correlate(inp.spike_indices[test_mask])

        if test_corr >= current_corr + corr_threshold:
            keep_mask[ci] = False
            current_corr = test_corr
            n_removed += 1

    print(f"  spike_curate: removed {n_removed}/{n_total} spikes "
          f"(corr {baseline_corr:.4f} → {current_corr:.4f})")

    curated_indices = inp.spike_indices[keep_mask]
    curated_values = inp.spike_values[keep_mask]
    return SpikeTrain(
        spike_indices=curated_indices,
        spike_values=curated_values,
        threshold_curve=inp.threshold_curve,
        source_signal=inp.source_signal,
        fs_hz=inp.fs_hz,
        source_id=inp.source_id,
        window_samples=inp.window_samples,
        label="spike_curate",
    )


def op_baseline_correction(inp: CATrace, ctx: PipelineContext, *,
                            window_frames, percentile) -> CATrace:
    """Percentile baseline correction for calcium traces."""
    if inp.original_data is not None:
        baseline = percentile_filter(
            inp.original_data.astype(float), percentile,
            size=window_frames, mode='nearest')
        corrected_orig = inp.original_data - baseline + np.mean(inp.original_data)

        start_sample, end_sample = inp.window_samples
        target_frames = np.arange(start_sample, end_sample)
        corrected_interp = np.interp(target_frames, inp.original_frames, corrected_orig)
        baseline_interp = np.interp(target_frames, inp.original_frames, baseline)
    else:
        baseline_arr = percentile_filter(
            inp.data.astype(float), percentile,
            size=window_frames, mode='nearest')
        corrected_interp = inp.data - baseline_arr + np.mean(inp.data)
        baseline_interp = baseline_arr

    return CATrace(
        data=corrected_interp,
        fs_hz=inp.fs_hz,
        trace_idx=inp.trace_idx,
        window_samples=inp.window_samples,
        original_data=inp.original_data,
        original_frames=inp.original_frames,
        baseline=baseline_interp,
        label="baseline_corrected",
    )
