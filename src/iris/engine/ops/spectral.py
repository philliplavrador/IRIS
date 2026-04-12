"""Spectral op handlers: spectrogram, freq_traces."""
from __future__ import annotations

from typing import Dict

import numpy as np
from scipy.signal import spectrogram as _scipy_spectrogram

from iris.engine.types import FreqPowerTraces, MEATrace, PipelineContext, Spectrogram


def op_spectrogram(inp: MEATrace, ctx: PipelineContext, *,
                   nperseg=256, noverlap=None, window='hann',
                   scaling='density', fmin=0, fmax=None, db_scale=True) -> Spectrogram:
    """Compute time-frequency spectrogram from MEATrace."""
    signal = inp.trimmed_data if hasattr(inp, 'trimmed_data') else inp.data
    fs = inp.fs_hz

    freqs, times, Sxx = _scipy_spectrogram(
        signal, fs=fs, window=window, nperseg=nperseg,
        noverlap=noverlap, scaling=scaling, mode='psd'
    )
    window_start_ms = inp.window_samples[0] / fs * 1000
    times_ms = times * 1000 + window_start_ms

    if fmax is None:
        fmax = fs / 2
    freq_mask = (freqs >= fmin) & (freqs <= fmax)
    freqs_filtered = freqs[freq_mask]
    Sxx_filtered = Sxx[freq_mask, :]

    if db_scale:
        Sxx_filtered = 10 * np.log10(Sxx_filtered + 1e-10)

    return Spectrogram(
        frequencies=freqs_filtered,
        times=times_ms,
        power=Sxx_filtered,
        fs_hz=fs,
        source_id=inp.channel_idx if hasattr(inp, 'channel_idx') else 0,
        window_samples=inp.window_samples,
        label="spectrogram",
    )


def op_freq_traces(inp: MEATrace, ctx: PipelineContext, *,
                   freqs_hz, broadband_range_hz,
                   nperseg=4096, noverlap=None, window='hann') -> FreqPowerTraces:
    """Compute power vs time at specific frequencies from MEATrace using STFT."""
    signal = inp.trimmed_data if hasattr(inp, 'trimmed_data') else inp.data
    fs = inp.fs_hz

    freqs, times_s, Sxx = _scipy_spectrogram(
        signal, fs=fs, window=window, nperseg=nperseg,
        noverlap=noverlap, scaling='density', mode='psd',
    )
    window_start_ms = inp.window_samples[0] / fs * 1000
    times_ms = times_s * 1000 + window_start_ms

    freq_traces_dict: Dict[float, np.ndarray] = {}
    for hz in freqs_hz:
        idx = int(np.argmin(np.abs(freqs - hz)))
        freq_traces_dict[float(hz)] = Sxx[idx, :]

    bb_low, bb_high = broadband_range_hz
    bb_mask = (freqs >= bb_low) & (freqs <= bb_high)
    broadband_power = Sxx[bb_mask, :].mean(axis=0)

    return FreqPowerTraces(
        times=times_ms,
        freq_traces=freq_traces_dict,
        broadband_power=broadband_power,
        broadband_range_hz=tuple(broadband_range_hz),
        fs_hz=fs,
        source_id=inp.channel_idx,
        window_samples=inp.window_samples,
    )
