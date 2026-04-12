"""DSL parser round-trip tests."""
from __future__ import annotations

from casi.engine import DSLParser, ExprNode, OverlayGroup, WindowDirective


def test_window_ms_parses():
    items = DSLParser().parse_pipeline(["window_ms[100, 2000]"])
    assert len(items) == 1
    assert isinstance(items[0], WindowDirective)
    assert items[0].start_ms == 100.0
    assert items[0].end_ms == 2000.0
    assert items[0].is_full is False


def test_window_full_parses():
    items = DSLParser().parse_pipeline(["window_ms[full]"])
    assert isinstance(items[0], WindowDirective)
    assert items[0].is_full is True


def test_simple_expression():
    items = DSLParser().parse_pipeline(["mea_trace(861).butter_bandpass.spectrogram"])
    assert isinstance(items[0], ExprNode)
    expr = items[0]
    assert expr.source.source_type == "mea_trace"
    assert expr.source.source_id == 861
    assert [op.op_name for op in expr.ops] == ["butter_bandpass", "spectrogram"]


def test_kwargs_overrides_parsed():
    items = DSLParser().parse_pipeline(["mea_trace(0).butter_bandpass(low_hz=300, high_hz=3000)"])
    expr = items[0]
    assert expr.ops[0].op_name == "butter_bandpass"
    assert expr.ops[0].kwargs_overrides == {"low_hz": 300, "high_hz": 3000}


def test_function_op_with_inner_expression():
    items = DSLParser().parse_pipeline([
        "ca_trace(12).baseline_correction.x_corr(mea_trace(all).butter_bandpass.sliding_rms.gcamp_sim)"
    ])
    expr = items[0]
    assert expr.source.source_type == "ca_trace"
    assert [op.op_name for op in expr.ops] == ["baseline_correction", "x_corr"]
    inner = expr.ops[1].inner_expr
    assert inner is not None
    assert inner.source.source_type == "mea_trace"
    assert inner.source.source_id == "all"
    assert [op.op_name for op in inner.ops] == ["butter_bandpass", "sliding_rms", "gcamp_sim"]


def test_overlay_group():
    items = DSLParser().parse_pipeline([
        ["mea_trace(0)", "mea_trace(0).butter_bandpass"],
    ])
    assert isinstance(items[0], OverlayGroup)
    assert len(items[0].expressions) == 2


def test_list_literal_in_kwargs():
    items = DSLParser().parse_pipeline(["mea_trace(0).notch_filter(harmonics=[1, 2, 3])"])
    expr = items[0]
    assert expr.ops[0].kwargs_overrides["harmonics"] == [1, 2, 3]


def test_cache_key_parts_stable():
    parser = DSLParser()
    a = parser.parse_pipeline(["mea_trace(861).butter_bandpass.spectrogram"])[0]
    b = parser.parse_pipeline(["mea_trace(861).butter_bandpass.spectrogram"])[0]
    assert a.cache_key_parts() == b.cache_key_parts()
