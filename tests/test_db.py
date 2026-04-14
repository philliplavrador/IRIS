"""Tests for ``iris.projects.db`` — connection helper + schema migration.

Covers the Task 1.4 checklist:
- schema applies cleanly to a fresh project path
- ``init_schema`` is idempotent (re-run is a no-op)
- foreign keys are enforced (violating insert raises)
- WAL sidecar files appear after the first write
- all FTS5 virtual tables are queryable
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from iris.projects.db import (
    DB_FILENAME,
    SCHEMA_VERSION,
    connect,
    current_version,
    init_schema,
    migrate,
)

# The spec §7.1 V1 base tables (12) + the 3 FTS5 virtual tables.
EXPECTED_BASE_TABLES = {
    "projects",
    "sessions",
    "events",
    "messages",
    "tool_calls",
    "datasets",
    "dataset_versions",
    "artifacts",
    "runs",
    "memory_entries",
    "contradictions",
    "operations",
    "operation_executions",
    "user_preferences",
}

EXPECTED_FTS_TABLES = {
    "messages_fts",
    "memory_entries_fts",
    "operations_fts",
}


def _all_table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {row[0] for row in rows}


def test_schema_applies_cleanly(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    try:
        init_schema(conn)
        assert (tmp_path / DB_FILENAME).exists()
        assert current_version(conn) == SCHEMA_VERSION

        tables = _all_table_names(conn)
        missing_base = EXPECTED_BASE_TABLES - tables
        assert not missing_base, f"missing base tables: {missing_base}"
        missing_fts = EXPECTED_FTS_TABLES - tables
        assert not missing_fts, f"missing FTS5 tables: {missing_fts}"
    finally:
        conn.close()


def test_init_schema_is_idempotent(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    try:
        init_schema(conn)
        first_tables = _all_table_names(conn)
        first_version = current_version(conn)

        # Second call must not raise (would raise "table X already exists"
        # if schema.sql were executed twice) and must leave state unchanged.
        init_schema(conn)
        assert _all_table_names(conn) == first_tables
        assert current_version(conn) == first_version == SCHEMA_VERSION

        # migrate() to the current version is also a no-op.
        migrate(conn, SCHEMA_VERSION)
        assert current_version(conn) == SCHEMA_VERSION
    finally:
        conn.close()


def test_foreign_keys_enforced(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    try:
        init_schema(conn)

        # sessions.project_id FK → projects.project_id. Inserting a session
        # whose project_id has no matching projects row must raise.
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO sessions (session_id, project_id, started_at) VALUES (?, ?, ?)",
                ("sess-1", "nonexistent-project", "2026-01-01T00:00:00Z"),
            )
    finally:
        conn.close()


def test_wal_sidecar_files_appear_after_write(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    try:
        init_schema(conn)
        # Force a durable write so WAL machinery engages.
        conn.execute(
            "INSERT INTO projects (project_id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
            ("p1", "demo", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
        )
        db_path = tmp_path / DB_FILENAME
        wal_path = db_path.with_name(db_path.name + "-wal")
        shm_path = db_path.with_name(db_path.name + "-shm")
        assert wal_path.exists(), "WAL file should exist while writer is open"
        assert shm_path.exists(), "SHM file should exist while writer is open"
    finally:
        conn.close()


def test_all_fts_tables_are_queryable(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    try:
        init_schema(conn)
        for fts in EXPECTED_FTS_TABLES:
            # An empty MATCH query against an empty FTS5 table should return
            # zero rows without error — this proves the virtual table is
            # wired up and its shadow tables exist.
            rows = conn.execute(
                f"SELECT rowid FROM {fts} WHERE {fts} MATCH ?",
                ("anything",),
            ).fetchall()
            assert rows == []
    finally:
        conn.close()
