"""Tests for ``iris.projects.messages`` — append + FTS5 BM25 search."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from iris.projects.db import connect, init_schema
from iris.projects.messages import append_message, search
from iris.projects.sessions import start_session


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


def _new_session(conn: sqlite3.Connection, project_id: str = "p1") -> str:
    return start_session(
        conn,
        project_id=project_id,
        model_provider="anthropic",
        model_name="claude-sonnet-4",
        system_prompt="You are IRIS.",
    )


def test_append_inserts_base_row_and_fts_shadow(project_conn: sqlite3.Connection) -> None:
    sid = _new_session(project_conn)
    mid = append_message(
        project_conn,
        session_id=sid,
        role="user",
        content="detect spikes in channel 3",
    )
    assert isinstance(mid, str) and len(mid) == 32

    row = project_conn.execute(
        "SELECT session_id, role, content, token_count, event_id "
        "FROM messages WHERE message_id = ?",
        (mid,),
    ).fetchone()
    assert row["session_id"] == sid
    assert row["role"] == "user"
    assert row["content"] == "detect spikes in channel 3"
    assert row["token_count"] is None
    assert row["event_id"] is None

    # FTS shadow must mirror the row so BM25 queries find it.
    (fts_count,) = project_conn.execute(
        "SELECT count(*) FROM messages_fts WHERE messages_fts MATCH 'spikes'",
    ).fetchone()
    assert fts_count == 1


def test_unknown_role_rejected(project_conn: sqlite3.Connection) -> None:
    sid = _new_session(project_conn)
    with pytest.raises(ValueError, match="unknown role"):
        append_message(project_conn, session_id=sid, role="bogus", content="hi")


def test_search_bm25_orders_hits_most_relevant_first(
    project_conn: sqlite3.Connection,
) -> None:
    sid = _new_session(project_conn)
    append_message(
        project_conn,
        session_id=sid,
        role="user",
        content="butter bandpass filter 300 to 3000 Hz",
    )
    append_message(
        project_conn,
        session_id=sid,
        role="assistant",
        content="running butter_bandpass on the trace",
    )
    # A document that mentions only one of the key terms should score worse.
    append_message(
        project_conn,
        session_id=sid,
        role="user",
        content="show me the spectrogram please",
    )

    hits = search(project_conn, project_id="p1", query="butter bandpass", limit=5)
    assert len(hits) == 2
    # Both hits mention "butter" + "bandpass" — FTS5 BM25 returns the tighter
    # match first. We only assert the tangential "spectrogram" row isn't here.
    contents = [h["content"] for h in hits]
    assert all("butter" in c for c in contents)
    # BM25 score is negative-log-prob; lower is better; the list is ordered
    # ascending, so the first score must not exceed the last.
    assert hits[0]["score"] <= hits[-1]["score"]


def test_search_scopes_to_project(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    init_schema(conn)
    _make_project(conn, "p1")
    _make_project(conn, "p2")

    sid1 = _new_session(conn, "p1")
    sid2 = _new_session(conn, "p2")
    append_message(conn, session_id=sid1, role="user", content="find the needle")
    append_message(conn, session_id=sid2, role="user", content="find the needle")

    hits_p1 = search(conn, project_id="p1", query="needle", limit=10)
    hits_p2 = search(conn, project_id="p2", query="needle", limit=10)
    assert len(hits_p1) == 1
    assert len(hits_p2) == 1
    assert hits_p1[0]["session_id"] == sid1
    assert hits_p2[0]["session_id"] == sid2
    conn.close()
