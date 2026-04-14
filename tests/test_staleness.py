"""Tests for ``iris.projects.staleness``."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from iris.projects import memory_entries as me
from iris.projects import staleness
from iris.projects.db import connect, init_schema


def _make_project(conn: sqlite3.Connection) -> str:
    conn.execute(
        "INSERT INTO projects (project_id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
        ("p1", "demo", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
    )
    return "p1"


@pytest.fixture
def conn(tmp_path: Path):
    c = connect(tmp_path)
    init_schema(c)
    _make_project(c)
    try:
        yield c
    finally:
        c.close()


def _plant(
    conn: sqlite3.Connection,
    memory_type: str,
    *,
    created_days_ago: int,
) -> str:
    mid = me.propose(
        conn,
        project_id="p1",
        scope="project",
        memory_type=memory_type,
        text=f"{memory_type} memory aged {created_days_ago}d",
        importance=5.0,
    )
    me.commit_pending(conn, [mid])
    # Backdate created_at to simulate age.
    old = (datetime.now(UTC) - timedelta(days=created_days_ago)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    conn.execute(
        "UPDATE memory_entries SET created_at = ? WHERE memory_id = ?",
        (old, mid),
    )
    return mid


def test_scan_flips_old_findings(conn: sqlite3.Connection) -> None:
    fresh = _plant(conn, "finding", created_days_ago=10)
    aged = _plant(conn, "finding", created_days_ago=120)

    flipped = staleness.scan(conn, "p1")
    assert flipped == [aged]
    assert (
        conn.execute("SELECT status FROM memory_entries WHERE memory_id = ?", (aged,)).fetchone()[0]
        == "stale"
    )
    assert (
        conn.execute("SELECT status FROM memory_entries WHERE memory_id = ?", (fresh,)).fetchone()[
            0
        ]
        == "active"
    )


def test_scan_respects_type_thresholds(conn: sqlite3.Connection) -> None:
    # Assumption is 30d default — 50d old should flip; 10d shouldn't.
    fresh = _plant(conn, "assumption", created_days_ago=10)
    aged = _plant(conn, "assumption", created_days_ago=50)
    flipped = set(staleness.scan(conn, "p1"))
    assert aged in flipped
    assert fresh not in flipped


def test_scan_skips_types_without_threshold(conn: sqlite3.Connection) -> None:
    mid = _plant(conn, "preference", created_days_ago=365)
    flipped = staleness.scan(conn, "p1")
    assert mid not in flipped


def test_scan_accepts_custom_thresholds(conn: sqlite3.Connection) -> None:
    mid = _plant(conn, "finding", created_days_ago=5)
    flipped = staleness.scan(conn, "p1", thresholds={"finding": 1})
    assert flipped == [mid]


def test_format_for_retrieval_stale_prefix() -> None:
    row = {
        "status": "stale",
        "memory_type": "finding",
        "text": "bandpass is 300 Hz",
        "last_validated_at": "2024-11-15T00:00:00Z",
    }
    out = staleness.format_for_retrieval(row)
    assert "may need revalidation" in out
    assert "2024-11-15" in out
    assert "bandpass is 300 Hz" in out


def test_format_for_retrieval_passes_active_through() -> None:
    row = {"status": "active", "text": "whatever"}
    assert staleness.format_for_retrieval(row) == "whatever"
