"""Tests for ``iris.projects.op_validation``."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from iris.projects import op_validation
from iris.projects import operations_store as ops_store
from iris.projects.db import connect, init_schema


def _make_project(conn: sqlite3.Connection) -> str:
    conn.execute(
        "INSERT INTO projects (project_id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
        ("p1", "demo", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
    )
    return "p1"


def _insert_op(conn: sqlite3.Connection) -> str:
    return ops_store.register(
        conn,
        project_id="p1",
        name="my_op",
        version="1.0.0",
        kind="generated",
        signature_json={"input": {}, "output": {}},
        docstring="test op",
    )


@pytest.fixture
def conn(tmp_path: Path):
    c = connect(tmp_path)
    init_schema(c)
    _make_project(c)
    # Relax artifact FK so tests can register ops without manufacturing
    # artifact rows — matches the pattern in test_operations_store.py.
    c.execute("PRAGMA foreign_keys=OFF")
    try:
        yield c
    finally:
        c.close()


def test_static_rejects_syntax_error(conn: sqlite3.Connection) -> None:
    op_id = _insert_op(conn)
    result = op_validation.validate_operation(conn, op_id, source_code="def run(:\n  return 1")
    assert result["ok"] is False
    assert result["stage"] == "static"
    row = conn.execute(
        "SELECT validation_status FROM operations WHERE op_id = ?", (op_id,)
    ).fetchone()
    assert row[0] == "rejected"


def test_static_accepts_well_formed_code(conn: sqlite3.Connection) -> None:
    op_id = _insert_op(conn)
    result = op_validation.validate_operation(
        conn, op_id, source_code="def run(x):\n    return x + 1\n"
    )
    assert result["ok"] is True
    row = conn.execute(
        "SELECT validation_status, validated_at FROM operations WHERE op_id = ?",
        (op_id,),
    ).fetchone()
    assert row[0] == "validated"
    assert row[1] is not None


def test_sample_run_success(conn: sqlite3.Connection) -> None:
    op_id = _insert_op(conn)
    result = op_validation.validate_operation(
        conn,
        op_id,
        source_code="def run(x):\n    return x * 2\n",
        sample_input={"x": 3},
    )
    assert result["ok"] is True


def test_sample_run_failure_rejects(conn: sqlite3.Connection) -> None:
    op_id = _insert_op(conn)
    result = op_validation.validate_operation(
        conn,
        op_id,
        source_code="def run(x):\n    raise RuntimeError('boom')\n",
        sample_input={"x": 1},
    )
    assert result["ok"] is False
    assert result["stage"] == "sample"
    row = conn.execute(
        "SELECT validation_status FROM operations WHERE op_id = ?", (op_id,)
    ).fetchone()
    assert row[0] == "rejected"


def test_missing_source_rejected(conn: sqlite3.Connection) -> None:
    op_id = _insert_op(conn)
    result = op_validation.validate_operation(conn, op_id)
    # No artifact backing the op, no source_code kwarg → rejected.
    assert result["ok"] is False
    assert result["stage"] == "static"
