"""Tests for PipelineExecutor with a mock registry."""
from __future__ import annotations

import numpy as np

from casi.engine import (
    DSLParser,
    MEATrace,
    OpRegistry,
    PipelineCache,
    PipelineContext,
    PipelineExecutor,
    TYPE_TRANSITIONS,
)


def _mock_bandpass(inp: MEATrace, ctx, *, low_hz=300, high_hz=3000, order=4, zero_phase=True):
    """Identity bandpass for testing — returns input unchanged."""
    return MEATrace(
        data=inp.trimmed_data.copy(),
        fs_hz=inp.fs_hz,
        channel_idx=inp.channel_idx,
        window_samples=inp.window_samples,
        label="mock_bandpass",
    )


def _mock_loader(source_id, ctx, margin_samples=0):
    """Return a synthetic MEATrace."""
    n = ctx.window_samples_mea[1] - ctx.window_samples_mea[0]
    return MEATrace(
        data=np.random.randn(n),
        fs_hz=ctx.mea_fs_hz,
        channel_idx=int(source_id) if source_id != 'all' else 0,
        window_samples=ctx.window_samples_mea,
        label="mock_raw",
    )


def _make_executor():
    registry = OpRegistry()
    registry.register_op("butter_bandpass", _mock_bandpass)

    ctx = PipelineContext(
        paths={},
        window_ms=(100.0, 200.0),
        mea_fs_hz=20000.0,
        verbose=False,
    )
    cache = PipelineCache(memory_cache=True, disk_cache=False)
    ctx.cache = cache
    ops_cfg = {"butter_bandpass": {"low_hz": 300, "high_hz": 3000, "order": 4}}
    source_loaders = {"mea_trace": _mock_loader}

    return PipelineExecutor(registry, cache, ctx, ops_cfg, source_loaders)


def test_executor_runs_simple_expression():
    executor = _make_executor()
    parser = DSLParser()
    items = parser.parse_pipeline(["mea_trace(0).butter_bandpass"])
    results = executor.run(items, plot=False)
    assert len(results) == 1
    _, result = results[0]
    assert isinstance(result, MEATrace)
    assert result.label == "mock_bandpass"


def test_executor_prefix_reuse():
    """Verifying the cache stores prefixes for reuse."""
    executor = _make_executor()
    parser = DSLParser()

    # First run: source + bandpass
    items1 = parser.parse_pipeline(["mea_trace(0).butter_bandpass"])
    executor.run(items1, plot=False)

    # Cache should have entries
    stats_after_first = executor.cache.stats
    assert stats_after_first["misses"] >= 1

    # Second run with same expression should hit cache
    items2 = parser.parse_pipeline(["mea_trace(0).butter_bandpass"])
    results2 = executor.run(items2, plot=False)
    stats_after_second = executor.cache.stats
    assert stats_after_second["hits"] >= 1

    _, result = results2[0]
    assert isinstance(result, MEATrace)


def test_executor_window_directive():
    executor = _make_executor()
    parser = DSLParser()
    items = parser.parse_pipeline(["window_ms[50, 150]", "mea_trace(0).butter_bandpass"])
    results = executor.run(items, plot=False)
    assert len(results) == 2
    # First item is window directive
    assert results[0][1] is None
    # Context should be updated
    assert executor.ctx.window_ms == (50.0, 150.0)
