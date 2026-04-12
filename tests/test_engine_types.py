"""Tests for engine type dataclasses."""
from __future__ import annotations

import numpy as np

from iris.engine import (
    CATrace,
    MEABank,
    MEATrace,
    PipelineContext,
    RTTrace,
    SimCalcium,
    SpikeTrain,
)


def test_pipeline_context_window_samples_mea():
    ctx = PipelineContext(paths={}, window_ms=(100.0, 200.0), mea_fs_hz=20000.0)
    start, end = ctx.window_samples_mea
    assert start == 2000
    assert end == 4000


def test_pipeline_context_window_samples_rtsort():
    ctx = PipelineContext(paths={}, window_ms=(0.0, 500.0), rtsort_fs_hz=10000.0)
    start, end = ctx.window_samples_rtsort
    assert start == 0
    assert end == 5000


def test_mea_trace_trimmed_data_no_margin():
    data = np.arange(100, dtype=float)
    trace = MEATrace(data=data, fs_hz=20000.0, channel_idx=0, window_samples=(0, 100))
    np.testing.assert_array_equal(trace.trimmed_data, data)


def test_mea_trace_trimmed_data_with_margins():
    data = np.arange(110, dtype=float)
    trace = MEATrace(
        data=data, fs_hz=20000.0, channel_idx=0, window_samples=(5, 105),
        margin_left=5, margin_right=5,
    )
    np.testing.assert_array_equal(trace.trimmed_data, data[5:105])


def test_spike_train_post_init():
    indices = np.array([10, 20, 30])
    st = SpikeTrain(
        spike_indices=indices,
        spike_values=np.array([1.0, 2.0, 3.0]),
        threshold_curve=np.zeros(100),
        source_signal=np.zeros(100),
        fs_hz=20000.0,
        source_id=0,
        window_samples=(0, 100),
    )
    assert st.num_spikes == 3


def test_mea_bank_construction():
    traces = np.random.randn(10, 200)
    bank = MEABank(
        traces=traces,
        fs_hz=20000.0,
        channel_ids=np.arange(10),
        locations=np.random.randn(10, 2),
        window_samples=(0, 200),
    )
    assert bank.traces.shape == (10, 200)
    assert bank.margin_left == 0


def test_sim_calcium_default_spike_indices():
    sc = SimCalcium(
        data=np.zeros(100),
        fs_hz=20000.0,
        source_id=0,
        window_samples=(0, 100),
    )
    assert len(sc.spike_indices) == 0
