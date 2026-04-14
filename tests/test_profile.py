"""Tests for ``iris.projects.profile`` — schema inference + draft proposals."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from iris.projects import events as events_mod
from iris.projects import memory_entries as memory_mod
from iris.projects.datasets import import_dataset
from iris.projects.db import connect, init_schema
from iris.projects.profile import profile_dataset


def _make_project(conn: sqlite3.Connection, project_id: str = "p1") -> str:
    conn.execute(
        "INSERT INTO projects (project_id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (project_id, "demo", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
    )
    return project_id


@pytest.fixture
def project_setup(tmp_path: Path):
    project_path = tmp_path / "proj"
    project_path.mkdir()
    conn = connect(project_path)
    init_schema(conn)
    _make_project(conn)
    try:
        yield conn, project_path
    finally:
        conn.close()


def test_profile_tiny_csv_populates_schema_and_proposes_drafts(
    project_setup: tuple[sqlite3.Connection, Path], tmp_path: Path
) -> None:
    pd = pytest.importorskip("pandas")

    # Write a synthetic CSV via pandas so the file format matches what
    # ``_profile_csv`` will read back.
    src = tmp_path / "sig.csv"
    df = pd.DataFrame(
        {
            "time_s": [0.0, 0.001, 0.002, 0.003, 0.004],
            "channel": [1, 1, 2, 2, 3],
            "voltage_uv": [-12.4, 5.1, 22.0, -3.3, 17.6],
        }
    )
    df.to_csv(src, index=False)

    conn, project_path = project_setup
    dataset_id, version_id = import_dataset(conn, project_path, source_path=src, name="sig")

    result = profile_dataset(conn, project_path, dataset_id=dataset_id, version_id=version_id)

    # Returned payload structure is sane.
    assert result["n_rows"] == 5
    col_names = [c["name"] for c in result["columns"]]
    assert col_names == ["time_s", "channel", "voltage_uv"]
    # Numeric columns carry min/max annotations.
    voltage_col = next(c for c in result["columns"] if c["name"] == "voltage_uv")
    assert "min" in voltage_col and "max" in voltage_col
    assert voltage_col["non_null_count"] == 5

    # schema_json + row_count landed on the dataset_versions row.
    row = conn.execute(
        "SELECT schema_json, row_count FROM dataset_versions WHERE dataset_version_id = ?",
        (version_id,),
    ).fetchone()
    assert row["row_count"] == 5
    decoded = json.loads(row["schema_json"])
    assert [c["name"] for c in decoded["columns"]] == col_names

    # ``dataset_profiled`` event was written.
    (evt_count,) = conn.execute(
        "SELECT count(*) FROM events WHERE type = ?",
        (events_mod.EVT_DATASET_PROFILED,),
    ).fetchone()
    assert evt_count == 1

    # One draft memory_entry per column, scoped to this dataset.
    drafts = memory_mod.query(
        conn,
        project_id="p1",
        status="draft",
        scope="dataset",
        dataset_id=dataset_id,
    )
    assert len(drafts) == len(col_names)
    draft_texts = [d["text"] for d in drafts]
    for name in col_names:
        assert any(name in text for text in draft_texts)


def test_profile_parquet_populates_schema_and_proposes_drafts(
    project_setup: tuple[sqlite3.Connection, Path], tmp_path: Path
) -> None:
    pd = pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")

    src = tmp_path / "sig.parquet"
    df = pd.DataFrame(
        {
            "t": [0.0, 0.1, 0.2],
            "label": ["a", "b", "a"],
        }
    )
    df.to_parquet(src, index=False)

    conn, project_path = project_setup
    dataset_id, version_id = import_dataset(conn, project_path, source_path=src, name="sig_pq")

    result = profile_dataset(conn, project_path, dataset_id=dataset_id, version_id=version_id)

    assert result["n_rows"] == 3
    col_names = [c["name"] for c in result["columns"]]
    assert col_names == ["t", "label"]

    row = conn.execute(
        "SELECT schema_json, row_count FROM dataset_versions WHERE dataset_version_id = ?",
        (version_id,),
    ).fetchone()
    assert row["row_count"] == 3
    assert json.loads(row["schema_json"])["suffix"] == ".parquet"

    drafts = memory_mod.query(
        conn,
        project_id="p1",
        status="draft",
        scope="dataset",
        dataset_id=dataset_id,
    )
    assert len(drafts) == len(col_names)


def test_profile_rejects_mismatched_version(
    project_setup: tuple[sqlite3.Connection, Path], tmp_path: Path
) -> None:
    pytest.importorskip("pandas")
    conn, project_path = project_setup
    src = tmp_path / "x.csv"
    src.write_bytes(b"a\n1\n")
    dataset_id, version_id = import_dataset(conn, project_path, source_path=src, name="x")
    with pytest.raises(LookupError):
        profile_dataset(conn, project_path, dataset_id="different", version_id=version_id)
    with pytest.raises(LookupError):
        profile_dataset(conn, project_path, dataset_id=dataset_id, version_id="no-such-version")
