"""Two-tier prefix cache tests."""
from __future__ import annotations

from pathlib import Path

from casi.engine import DSLParser, OpNode, PipelineCache, SourceNode


def test_make_key_stable_for_same_inputs(tmp_path):
    cache = PipelineCache(cache_dir=str(tmp_path), source_paths={}, disk_cache=False)
    parser = DSLParser()
    expr = parser.parse_pipeline(["mea_trace(0).butter_bandpass.spectrogram"])[0]
    k1 = cache.make_key((0.0, 1000.0), expr.cache_key_parts(), {}, margin=0)
    k2 = cache.make_key((0.0, 1000.0), expr.cache_key_parts(), {}, margin=0)
    assert k1 == k2


def test_make_key_changes_with_window():
    cache = PipelineCache(source_paths={}, disk_cache=False)
    parser = DSLParser()
    expr = parser.parse_pipeline(["mea_trace(0).butter_bandpass"])[0]
    k1 = cache.make_key((0.0, 1000.0), expr.cache_key_parts(), {})
    k2 = cache.make_key((0.0, 2000.0), expr.cache_key_parts(), {})
    assert k1 != k2


def test_make_key_changes_with_op_params():
    cache = PipelineCache(source_paths={}, disk_cache=False)
    parser = DSLParser()
    expr = parser.parse_pipeline(["mea_trace(0).butter_bandpass"])[0]
    ops_a = {"butter_bandpass": {"low_hz": 300, "high_hz": 3000}}
    ops_b = {"butter_bandpass": {"low_hz": 350, "high_hz": 6000}}
    k1 = cache.make_key((0.0, 1000.0), expr.cache_key_parts(), ops_a)
    k2 = cache.make_key((0.0, 1000.0), expr.cache_key_parts(), ops_b)
    assert k1 != k2


def test_make_key_includes_file_mtime(tmp_path):
    f = tmp_path / "fake.h5"
    f.write_text("first")
    cache_a = PipelineCache(source_paths={"mea_h5": str(f)}, disk_cache=False)
    k_a = cache_a.make_key((0.0, 1000.0), (("mea_trace", 0),), {})

    # Modify the file: mtime changes → key changes
    import time
    time.sleep(0.01)
    f.write_text("second")
    cache_b = PipelineCache(source_paths={"mea_h5": str(f)}, disk_cache=False)
    k_b = cache_b.make_key((0.0, 1000.0), (("mea_trace", 0),), {})
    assert k_a != k_b


def test_mem_put_and_get():
    cache = PipelineCache(source_paths={}, disk_cache=False)
    cache.mem_put("k", "value")
    assert cache.mem_get("k") == "value"
    assert cache.mem_get("missing") is None


def test_find_longest_prefix_returns_minus_one_for_empty():
    cache = PipelineCache(source_paths={}, disk_cache=False)
    parser = DSLParser()
    expr = parser.parse_pipeline(["mea_trace(0).butter_bandpass.spectrogram"])[0]
    n, cached = cache.find_longest_prefix((0.0, 1000.0), expr, {}, margin=0)
    assert n == -1
    assert cached is None


def test_find_longest_prefix_finds_full_match():
    cache = PipelineCache(source_paths={}, disk_cache=False)
    parser = DSLParser()
    expr = parser.parse_pipeline(["mea_trace(0).butter_bandpass.spectrogram"])[0]
    full_key = cache.make_prefix_key((0.0, 1000.0), expr.source, expr.ops, {}, margin=0)
    cache.mem_put(full_key, "RESULT")
    n, cached = cache.find_longest_prefix((0.0, 1000.0), expr, {}, margin=0)
    assert n == len(expr.ops)
    assert cached == "RESULT"


def test_find_longest_prefix_finds_partial_match():
    cache = PipelineCache(source_paths={}, disk_cache=False)
    parser = DSLParser()
    expr = parser.parse_pipeline(["mea_trace(0).butter_bandpass.spectrogram"])[0]
    partial_key = cache.make_prefix_key((0.0, 1000.0), expr.source, expr.ops[:1], {}, margin=0)
    cache.mem_put(partial_key, "BANDPASSED")
    n, cached = cache.find_longest_prefix((0.0, 1000.0), expr, {}, margin=0)
    assert n == 1
    assert cached == "BANDPASSED"
