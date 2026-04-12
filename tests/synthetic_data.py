"""Generate small synthetic MEA + calcium signals for tests.

The real Maxwell recordings are too large (1.6 GB) to commit to git, and
spikeinterface doesn't have an easy in-memory MEA fixture, so the test
suite uses these helpers instead. They produce numpy arrays only — no
disk IO, no spikeinterface — so they work in CI without any data deps.
"""
from __future__ import annotations

import numpy as np


def synth_mea_trace(
    duration_ms: float = 1000.0,
    fs_hz: float = 20000.0,
    n_spikes: int = 10,
    spike_amplitude: float = 100.0,
    noise_std: float = 5.0,
    seed: int = 0,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (trace, spike_times_in_samples) for a single MEA channel.

    Trace is bandlimited Gaussian noise with N negative-going spike templates
    inserted at random times.
    """
    rng = np.random.default_rng(seed)
    n_samples = int(duration_ms * fs_hz / 1000)
    trace = rng.standard_normal(n_samples) * noise_std

    # Simple negative-going spike template (~1 ms)
    template_len = int(0.001 * fs_hz)
    t_template = np.arange(template_len) / fs_hz
    template = -spike_amplitude * np.exp(-t_template / 0.0003) * np.sin(2 * np.pi * 1500 * t_template)

    spike_times = rng.choice(
        np.arange(template_len, n_samples - template_len),
        size=n_spikes,
        replace=False,
    )
    spike_times.sort()
    for s in spike_times:
        trace[s:s + template_len] += template

    return trace, spike_times


def synth_calcium_trace(
    duration_ms: float = 1000.0,
    fs_hz: float = 50.0,
    spike_times_in_mea_samples: np.ndarray | None = None,
    mea_fs_hz: float = 20000.0,
    rise_ms: float = 80.0,
    decay_ms: float = 500.0,
    noise_std: float = 0.01,
    seed: int = 0,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (trace, frame_times_in_mea_samples).

    If ``spike_times_in_mea_samples`` is provided, the trace is a sum of
    GCaMP-shaped impulses at those times. Otherwise it's pure noise.
    """
    rng = np.random.default_rng(seed)
    n_frames = int(duration_ms * fs_hz / 1000)
    frame_times = np.linspace(0, duration_ms / 1000 * mea_fs_hz, n_frames)

    if spike_times_in_mea_samples is None:
        return rng.standard_normal(n_frames) * noise_std, frame_times.astype(int)

    tau_rise = rise_ms / 1000 / np.log(2)
    tau_decay = decay_ms / 1000 / np.log(2)

    trace = rng.standard_normal(n_frames) * noise_std
    for s in spike_times_in_mea_samples:
        spike_time_s = s / mea_fs_hz
        for i, ft in enumerate(frame_times / mea_fs_hz):
            dt = ft - spike_time_s
            if dt < 0:
                continue
            trace[i] += 0.2 * (1 - np.exp(-dt / tau_rise)) * np.exp(-dt / tau_decay)

    return trace, frame_times.astype(int)
