"""Tests for individual op handlers using synthetic data."""
from __future__ import annotations

import numpy as np
import pytest

from iris.engine.types import CATrace, MEATrace, PipelineContext, RTTrace, SpikePCA, SpikeTrain
from synthetic_data import synth_calcium_trace, synth_mea_trace

# Shared context for all ops
_CTX = PipelineContext(
    paths={}, window_ms=(0.0, 1000.0), mea_fs_hz=20000.0, verbose=False,
    ops_cfg={
        "gcamp_sim": {
            "half_rise_ms": 80.0, "half_decay_ms": 500.0,
            "duration_ms": 2500.0, "peak_dff": 0.20,
        },
    },
)


def _make_mea_trace(duration_ms=1000.0, fs_hz=20000.0, seed=0):
    trace, spikes = synth_mea_trace(duration_ms=duration_ms, fs_hz=fs_hz, seed=seed)
    ws = (0, int(duration_ms * fs_hz / 1000))
    return MEATrace(data=trace, fs_hz=fs_hz, channel_idx=0, window_samples=ws)


def _make_spike_train(duration_ms=1000.0, fs_hz=20000.0, seed=0):
    trace, spike_times = synth_mea_trace(duration_ms=duration_ms, fs_hz=fs_hz, seed=seed)
    ws = (0, len(trace))
    return SpikeTrain(
        spike_indices=spike_times,
        spike_values=trace[spike_times],
        threshold_curve=np.full(len(trace), -20.0),
        source_signal=trace,
        fs_hz=fs_hz,
        source_id=0,
        window_samples=ws,
    )


# -- Filtering ops --

def test_butter_bandpass():
    from iris.engine.ops.filtering import op_butter_bandpass
    inp = _make_mea_trace()
    result = op_butter_bandpass(inp, _CTX, low_hz=300, high_hz=3000, order=4)
    assert isinstance(result, MEATrace)
    assert result.label == "bandpass"
    assert len(result.data) == len(inp.data)


def test_notch_filter():
    from iris.engine.ops.filtering import op_notch_filter
    inp = _make_mea_trace()
    result = op_notch_filter(inp, _CTX, notch_freq_hz=60.0, notch_q=30.0)
    assert isinstance(result, MEATrace)
    assert result.label == "notch"


def test_amp_gain_correction():
    from iris.engine.ops.filtering import op_amp_gain_correction
    inp = _make_mea_trace()
    result = op_amp_gain_correction(inp, _CTX, broadband_range_hz=[300, 3000])
    assert isinstance(result, MEATrace)
    assert result.label == "amp_gain_correction"


# -- Detection ops --

def test_sliding_rms():
    from iris.engine.ops.detection import op_sliding_rms
    inp = _make_mea_trace()
    result = op_sliding_rms(inp, _CTX, k=5.0, half_window_ms=50.0, min_spike_distance_ms=1.0)
    assert isinstance(result, SpikeTrain)
    assert result.num_spikes >= 0


def test_constant_rms():
    from iris.engine.ops.detection import op_constant_rms
    inp = _make_mea_trace()
    result = op_constant_rms(inp, _CTX, k=5.0, min_spike_distance_ms=1.0)
    assert isinstance(result, SpikeTrain)
    assert result.num_spikes >= 0


def test_sigmoid():
    from iris.engine.ops.detection import op_sigmoid
    inp = RTTrace(data=np.array([0.0, 1.0, -1.0, 5.0]), fs_hz=20000.0, channel_idx=0, window_samples=(0, 4))
    result = op_sigmoid(inp, _CTX)
    assert isinstance(result, RTTrace)
    assert result.label == "sigmoid"
    assert 0.0 < result.data[0] < 1.0  # sigmoid(0) = 0.5
    np.testing.assert_almost_equal(result.data[0], 0.5)


def test_rt_thresh():
    from iris.engine.ops.detection import op_rt_thresh
    inp = RTTrace(
        data=np.array([0.1, 0.2, 0.9, 0.3, 0.1, 0.8, 0.2]),
        fs_hz=20000.0, channel_idx=0, window_samples=(0, 7),
    )
    result = op_rt_thresh(inp, _CTX, threshold=0.5)
    assert isinstance(result, SpikeTrain)


# -- Analysis ops --

def test_spike_pca():
    from iris.engine.ops.analysis import op_spike_pca
    st = _make_spike_train()
    result = op_spike_pca(st, _CTX, snippet_ms=1.5, n_components=3, outlier_std=2.5)
    assert isinstance(result, SpikePCA)


def test_baseline_correction():
    from iris.engine.ops.analysis import op_baseline_correction
    ca_data, ca_frames = synth_calcium_trace()
    inp = CATrace(
        data=ca_data, fs_hz=20000.0, trace_idx=0,
        window_samples=(0, len(ca_data)),
        original_data=ca_data, original_frames=ca_frames,
    )
    result = op_baseline_correction(inp, _CTX, window_frames=50, percentile=10)
    assert isinstance(result, CATrace)
    assert result.label == "baseline_corrected"


# -- Simulation ops --

def test_gcamp_sim_single():
    from iris.engine.ops.simulation import op_gcamp_sim
    st = _make_spike_train()
    result = op_gcamp_sim(st, _CTX, half_rise_ms=80.0, half_decay_ms=500.0, duration_ms=2500.0, peak_dff=0.20)
    from iris.engine.types import SimCalcium
    assert isinstance(result, SimCalcium)
    assert result.label == "gcamp_sim"


# -- Spectral ops --

def test_spectrogram():
    from iris.engine.ops.spectral import op_spectrogram
    inp = _make_mea_trace()
    result = op_spectrogram(inp, _CTX, nperseg=256)
    from iris.engine.types import Spectrogram
    assert isinstance(result, Spectrogram)
    assert result.frequencies.ndim == 1
    assert result.power.ndim == 2


def test_freq_traces():
    from iris.engine.ops.spectral import op_freq_traces
    inp = _make_mea_trace()
    result = op_freq_traces(inp, _CTX, freqs_hz=[60, 300], broadband_range_hz=[300, 3000])
    from iris.engine.types import FreqPowerTraces
    assert isinstance(result, FreqPowerTraces)
    assert 60.0 in result.freq_traces or any(abs(k - 60) < 1 for k in result.freq_traces)


# -- Saturation ops --

def test_saturation_mask_fill_nan():
    from iris.engine.ops.saturation import op_saturation_mask
    # Create trace with a saturated segment (constant values)
    data = np.random.randn(1000)
    data[100:150] = 42.0  # flat segment = saturation
    inp = MEATrace(data=data, fs_hz=20000.0, channel_idx=0, window_samples=(0, 1000))
    result = op_saturation_mask(inp, _CTX, min_run=20, eps_range=0.1, mode="fill_nan")
    assert isinstance(result, MEATrace)
    assert np.any(np.isnan(result.data))
