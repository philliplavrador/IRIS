"""Tests for ``iris.projects.reflection`` — importance-triggered cycles."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from iris.projects import memory_entries as me
from iris.projects import reflection
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


def _plant(conn: sqlite3.Connection, text: str, importance: float) -> str:
    mid = me.propose(
        conn,
        project_id="p1",
        scope="project",
        memory_type="finding",
        text=text,
        importance=importance,
    )
    me.commit_pending(conn, [mid])
    return mid


def test_should_reflect_false_below_threshold(conn: sqlite3.Connection) -> None:
    _plant(conn, "small finding", 3.0)
    assert reflection.should_reflect(conn, "p1", threshold=40.0) is False


def test_should_reflect_true_at_threshold(conn: sqlite3.Connection) -> None:
    for i in range(6):
        _plant(conn, f"finding {i}", 8.0)
    assert reflection.should_reflect(conn, "p1", threshold=40.0) is True


def test_run_reflection_commits_insight_with_evidence(
    conn: sqlite3.Connection,
) -> None:
    ids = [_plant(conn, f"finding {i}", 9.0) for i in range(6)]

    def fake_llm(prompt: str) -> str:
        assert "higher-level insights" in prompt
        return "signal pipeline is stable across blocks\nmotif density correlates with block size"

    committed = reflection.run_reflection(conn, project_id="p1", threshold=40.0, llm_fn=fake_llm)
    assert len(committed) == 2

    rows = me.query(conn, project_id="p1", memory_type="reflection", status="active")
    assert len(rows) == 2
    assert {r["text"] for r in rows} == {
        "signal pipeline is stable across blocks",
        "motif density correlates with block size",
    }
    # Evidence pointers reference the planted memories.
    for r in rows:
        ev = r.get("evidence_json") or r.get("evidence")
        if isinstance(ev, str):
            import json as _json

            ev = _json.loads(ev)
        assert {e["memory_id"] for e in ev}.issuperset(set(ids[:5]))


def test_run_reflection_below_threshold_is_noop(conn: sqlite3.Connection) -> None:
    _plant(conn, "only one small finding", 3.0)
    called = False

    def spy(prompt: str) -> str:
        nonlocal called
        called = True
        return "nope"

    assert reflection.run_reflection(conn, project_id="p1", threshold=40.0, llm_fn=spy) == []
    assert called is False


def test_run_reflection_handles_empty_llm_output(conn: sqlite3.Connection) -> None:
    for i in range(6):
        _plant(conn, f"finding {i}", 8.0)
    assert (
        reflection.run_reflection(conn, project_id="p1", threshold=40.0, llm_fn=lambda _p: "") == []
    )
