"""Tests for ``iris.projects.transformations`` — derived versions + lineage."""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

import pytest

from iris.projects.datasets import import_dataset
from iris.projects.db import connect, init_schema
from iris.projects.transformations import (
    lineage,
    list_versions,
    record_derived_version,
)


def _make_project(conn: sqlite3.Connection, project_id: str = "p1") -> str:
    conn.execute(
        "INSERT INTO projects (project_id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (project_id, "demo", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
    )
    return project_id


def _fake_artifact(conn: sqlite3.Connection, project_id: str = "p1") -> str:
    """Insert an ``artifacts`` row and return its id (bypasses Phase 6.4)."""
    artifact_id = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO artifacts ("
        "artifact_id, project_id, type, created_at, content_hash, storage_path, "
        "metadata_json, description) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            artifact_id,
            project_id,
            "data_export",
            "2026-02-01T00:00:00Z",
            "a" * 64,
            f"artifacts/{artifact_id}/out.parquet",
            None,
            None,
        ),
    )
    return artifact_id


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


def _make_raw(
    conn: sqlite3.Connection, project_path: Path, tmp_path: Path, name: str = "raw.csv"
) -> tuple[str, str]:
    src = tmp_path / name
    src.write_bytes(b"col\n1\n2\n")
    return import_dataset(conn, project_path, source_path=src, name="raw")


def test_record_derived_version_links_to_parent(
    project_setup: tuple[sqlite3.Connection, Path], tmp_path: Path
) -> None:
    conn, project_path = project_setup
    dataset_id, raw_version = _make_raw(conn, project_path, tmp_path)
    artifact_id = _fake_artifact(conn)

    derived_id = record_derived_version(
        conn,
        dataset_id=dataset_id,
        parent_version_id=raw_version,
        transform_name="butter_bandpass",
        transform_params={"low": 300, "high": 3000},
        artifact_id=artifact_id,
        description="300-3000 Hz",
    )

    row = conn.execute(
        "SELECT derived_from_dataset_version_id, content_hash, storage_path, description "
        "FROM dataset_versions WHERE dataset_version_id = ?",
        (derived_id,),
    ).fetchone()
    assert row["derived_from_dataset_version_id"] == raw_version
    assert row["content_hash"] == "a" * 64
    assert row["storage_path"].startswith("artifacts/")
    # Description is packed with a canonical-JSON header.
    assert "butter_bandpass" in row["description"]
    assert "300-3000 Hz" in row["description"]


def test_lineage_recursive_chain_leaf_to_root(
    project_setup: tuple[sqlite3.Connection, Path], tmp_path: Path
) -> None:
    conn, project_path = project_setup
    dataset_id, raw_version = _make_raw(conn, project_path, tmp_path)
    a1 = _fake_artifact(conn)
    a2 = _fake_artifact(conn)

    v1 = record_derived_version(
        conn,
        dataset_id=dataset_id,
        parent_version_id=raw_version,
        transform_name="trim",
        transform_params={"start": 0, "end": 10},
        artifact_id=a1,
    )
    v2 = record_derived_version(
        conn,
        dataset_id=dataset_id,
        parent_version_id=v1,
        transform_name="resample",
        transform_params={"fs": 1000},
        artifact_id=a2,
    )

    chain = lineage(conn, v2)
    ids = [row["dataset_version_id"] for row in chain]
    # Leaf-to-root: v2 -> v1 -> raw.
    assert ids == [v2, v1, raw_version]
    assert chain[-1]["derived_from_dataset_version_id"] is None

    # list_versions returns chronological (raw first, derived after).
    listed = [r["dataset_version_id"] for r in list_versions(conn, dataset_id=dataset_id)]
    assert listed == [raw_version, v1, v2]


def test_record_rejects_mismatched_parent(
    project_setup: tuple[sqlite3.Connection, Path], tmp_path: Path
) -> None:
    conn, project_path = project_setup
    dataset_a, raw_a = _make_raw(conn, project_path, tmp_path, "a.csv")
    dataset_b, _raw_b = _make_raw(conn, project_path, tmp_path, "b.csv")
    artifact_id = _fake_artifact(conn)

    with pytest.raises(ValueError, match="belongs to dataset"):
        record_derived_version(
            conn,
            dataset_id=dataset_b,
            parent_version_id=raw_a,
            transform_name="noop",
            transform_params={},
            artifact_id=artifact_id,
        )


def test_lineage_returns_empty_for_unknown_version(
    project_setup: tuple[sqlite3.Connection, Path],
) -> None:
    conn, _ = project_setup
    assert lineage(conn, "deadbeef") == []
