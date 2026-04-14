"""Tests for ``iris.projects.retrieval`` — gate + three-stage recall."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from iris.projects import memory_entries as me
from iris.projects import retrieval
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
    try:
        yield conn
    finally:
        conn.close()


def _plant(
    conn: sqlite3.Connection,
    *,
    text: str,
    importance: float = 5.0,
    memory_type: str = "finding",
) -> str:
    mid = me.propose(
        conn,
        project_id="p1",
        scope="project",
        memory_type=memory_type,
        text=text,
        importance=importance,
    )
    me.commit_pending(conn, [mid])
    return mid


# -- gate ------------------------------------------------------------------


def test_should_retrieve_skips_trivial_acknowledgements() -> None:
    for q in ("ok", "thanks", "got it", "yes", "sure"):
        assert retrieval.should_retrieve(q) is False, q


def test_should_retrieve_fires_on_recall_keywords() -> None:
    for q in (
        "what did we decide about spikes?",
        "remember the bandpass setting",
        "recall earlier analysis",
    ):
        assert retrieval.should_retrieve(q) is True, q


def test_should_retrieve_fires_on_long_queries() -> None:
    q = "please summarize the outputs from our last three runs and their findings"
    assert retrieval.should_retrieve(q) is True


# -- recall ----------------------------------------------------------------


def test_recall_returns_active_matches_ranked(
    project_conn: sqlite3.Connection,
) -> None:
    _plant(project_conn, text="bandpass butter filter 300 hz", importance=9.0)
    _plant(project_conn, text="wholly unrelated note about icing cakes", importance=5.0)
    hits = retrieval.recall(project_conn, project_id="p1", query="bandpass", limit=5)
    assert len(hits) >= 1
    assert any("bandpass" in h["text"].lower() for h in hits)
    # Returned rows carry score breakdown.
    for h in hits:
        assert "score" in h and "bm25_norm" in h


def test_recall_ignores_drafts(project_conn: sqlite3.Connection) -> None:
    # Draft (not committed) — must be invisible.
    me.propose(
        project_conn,
        project_id="p1",
        scope="project",
        memory_type="finding",
        text="draft about bandpass",
        importance=5.0,
    )
    hits = retrieval.recall(project_conn, project_id="p1", query="bandpass", limit=5)
    assert all("draft" not in h["text"] for h in hits)


def test_recall_type_filter_rejects_unknown(
    project_conn: sqlite3.Connection,
) -> None:
    with pytest.raises(ValueError):
        retrieval.recall(
            project_conn,
            project_id="p1",
            query="bandpass",
            types=["not-a-real-type"],
        )


def test_recall_respects_limit(project_conn: sqlite3.Connection) -> None:
    for i in range(8):
        _plant(project_conn, text=f"bandpass finding number {i}", importance=6.0)
    hits = retrieval.recall(project_conn, project_id="p1", query="bandpass", limit=3)
    assert len(hits) <= 3
