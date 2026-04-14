"""Session directory + provenance sidecar tests."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from iris.engine import DSLParser, PipelineContext
from iris.plot_sessions import (
    list_sessions,
    new_session,
    write_manifest,
    write_provenance_sidecar,
)


def test_new_session_creates_dir(tmp_path):
    sd = new_session(label="test", output_root=tmp_path)
    assert sd.is_dir()
    assert "session_001" in sd.name
    assert sd.name.endswith("test")


def test_new_session_increments_counter(tmp_path):
    sd1 = new_session(output_root=tmp_path)
    sd2 = new_session(output_root=tmp_path)
    assert sd1 != sd2
    assert "session_001" in sd1.name
    assert "session_002" in sd2.name


def test_new_session_sanitizes_label(tmp_path):
    sd = new_session(label="this is/a bad/label!", output_root=tmp_path)
    assert "/" not in sd.name
    assert "!" not in sd.name


def test_list_sessions_returns_newest_first(tmp_path):
    sd1 = new_session(label="a", output_root=tmp_path)
    sd2 = new_session(label="b", output_root=tmp_path)
    sd3 = new_session(label="c", output_root=tmp_path)
    sessions = list_sessions(tmp_path)
    assert len(sessions) == 3
    # newest first means session_003 before session_001
    assert sessions[0] == sd3
    assert sessions[-1] == sd1


def test_list_sessions_empty_dir(tmp_path):
    assert list_sessions(tmp_path / "nonexistent") == []


def test_write_manifest_produces_valid_json(tmp_path):
    sd = new_session(output_root=tmp_path)
    fake_file = tmp_path / "fake.h5"
    fake_file.write_text("data")
    ctx = PipelineContext(
        paths={"mea_h5": str(fake_file), "output_dir": str(sd), "cache_dir": str(tmp_path / "cache")},
        window_ms=(0.0, 1000.0),
    )
    paths_cfg = {"mea_h5": str(fake_file), "output_dir": str(sd), "cache_dir": str(tmp_path / "cache")}
    write_manifest(sd, ctx, paths_cfg, ops_cfg={"butter_bandpass": {"low_hz": 350}}, globals_cfg={"plot_backend": "matplotlib"})
    manifest = json.loads((sd / "manifest.json").read_text())
    assert manifest["iris_version"]
    assert manifest["paths"]["mea_h5"] == str(fake_file)
    assert manifest["sources"]["mea_h5"]["mtime"] > 0
    assert manifest["sources"]["mea_h5"]["size"] == 4
    assert manifest["window_ms"] == [0.0, 1000.0]


def test_write_provenance_sidecar(tmp_path):
    plot_path = tmp_path / "plot.png"
    plot_path.write_bytes(b"fake png")
    expr = DSLParser().parse_pipeline(["mea_trace(861).butter_bandpass.spectrogram"])[0]
    ctx = PipelineContext(
        paths={},
        window_ms=(100.0, 2000.0),
        ops_cfg={
            "butter_bandpass": {"low_hz": 350, "high_hz": 6000, "order": 10, "zero_phase": True},
            "spectrogram": {"nperseg": 16384, "fmin": 0, "fmax": 360},
        },
    )
    ctx.current_expr = expr
    sidecar = write_provenance_sidecar(plot_path, ctx)
    assert sidecar is not None and sidecar.is_file()
    payload = json.loads(sidecar.read_text())
    assert payload["dsl"] == "mea_trace(861).butter_bandpass.spectrogram"
    assert payload["window_ms"] == [100.0, 2000.0]
    assert len(payload["ops"]) == 2
    assert payload["ops"][0]["name"] == "butter_bandpass"
    assert payload["ops"][0]["params"]["low_hz"] == 350
    assert payload["ops"][1]["name"] == "spectrogram"


def test_write_provenance_sidecar_with_inner_expr(tmp_path):
    plot_path = tmp_path / "plot.png"
    plot_path.write_bytes(b"fake png")
    expr = DSLParser().parse_pipeline([
        "ca_trace(12).baseline_correction.x_corr(mea_trace(all).butter_bandpass.sliding_rms.gcamp_sim)"
    ])[0]
    ctx = PipelineContext(paths={}, window_ms=(0.0, 1000.0))
    ctx.current_expr = expr
    sidecar = write_provenance_sidecar(plot_path, ctx)
    payload = json.loads(sidecar.read_text())
    assert "x_corr" in payload["dsl"]
    assert payload["ops"][1]["name"] == "x_corr"
    assert "inner" in payload["ops"][1]
    assert payload["ops"][1]["inner"]["source"]["type"] == "mea_trace"


def test_write_provenance_sidecar_returns_none_for_no_expr(tmp_path):
    plot_path = tmp_path / "plot.png"
    ctx = PipelineContext(paths={}, window_ms=(0.0, 1000.0))
    ctx.current_expr = None
    assert write_provenance_sidecar(plot_path, ctx) is None
