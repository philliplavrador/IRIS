"""Tests for ``iris.projects.contradictions``."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from iris.projects import contradictions
from iris.projects import memory_entries as me
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


def _plant(conn: sqlite3.Connection, text: str) -> str:
    mid = me.propose(
        conn,
        project_id="p1",
        scope="project",
        memory_type="finding",
        text=text,
        importance=5.0,
    )
    me.commit_pending(conn, [mid])
    return mid


def test_detect_no_candidates_returns_empty(conn: sqlite3.Connection) -> None:
    # With only the new memory present, there are no candidates to compare.
    mid = _plant(conn, "bandpass is 300 Hz")
    assert contradictions.detect_contradictions(conn, mid, llm_fn=lambda _p: "whatever") == []


def test_detect_flags_contradicting_memory(conn: sqlite3.Connection) -> None:
    old = _plant(conn, "bandpass is 300 Hz")
    new = _plant(conn, "bandpass is actually 500 Hz")

    def fake(prompt: str) -> str:
        assert old in prompt
        return old  # LLM returns the contradicting memory's id

    hits = contradictions.detect_contradictions(conn, new, llm_fn=fake)
    assert hits == [old]

    # Old memory flipped to contradicted
    row = conn.execute("SELECT status FROM memory_entries WHERE memory_id = ?", (old,)).fetchone()
    assert row[0] == "contradicted"

    # Contradiction row inserted
    rows = contradictions.list_contradictions(conn, project_id="p1", resolved=False)
    assert len(rows) == 1
    assert rows[0]["memory_id_a"] == new
    assert rows[0]["memory_id_b"] == old


def test_detect_ignores_unknown_ids_from_llm(conn: sqlite3.Connection) -> None:
    _plant(conn, "bandpass is 300 Hz")
    new = _plant(conn, "bandpass is actually 500 Hz")
    hits = contradictions.detect_contradictions(
        conn, new, llm_fn=lambda _p: "not-a-real-id\nanother-bogus-id"
    )
    assert hits == []


def test_resolve_winner_loser(conn: sqlite3.Connection) -> None:
    old = _plant(conn, "bandpass is 300 Hz")
    new = _plant(conn, "bandpass is 500 Hz")
    contradictions.detect_contradictions(conn, new, llm_fn=lambda _p: old)
    (cid,) = conn.execute("SELECT contradiction_id FROM contradictions LIMIT 1").fetchone()

    contradictions.resolve(conn, cid, resolution_text="500 Hz is correct", winning_memory_id=new)

    row = conn.execute(
        "SELECT resolved, resolution_text FROM contradictions WHERE contradiction_id = ?",
        (cid,),
    ).fetchone()
    assert row[0] == 1
    assert "500 Hz" in row[1]

    winner_status = conn.execute(
        "SELECT status FROM memory_entries WHERE memory_id = ?", (new,)
    ).fetchone()[0]
    loser_status = conn.execute(
        "SELECT status FROM memory_entries WHERE memory_id = ?", (old,)
    ).fetchone()[0]
    assert winner_status == "active"
    assert loser_status == "contradicted"


def test_resolve_rejects_unrelated_winner(conn: sqlite3.Connection) -> None:
    old = _plant(conn, "x")
    new = _plant(conn, "y")
    contradictions.detect_contradictions(conn, new, llm_fn=lambda _p: old)
    (cid,) = conn.execute("SELECT contradiction_id FROM contradictions LIMIT 1").fetchone()
    with pytest.raises(ValueError, match="must be one of"):
        contradictions.resolve(
            conn,
            cid,
            resolution_text="???",
            winning_memory_id="not-a-real-id",
        )
