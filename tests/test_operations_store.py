"""Tests for ``iris.projects.operations_store`` — catalog + executions + FTS."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from iris.projects import operations_store
from iris.projects.db import connect, init_schema


def _make_project(conn: sqlite3.Connection, project_id: str = "p1") -> str:
    conn.execute(
        "INSERT INTO projects (project_id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (project_id, "demo", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
    )
    return project_id


@pytest.fixture
def project_conn(tmp_path: Path):
    conn = connect(tmp_path)
    init_schema(conn)
    _make_project(conn)
    # ``operations.code_artifact_id`` is FK-bound to ``artifacts`` in the
    # schema, but V1 callers (including the startup cataloger in Task 8.2)
    # register ops before Phase 5 wires real artifact blobs. Mirror that
    # temporary relaxation here so the catalog exercises its own code path
    # without us having to manufacture an artifact row per test.
    conn.execute("PRAGMA foreign_keys=OFF")
    try:
        yield conn
    finally:
        conn.close()


def _sig(extra: dict | None = None) -> dict:
    base = {"input": {"x": "float"}, "output": {"y": "float"}}
    if extra:
        base.update(extra)
    return base


def test_register_returns_id_and_inserts_row(project_conn: sqlite3.Connection) -> None:
    op_id = operations_store.register(
        project_conn,
        project_id="p1",
        name="butter_bandpass",
        version="1.0.0",
        kind="hardcoded",
        signature_json=_sig(),
        docstring="Butterworth bandpass filter over a trace.",
    )
    assert isinstance(op_id, str) and len(op_id) == 32

    row = project_conn.execute(
        "SELECT name, version, validation_status, use_count FROM operations WHERE op_id = ?",
        (op_id,),
    ).fetchone()
    assert row["name"] == "butter_bandpass"
    assert row["version"] == "1.0.0"
    # hardcoded ops land pre-vetted.
    assert row["validation_status"] == "validated"
    assert row["use_count"] == 0


def test_register_emits_operation_created_event(project_conn: sqlite3.Connection) -> None:
    op_id = operations_store.register(
        project_conn,
        project_id="p1",
        name="spectrogram",
        version="1.0.0",
        kind="hardcoded",
        signature_json=_sig(),
        docstring="STFT power spectrogram.",
    )
    evt = project_conn.execute(
        "SELECT type, payload_json FROM events WHERE project_id = ? ORDER BY ts DESC LIMIT 1",
        ("p1",),
    ).fetchone()
    assert evt["type"] == "operation_created"
    assert op_id in evt["payload_json"]
    assert "spectrogram" in evt["payload_json"]


def test_register_mirrors_fts_shadow(project_conn: sqlite3.Connection) -> None:
    operations_store.register(
        project_conn,
        project_id="p1",
        name="butter_bandpass",
        version="1.0.0",
        kind="hardcoded",
        signature_json=_sig(),
        docstring="Butterworth bandpass filter over a trace.",
    )
    (n,) = project_conn.execute(
        "SELECT count(*) FROM operations_fts WHERE operations_fts MATCH 'butterworth'",
    ).fetchone()
    assert n == 1


def test_register_unknown_kind_rejected(project_conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError, match="unknown kind"):
        operations_store.register(
            project_conn,
            project_id="p1",
            name="x",
            version="1.0.0",
            kind="bogus",
            signature_json=_sig(),
            docstring="d",
        )


def test_register_is_idempotent_on_name_version(project_conn: sqlite3.Connection) -> None:
    op_id_1 = operations_store.register(
        project_conn,
        project_id="p1",
        name="butter_bandpass",
        version="1.0.0",
        kind="hardcoded",
        signature_json=_sig(),
        docstring="Butterworth bandpass filter.",
    )
    op_id_2 = operations_store.register(
        project_conn,
        project_id="p1",
        name="butter_bandpass",
        version="1.0.0",
        kind="hardcoded",
        signature_json=_sig(),
        docstring="Butterworth bandpass filter.",
    )
    assert op_id_1 == op_id_2

    (n,) = project_conn.execute(
        "SELECT count(*) FROM operations WHERE name = ? AND version = ?",
        ("butter_bandpass", "1.0.0"),
    ).fetchone()
    assert n == 1

    # A different version of the same op is NOT idempotent — it's a new row.
    op_id_v2 = operations_store.register(
        project_conn,
        project_id="p1",
        name="butter_bandpass",
        version="1.1.0",
        kind="hardcoded",
        signature_json=_sig(),
        docstring="Butterworth bandpass filter (tweaked).",
    )
    assert op_id_v2 != op_id_1


def test_find_by_exact_version(project_conn: sqlite3.Connection) -> None:
    op_id_a = operations_store.register(
        project_conn,
        project_id="p1",
        name="spectrogram",
        version="1.0.0",
        kind="hardcoded",
        signature_json=_sig(),
        docstring="v1",
    )
    op_id_b = operations_store.register(
        project_conn,
        project_id="p1",
        name="spectrogram",
        version="1.1.0",
        kind="hardcoded",
        signature_json=_sig(),
        docstring="v2",
    )
    hit = operations_store.find(project_conn, project_id="p1", name="spectrogram", version="1.0.0")
    assert hit is not None
    assert hit["op_id"] == op_id_a

    # version=None resolves latest by created_at — b was inserted after a.
    latest = operations_store.find(project_conn, project_id="p1", name="spectrogram")
    assert latest is not None
    assert latest["op_id"] == op_id_b


def test_find_returns_none_when_missing(project_conn: sqlite3.Connection) -> None:
    assert operations_store.find(project_conn, project_id="p1", name="nope") is None


def test_list_filters_by_status(project_conn: sqlite3.Connection) -> None:
    # hardcoded -> validated
    operations_store.register(
        project_conn,
        project_id="p1",
        name="hard_op",
        version="1.0.0",
        kind="hardcoded",
        signature_json=_sig(),
        docstring="hard",
    )
    # generated -> draft
    operations_store.register(
        project_conn,
        project_id="p1",
        name="gen_op",
        version="1.0.0",
        kind="generated",
        signature_json=_sig(),
        docstring="gen",
    )

    active = operations_store.list(project_conn, project_id="p1", status="active")
    assert [r["name"] for r in active] == ["hard_op"]

    drafts = operations_store.list(project_conn, project_id="p1", status="draft")
    assert [r["name"] for r in drafts] == ["gen_op"]


def test_list_accepts_kind_filter_without_error(project_conn: sqlite3.Connection) -> None:
    # kind is a V1 no-op filter, but the argument must still be accepted.
    operations_store.register(
        project_conn,
        project_id="p1",
        name="op",
        version="1.0.0",
        kind="hardcoded",
        signature_json=_sig(),
        docstring="d",
    )
    rows = operations_store.list(project_conn, project_id="p1", kind="hardcoded", status="active")
    assert len(rows) == 1


def test_search_returns_bm25_ordered_hits(project_conn: sqlite3.Connection) -> None:
    operations_store.register(
        project_conn,
        project_id="p1",
        name="butter_bandpass",
        version="1.0.0",
        kind="hardcoded",
        signature_json=_sig(),
        docstring="Butterworth bandpass filter for neural traces.",
    )
    operations_store.register(
        project_conn,
        project_id="p1",
        name="spectrogram",
        version="1.0.0",
        kind="hardcoded",
        signature_json=_sig(),
        docstring="STFT spectrogram — not a filter at all.",
    )
    operations_store.register(
        project_conn,
        project_id="p1",
        name="notch",
        version="1.0.0",
        kind="hardcoded",
        signature_json=_sig(),
        docstring="Notch filter around 60 Hz.",
    )

    hits = operations_store.search(project_conn, project_id="p1", query="bandpass filter", limit=10)
    assert len(hits) >= 1
    # Top hit must be the butter_bandpass op — it contains both terms.
    assert hits[0]["name"] == "butter_bandpass"
    # BM25 scores are ascending (lower = better).
    scores = [h["score"] for h in hits]
    assert scores == sorted(scores)


def test_search_scopes_to_project(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    init_schema(conn)
    _make_project(conn, "p1")
    _make_project(conn, "p2")
    conn.execute("PRAGMA foreign_keys=OFF")

    operations_store.register(
        conn,
        project_id="p1",
        name="butter_bandpass",
        version="1.0.0",
        kind="hardcoded",
        signature_json=_sig(),
        docstring="Butterworth filter in p1.",
    )
    operations_store.register(
        conn,
        project_id="p2",
        name="butter_bandpass",
        version="1.0.0",
        kind="hardcoded",
        signature_json=_sig(),
        docstring="Butterworth filter in p2.",
    )

    hits = operations_store.search(conn, project_id="p1", query="butterworth", limit=10)
    assert len(hits) == 1
    assert hits[0]["project_id"] == "p1"
    conn.close()


def test_record_execution_inserts_row_and_updates_aggregates(
    project_conn: sqlite3.Connection,
) -> None:
    op_id = operations_store.register(
        project_conn,
        project_id="p1",
        name="butter_bandpass",
        version="1.0.0",
        kind="hardcoded",
        signature_json=_sig(),
        docstring="d",
    )
    exec_id = operations_store.record_execution(
        project_conn,
        operation_id=op_id,
        run_id=None,
        inputs_hash="abc",
        success=True,
        execution_time_ms=42,
    )
    assert isinstance(exec_id, str) and len(exec_id) == 32

    row = project_conn.execute(
        "SELECT op_id, success, execution_time_ms FROM operation_executions WHERE execution_id = ?",
        (exec_id,),
    ).fetchone()
    assert row["op_id"] == op_id
    assert row["success"] == 1
    assert row["execution_time_ms"] == 42

    agg = project_conn.execute(
        "SELECT use_count, success_rate, last_used_at FROM operations WHERE op_id = ?",
        (op_id,),
    ).fetchone()
    assert agg["use_count"] == 1
    assert agg["success_rate"] == 1.0
    assert agg["last_used_at"] is not None

    # One failure flips success_rate to 0.5.
    operations_store.record_execution(
        project_conn,
        operation_id=op_id,
        run_id=None,
        inputs_hash="def",
        success=False,
        execution_time_ms=10,
    )
    agg2 = project_conn.execute(
        "SELECT use_count, success_rate FROM operations WHERE op_id = ?",
        (op_id,),
    ).fetchone()
    assert agg2["use_count"] == 2
    assert agg2["success_rate"] == 0.5


def test_record_execution_emits_transform_run_event(
    project_conn: sqlite3.Connection,
) -> None:
    op_id = operations_store.register(
        project_conn,
        project_id="p1",
        name="butter_bandpass",
        version="1.0.0",
        kind="hardcoded",
        signature_json=_sig(),
        docstring="d",
    )
    # Clear the create-event noise so the assertion below is unambiguous.
    project_conn.execute("DELETE FROM events WHERE project_id = ?", ("p1",))

    operations_store.record_execution(
        project_conn,
        operation_id=op_id,
        run_id=None,
        inputs_hash="abc",
        success=True,
        execution_time_ms=5,
    )

    evt = project_conn.execute(
        "SELECT type, payload_json FROM events WHERE project_id = ? ORDER BY ts DESC LIMIT 1",
        ("p1",),
    ).fetchone()
    assert evt["type"] == "transform_run"
    assert "operation_executed" in evt["payload_json"]
    assert op_id in evt["payload_json"]
