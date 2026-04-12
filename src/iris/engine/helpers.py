"""Pure signal processing helper functions used by op handlers."""
from __future__ import annotations

import numpy as np
from scipy.signal import correlate, find_peaks


def detect_spikes_constant_rms(signal, fs, k, min_distance_ms, prominence=None):
    """Detect spikes using constant RMS threshold (negative polarity)."""
    threshold = -k * np.std(signal)
    distance = int(min_distance_ms * fs / 1000)
    kwargs = {"height": -threshold, "distance": distance}
    if prominence is not None:
        kwargs["prominence"] = prominence
    spike_indices, props = find_peaks(-signal, **kwargs)
    spike_values = signal[spike_indices]
    threshold_curve = np.full(len(signal), threshold)
    return threshold_curve, spike_indices, spike_values


def detect_spikes_sliding_rms(signal, fs, k, half_window_ms, min_spike_distance_ms,
                               min_nonzero_fraction=0.2, zero_eps=1e-4, zero_buffer_ms=0.0,
                               prominence=None):
    """Detect spikes using sliding RMS threshold (negative polarity)."""
    N = len(signal)
    half_w = int(round(half_window_ms * fs / 1000.0))
    wlen = 2 * half_w + 1
    min_count = max(1, int(round(wlen * min_nonzero_fraction)))

    nz = (np.abs(signal) > zero_eps)
    x2 = (signal * signal) * nz

    csum = np.empty(N + 1, dtype=float)
    csum[0] = 0.0
    np.cumsum(x2, out=csum[1:])

    ccount = np.empty(N + 1, dtype=np.int64)
    ccount[0] = 0
    np.cumsum(nz.astype(np.int64), out=ccount[1:])

    idx = np.arange(N)
    lo = np.clip(idx - half_w, 0, N)
    hi = np.clip(idx + half_w + 1, 0, N)

    ss = csum[hi] - csum[lo]
    nn = ccount[hi] - ccount[lo]

    rms = np.sqrt(ss / np.maximum(nn, 1))
    rms[nn < min_count] = np.nan
    threshold = -k * rms

    invalid = ~nz
    if zero_buffer_ms > 0:
        buf = int(round(zero_buffer_ms * fs / 1000.0))
        if buf > 0:
            kern = np.ones(2 * buf + 1, dtype=int)
            invalid = np.convolve(invalid.astype(int), kern, mode="same") > 0

    valid = (~invalid) & np.isfinite(threshold)
    distance = int(round(min_spike_distance_ms * fs / 1000.0))

    s_for_peaks = -signal.copy()
    s_for_peaks[~valid] = -np.inf

    kwargs = {"distance": distance}
    if prominence is not None:
        kwargs["prominence"] = prominence
    peak_idx, _ = find_peaks(s_for_peaks, **kwargs)

    keep = valid[peak_idx] & (signal[peak_idx] < threshold[peak_idx])
    spike_indices = peak_idx[keep]
    spike_values = signal[spike_indices]

    return threshold, spike_indices, spike_values


def cross_correlate_pair(ca_signal, sim_trace, max_lag_samples, normalize=True):
    """Max cross-correlation between calcium and simulated trace."""
    min_len = min(len(ca_signal), len(sim_trace))
    ca = ca_signal[:min_len]
    sim = sim_trace[:min_len]
    if normalize:
        ca = (ca - np.mean(ca)) / (np.std(ca) + 1e-10)
        sim = (sim - np.mean(sim)) / (np.std(sim) + 1e-10)
    corr = correlate(ca, sim, mode='same') / min_len
    center = len(corr) // 2
    return np.max(corr[center - max_lag_samples:center + max_lag_samples + 1])
