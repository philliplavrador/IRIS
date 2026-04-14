"""Tests for ``iris.projects.artifacts`` — content-addressed store (§5.1)."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from iris.projects import artifacts
from iris.projects import events as events_mod
from iris.projects.db import connect, init_schema


def _make_project(conn: sqlite3.Connection, project_id: str = "p1") -> str:
    conn.execute(
        "INSERT INTO projects (project_id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (project_id, "demo", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
    )
    return project_id


@pytest.fixture
def project(tmp_path: Path):
    conn = connect(tmp_path)
    init_schema(conn)
    _make_project(conn)
    try:
        yield conn, tmp_path
    finally:
        conn.close()


# -- store / dedup ----------------------------------------------------------


def test_store_returns_sha256_as_artifact_id_and_writes_blob(
    project: tuple[sqlite3.Connection, Path],
) -> None:
    conn, root = project
    payload = b"\x89PNG\r\n\x1a\nfake-png-bytes"
    aid = artifacts.store(conn, root, content=payload, type="plot_png")

    expected_sha = hashlib.sha256(payload).hexdigest()
    assert aid == expected_sha

    blob_path = root / "artifacts" / expected_sha / "blob"
    assert blob_path.exists()
    assert blob_path.read_bytes() == payload

    row = conn.execute(
        "SELECT content_hash, storage_path, type FROM artifacts WHERE artifact_id = ?",
        (aid,),
    ).fetchone()
    assert row["content_hash"] == expected_sha
    assert row["storage_path"] == f"artifacts/{expected_sha}/blob"
    assert row["type"] == "plot_png"


def test_store_emits_artifact_created_event(
    project: tuple[sqlite3.Connection, Path],
) -> None:
    conn, root = project
    aid = artifacts.store(conn, root, content=b"hello", type="code_file")

    rows = conn.execute(
        "SELECT payload_json FROM events WHERE type = ?",
        (events_mod.EVT_ARTIFACT_CREATED,),
    ).fetchall()
    assert len(rows) == 1
    payload = json.loads(rows[0]["payload_json"])
    assert payload["artifact_id"] == aid
    assert payload["artifact_type"] == "code_file"
    assert payload["content_hash"] == aid


def test_store_dedups_same_bytes_to_single_row_and_file(
    project: tuple[sqlite3.Connection, Path],
) -> None:
    conn, root = project
    payload = b"identical bytes"
    a1 = artifacts.store(conn, root, content=payload, type="plot_png")
    a2 = artifacts.store(conn, root, content=payload, type="plot_png")
    assert a1 == a2

    (count,) = conn.execute(
        "SELECT count(*) FROM artifacts WHERE artifact_id = ?", (a1,)
    ).fetchone()
    assert count == 1

    # Only one directory on disk for this hash, containing one blob file.
    sha_dir = root / "artifacts" / a1
    files = list(sha_dir.iterdir())
    assert len(files) == 1
    assert files[0].name == "blob"

    # Dedup path does not emit a second event.
    (ev_count,) = conn.execute(
        "SELECT count(*) FROM events WHERE type = ?",
        (events_mod.EVT_ARTIFACT_CREATED,),
    ).fetchone()
    assert ev_count == 1


def test_store_different_bytes_produce_different_artifacts(
    project: tuple[sqlite3.Connection, Path],
) -> None:
    conn, root = project
    a1 = artifacts.store(conn, root, content=b"alpha", type="plot_png")
    a2 = artifacts.store(conn, root, content=b"beta", type="plot_png")
    assert a1 != a2
    assert (root / "artifacts" / a1 / "blob").exists()
    assert (root / "artifacts" / a2 / "blob").exists()


def test_store_rejects_unknown_type(
    project: tuple[sqlite3.Connection, Path],
) -> None:
    conn, root = project
    with pytest.raises(ValueError, match="unknown artifact type"):
        artifacts.store(conn, root, content=b"x", type="not_a_real_type")


def test_store_self_heals_missing_blob(
    project: tuple[sqlite3.Connection, Path],
) -> None:
    conn, root = project
    payload = b"need to heal"
    aid = artifacts.store(conn, root, content=payload, type="plot_png")
    blob = root / "artifacts" / aid / "blob"
    blob.unlink()
    assert not blob.exists()

    again = artifacts.store(conn, root, content=payload, type="plot_png")
    assert again == aid
    assert blob.exists()
    assert blob.read_bytes() == payload


# -- round-trip for all common types ----------------------------------------


@pytest.mark.parametrize(
    ("atype", "content", "metadata"),
    [
        ("plot_png", b"\x89PNG-stub", {"title": "trace", "dpi": 120}),
        ("plot_svg", b"<svg/>", {"width": 200}),
        ("report_html", b"<html><body>hi</body></html>", {"section": "summary"}),
        ("report_pdf", b"%PDF-1.4 stub", {"pages": 1}),
        ("slide_deck", b"PK\x03\x04 deck-stub", {"slides": 3}),
        ("code_file", b"def f():\n    return 1\n", {"lang": "python"}),
        ("cache_object", b"\x00\x01\x02cache", {"compressed": False}),
        ("data_export", b"a,b\n1,2\n", {"format": "csv"}),
        ("notebook", b'{"cells": []}', {"kernel": "python3"}),
    ],
)
def test_round_trip_all_artifact_types(
    project: tuple[sqlite3.Connection, Path],
    atype: str,
    content: bytes,
    metadata: dict,
) -> None:
    conn, root = project
    aid = artifacts.store(
        conn,
        root,
        content=content,
        type=atype,
        metadata=metadata,
        description=f"{atype} fixture",
    )
    assert artifacts.get_bytes(conn, root, aid) == content

    meta = artifacts.get_metadata(conn, aid)
    assert meta["artifact_id"] == aid
    assert meta["type"] == atype
    assert meta["content_hash"] == hashlib.sha256(content).hexdigest()
    assert meta["storage_path"] == f"artifacts/{aid}/blob"
    assert meta["metadata"] == metadata
    assert meta["description"] == f"{atype} fixture"
    assert meta["project_id"] == "p1"
    assert meta["created_at"]


def test_get_bytes_raises_for_unknown_id(
    project: tuple[sqlite3.Connection, Path],
) -> None:
    conn, root = project
    with pytest.raises(ValueError, match="does not exist"):
        artifacts.get_bytes(conn, root, "ghost")


def test_get_metadata_raises_for_unknown_id(
    project: tuple[sqlite3.Connection, Path],
) -> None:
    conn, _ = project
    with pytest.raises(ValueError, match="does not exist"):
        artifacts.get_metadata(conn, "ghost")


def test_get_metadata_handles_no_metadata(
    project: tuple[sqlite3.Connection, Path],
) -> None:
    conn, root = project
    aid = artifacts.store(conn, root, content=b"plain", type="code_file")
    meta = artifacts.get_metadata(conn, aid)
    assert meta["metadata"] is None
    assert meta["description"] is None


# -- list_artifacts ---------------------------------------------------------


def test_list_filters_by_type(
    project: tuple[sqlite3.Connection, Path],
) -> None:
    conn, root = project
    p1 = artifacts.store(conn, root, content=b"p1", type="plot_png")
    p2 = artifacts.store(conn, root, content=b"p2", type="plot_png")
    c1 = artifacts.store(conn, root, content=b"c1", type="code_file")

    pngs = artifacts.list_artifacts(conn, project_id="p1", type="plot_png")
    png_ids = {r["artifact_id"] for r in pngs}
    assert png_ids == {p1, p2}

    codes = artifacts.list_artifacts(conn, project_id="p1", type="code_file")
    assert {r["artifact_id"] for r in codes} == {c1}

    all_rows = artifacts.list_artifacts(conn, project_id="p1")
    assert {r["artifact_id"] for r in all_rows} == {p1, p2, c1}


def test_list_scopes_by_project_id(
    project: tuple[sqlite3.Connection, Path],
) -> None:
    conn, root = project
    aid = artifacts.store(conn, root, content=b"only-p1", type="plot_png")
    rows = artifacts.list_artifacts(conn, project_id="p1")
    assert {r["artifact_id"] for r in rows} == {aid}

    # Unknown project returns empty list.
    assert artifacts.list_artifacts(conn, project_id="not-a-project") == []


# -- soft_delete ------------------------------------------------------------


def test_soft_delete_sets_deleted_at_and_hides_from_list(
    project: tuple[sqlite3.Connection, Path],
) -> None:
    conn, root = project
    keep = artifacts.store(conn, root, content=b"keep", type="plot_png")
    gone = artifacts.store(conn, root, content=b"gone", type="plot_png")

    artifacts.soft_delete(conn, gone)

    (deleted_at,) = conn.execute(
        "SELECT deleted_at FROM artifacts WHERE artifact_id = ?", (gone,)
    ).fetchone()
    assert deleted_at is not None

    visible = artifacts.list_artifacts(conn, project_id="p1")
    assert {r["artifact_id"] for r in visible} == {keep}

    # Blob is preserved on disk for retention window.
    assert (root / "artifacts" / gone / "blob").exists()


def test_soft_delete_idempotent(
    project: tuple[sqlite3.Connection, Path],
) -> None:
    conn, root = project
    aid = artifacts.store(conn, root, content=b"x", type="plot_png")
    artifacts.soft_delete(conn, aid)
    (first_ts,) = conn.execute(
        "SELECT deleted_at FROM artifacts WHERE artifact_id = ?", (aid,)
    ).fetchone()
    artifacts.soft_delete(conn, aid)  # no-op
    (second_ts,) = conn.execute(
        "SELECT deleted_at FROM artifacts WHERE artifact_id = ?", (aid,)
    ).fetchone()
    assert first_ts == second_ts


def test_soft_delete_raises_for_unknown_id(
    project: tuple[sqlite3.Connection, Path],
) -> None:
    conn, _ = project
    with pytest.raises(ValueError, match="does not exist"):
        artifacts.soft_delete(conn, "ghost")
