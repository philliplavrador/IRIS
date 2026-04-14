"""Smoke tests for the `iris` CLI."""

from __future__ import annotations

import io
from contextlib import redirect_stdout

import pytest

from iris.cli import main


def test_cli_help_prints_usage():
    buf = io.StringIO()
    with redirect_stdout(buf):
        with pytest.raises(SystemExit) as exc:
            main(["--help"])
    assert exc.value.code == 0
    assert "iris" in buf.getvalue()
    assert "config" in buf.getvalue()
    assert "run" in buf.getvalue()


def test_cli_version():
    buf = io.StringIO()
    with redirect_stdout(buf):
        with pytest.raises(SystemExit) as exc:
            main(["--version"])
    assert exc.value.code == 0
    assert "iris" in buf.getvalue().lower()


def test_cli_config_show(tmp_configs_dir):
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["--config-dir", str(tmp_configs_dir), "config", "show"])
    assert rc == 0
    out = buf.getvalue()
    assert "IRIS configuration" in out
    assert "butter_bandpass" in out


def test_cli_config_validate_flags_missing_files(tmp_configs_dir):
    rc = main(["--config-dir", str(tmp_configs_dir), "config", "validate"])
    # The fixture configs reference nonexistent files on purpose
    assert rc == 1


def test_cli_config_edit(tmp_configs_dir):
    rc = main(
        [
            "--config-dir",
            str(tmp_configs_dir),
            "config",
            "edit",
            "ops",
            "butter_bandpass.low_hz",
            "300",
        ]
    )
    assert rc == 0
    # verify the change persisted
    import tomllib

    with (tmp_configs_dir / "config.toml").open("rb") as f:
        data = tomllib.load(f)
    assert data["ops"]["butter_bandpass"]["low_hz"] == 300


def test_cli_ops_list(tmp_configs_dir):
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["--config-dir", str(tmp_configs_dir), "ops", "list"])
    assert rc == 0
    out = buf.getvalue()
    # All 17 ops should appear in the listing
    for op in (
        "butter_bandpass",
        "notch_filter",
        "saturation_mask",
        "constant_rms",
        "sliding_rms",
        "spike_pca",
        "spike_curate",
        "baseline_correction",
        "rt_detect",
        "sigmoid",
        "rt_thresh",
        "gcamp_sim",
        "x_corr",
        "spectrogram",
        "freq_traces",
        "amp_gain_correction",
        "saturation_survey",
    ):
        assert op in out, f"missing op {op} in `iris ops list` output"


def test_cli_session_new_and_list(tmp_configs_dir, tmp_path, monkeypatch):
    # Re-write configs/paths.yaml to point output_dir at the tmp dir so the
    # session is created somewhere we can clean up
    out_dir = tmp_path / "outputs"
    # Windows paths have backslashes that TOML would interpret as escapes,
    # so convert to forward slashes (TOML treats them verbatim).
    out_dir_str = str(out_dir).replace("\\", "/")
    cache_dir_str = str(tmp_path / "cache").replace("\\", "/")
    (tmp_configs_dir / "config.toml").write_text(
        f"""
[paths]
mea_h5 = "nonexistent_mea.h5"
ca_traces_npz = "nonexistent_ca.npz"
output_dir = "{out_dir_str}"
cache_dir = "{cache_dir_str}"
""".strip()
    )

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["--config-dir", str(tmp_configs_dir), "session", "new", "--label", "smoke"])
    assert rc == 0
    created = buf.getvalue().strip()
    assert "session_001" in created
    assert "smoke" in created

    buf2 = io.StringIO()
    with redirect_stdout(buf2):
        rc = main(["--config-dir", str(tmp_configs_dir), "session", "list"])
    assert rc == 0
    assert "smoke" in buf2.getvalue()
