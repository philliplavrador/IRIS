"""Filtering op handlers: butter_bandpass, notch_filter, amp_gain_correction."""
from __future__ import annotations

import numpy as np
from scipy.signal import (
    butter, filtfilt, iirnotch, sosfiltfilt, tf2sos,
    spectrogram as _scipy_spectrogram,
)

from casi.engine.types import MEATrace, PipelineContext


def op_butter_bandpass(inp: MEATrace, ctx: PipelineContext, *,
                       low_hz, high_hz, order, zero_phase=True) -> MEATrace:
    """Butterworth bandpass filter. Filters extended data then trims margins."""
    nyq = inp.fs_hz * 0.5
    b, a = butter(order, [low_hz / nyq, high_hz / nyq], btype='band')
    if zero_phase:
        filtered = filtfilt(b, a, inp.data)
    else:
        from scipy.signal import lfilter
        filtered = lfilter(b, a, inp.data)

    ml, mr = inp.margin_left, inp.margin_right
    if ml > 0 or mr > 0:
        end = len(filtered) - mr if mr > 0 else len(filtered)
        filtered = filtered[ml:end]

    return MEATrace(
        data=filtered,
        fs_hz=inp.fs_hz,
        channel_idx=inp.channel_idx,
        window_samples=inp.window_samples,
        margin_left=0, margin_right=0,
        label="bandpass",
    )


def op_notch_filter(inp: MEATrace, ctx: PipelineContext, *,
                    notch_freq_hz, notch_q, harmonics=None) -> MEATrace:
    """Notch filter with optional harmonics. Filters extended data then trims margins."""
    if harmonics is None:
        harmonics = [1]

    filtered = inp.data.copy()
    for harmonic in harmonics:
        freq = notch_freq_hz * harmonic
        b, a = iirnotch(freq, notch_q, inp.fs_hz)
        sos = tf2sos(b, a)
        filtered = sosfiltfilt(sos, filtered)

    ml, mr = inp.margin_left, inp.margin_right
    if ml > 0 or mr > 0:
        end = len(filtered) - mr if mr > 0 else len(filtered)
        filtered = filtered[ml:end]

    return MEATrace(
        data=filtered,
        fs_hz=inp.fs_hz,
        channel_idx=inp.channel_idx,
        window_samples=inp.window_samples,
        margin_left=0, margin_right=0,
        label="notch",
    )


def op_amp_gain_correction(inp: MEATrace, ctx: PipelineContext, *,
                           broadband_range_hz, nperseg=4096,
                           noverlap=None, window='hann') -> MEATrace:
    """Normalize signal amplitude by dividing by sqrt of broadband power envelope."""
    ml, mr = inp.margin_left, inp.margin_right
    if ml > 0 or mr > 0:
        end = len(inp.data) - mr if mr > 0 else len(inp.data)
        signal = inp.data[ml:end].copy()
    else:
        signal = inp.data.copy()

    fs = inp.fs_hz
    n = len(signal)

    freqs, times_s, Sxx = _scipy_spectrogram(
        signal, fs=fs, window=window, nperseg=nperseg,
        noverlap=noverlap, scaling='density', mode='psd',
    )

    bb_low, bb_high = broadband_range_hz
    bb_mask = (freqs >= bb_low) & (freqs <= bb_high)
    bb_power = Sxx[bb_mask, :].mean(axis=0)
    bb_sqrt = np.sqrt(np.maximum(bb_power, 1e-10))

    stft_sample_indices = times_s * fs
    signal_indices = np.arange(n, dtype=np.float64)
    bb_sqrt_interp = np.interp(signal_indices, stft_sample_indices, bb_sqrt)

    corrected = signal / bb_sqrt_interp

    return MEATrace(
        data=corrected,
        fs_hz=fs,
        channel_idx=inp.channel_idx,
        window_samples=inp.window_samples,
        margin_left=0, margin_right=0,
        label="amp_gain_correction",
    )
