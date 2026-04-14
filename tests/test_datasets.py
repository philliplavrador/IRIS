"""Tests for ``iris.projects.datasets`` — raw import + dedup + lookups."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from iris.projects import events as events_mod
from iris.projects.datasets import (
    RAW_SUBDIR,
    get_dataset,
    get_version,
    import_dataset,
    list_datasets,
)
from iris.projects.db import connect, init_schema


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


def _write_source(tmp_path: Path, name: str, content: bytes) -> Path:
    src = tmp_path / name
    src.write_bytes(content)
    return src


def test_import_writes_file_row_version_and_event(
    project_setup: tuple[sqlite3.Connection, Path], tmp_path: Path
) -> None:
    conn, project_path = project_setup
    src = _write_source(tmp_path, "data.csv", b"a,b\n1,2\n3,4\n")

    dataset_id, version_id = import_dataset(
        conn, project_path, source_path=src, name="demo", description="hello"
    )
    assert isinstance(dataset_id, str) and len(dataset_id) == 32
    assert isinstance(version_id, str) and len(version_id) == 32

    # File was copied into the content-addressed raw store.
    ds_row = get_dataset(conn, dataset_id)
    assert ds_row is not None
    assert ds_row["original_filename"] == "data.csv"
    assert ds_row["project_id"] == "p1"

    ver = get_version(conn, version_id)
    assert ver is not None
    assert ver["dataset_id"] == dataset_id
    assert ver["derived_from_dataset_version_id"] is None
    assert ver["transform_run_id"] is None
    assert ver["description"] == "hello"
    assert ver["storage_path"].startswith(RAW_SUBDIR + "/")
    on_disk = project_path / ver["storage_path"]
    assert on_disk.is_file()
    assert on_disk.read_bytes() == src.read_bytes()

    # A ``dataset_import`` event was appended.
    ev_rows = conn.execute(
        "SELECT payload_json FROM events WHERE type = ?",
        (events_mod.EVT_DATASET_IMPORT,),
    ).fetchall()
    assert len(ev_rows) == 1
    assert dataset_id in ev_rows[0][0]
    assert version_id in ev_rows[0][0]


def test_import_dedupes_identical_content_on_disk(
    project_setup: tuple[sqlite3.Connection, Path], tmp_path: Path
) -> None:
    conn, project_path = project_setup
    payload = b"col\n1\n2\n3\n"
    src_a = _write_source(tmp_path, "a.csv", payload)
    src_b = _write_source(tmp_path, "b.csv", payload)  # same bytes, new name

    ds_a, ver_a = import_dataset(conn, project_path, source_path=src_a, name="A")
    ds_b, ver_b = import_dataset(conn, project_path, source_path=src_b, name="B")

    va = get_version(conn, ver_a)
    vb = get_version(conn, ver_b)
    assert va is not None and vb is not None
    # Two distinct logical datasets + versions, but both point at files whose
    # bytes hash identically — the content-addressed directory is reused.
    assert ds_a != ds_b
    assert ver_a != ver_b
    assert va["content_hash"] == vb["content_hash"]
    # Same directory, different filename subpaths (a.csv vs b.csv).
    dir_a = (project_path / va["storage_path"]).parent
    dir_b = (project_path / vb["storage_path"]).parent
    assert dir_a == dir_b


def test_reimport_same_file_reuses_raw_blob(
    project_setup: tuple[sqlite3.Connection, Path], tmp_path: Path
) -> None:
    conn, project_path = project_setup
    src = _write_source(tmp_path, "d.csv", b"x\n1\n")

    _, ver1 = import_dataset(conn, project_path, source_path=src, name="first")
    _, ver2 = import_dataset(conn, project_path, source_path=src, name="second")
    v1 = get_version(conn, ver1)
    v2 = get_version(conn, ver2)
    assert v1 is not None and v2 is not None
    assert v1["storage_path"] == v2["storage_path"]  # same file reused
    assert (project_path / v1["storage_path"]).is_file()


def test_list_and_get_roundtrip(
    project_setup: tuple[sqlite3.Connection, Path], tmp_path: Path
) -> None:
    conn, project_path = project_setup
    src1 = _write_source(tmp_path, "one.csv", b"1")
    src2 = _write_source(tmp_path, "two.csv", b"2")
    d1, _ = import_dataset(conn, project_path, source_path=src1, name="one")
    d2, _ = import_dataset(conn, project_path, source_path=src2, name="two")

    rows = list_datasets(conn, project_id="p1")
    ids = {r["dataset_id"] for r in rows}
    assert ids == {d1, d2}
    assert get_dataset(conn, d1)["name"] == "one"
    assert get_dataset(conn, "nope-nope") is None
    assert get_version(conn, "nope-nope") is None


def test_missing_source_raises(
    project_setup: tuple[sqlite3.Connection, Path], tmp_path: Path
) -> None:
    conn, project_path = project_setup
    with pytest.raises(FileNotFoundError):
        import_dataset(conn, project_path, source_path=tmp_path / "nope.csv", name="x")
