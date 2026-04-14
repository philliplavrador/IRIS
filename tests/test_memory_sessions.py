"""Tests for ``iris.projects.sessions`` — memory-layer session lifecycle."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from iris.projects.db import connect, init_schema
from iris.projects.events import EVT_SESSION_ENDED, EVT_SESSION_STARTED, verify_chain
from iris.projects.sessions import end_session, get_session, start_session


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


def test_start_session_inserts_row_and_event(project_conn: sqlite3.Connection) -> None:
    sid = start_session(
        project_conn,
        project_id="p1",
        model_provider="anthropic",
        model_name="claude-sonnet-4",
        system_prompt="You are IRIS.",
    )
    assert isinstance(sid, str) and len(sid) == 32

    row = project_conn.execute(
        "SELECT project_id, model_provider, model_name, system_prompt_hash, "
        "ended_at, summary FROM sessions WHERE session_id = ?",
        (sid,),
    ).fetchone()
    assert row["project_id"] == "p1"
    assert row["model_provider"] == "anthropic"
    assert row["model_name"] == "claude-sonnet-4"
    expected = hashlib.sha256(b"You are IRIS.").hexdigest()
    assert row["system_prompt_hash"] == expected
    assert row["ended_at"] is None
    assert row["summary"] is None

    evts = project_conn.execute(
        "SELECT type, session_id FROM events WHERE project_id = ? ORDER BY rowid",
        ("p1",),
    ).fetchall()
    assert [e["type"] for e in evts] == [EVT_SESSION_STARTED]
    assert evts[0]["session_id"] == sid


def test_end_session_stamps_summary_and_event(project_conn: sqlite3.Connection) -> None:
    sid = start_session(
        project_conn,
        project_id="p1",
        model_provider="anthropic",
        model_name="claude-sonnet-4",
        system_prompt="prompt",
    )
    end_session(project_conn, session_id=sid, summary="Wrapped up the analysis.")

    row = project_conn.execute(
        "SELECT ended_at, summary FROM sessions WHERE session_id = ?", (sid,)
    ).fetchone()
    assert row["ended_at"] is not None
    assert row["summary"] == "Wrapped up the analysis."

    types = [
        r["type"]
        for r in project_conn.execute(
            "SELECT type FROM events WHERE project_id = ? ORDER BY rowid", ("p1",)
        ).fetchall()
    ]
    assert types == [EVT_SESSION_STARTED, EVT_SESSION_ENDED]


def test_get_session_round_trip(project_conn: sqlite3.Connection) -> None:
    sid = start_session(
        project_conn,
        project_id="p1",
        model_provider="anthropic",
        model_name="claude-sonnet-4",
        system_prompt="prompt",
    )
    record = get_session(project_conn, sid)
    assert record["session_id"] == sid
    assert record["project_id"] == "p1"
    assert record["model_provider"] == "anthropic"
    assert record["ended_at"] is None


def test_get_session_unknown_raises(project_conn: sqlite3.Connection) -> None:
    with pytest.raises(LookupError):
        get_session(project_conn, "deadbeef")


def test_end_session_unknown_raises(project_conn: sqlite3.Connection) -> None:
    with pytest.raises(LookupError):
        end_session(project_conn, session_id="nope", summary="x")


def test_session_lifecycle_keeps_chain_valid(project_conn: sqlite3.Connection) -> None:
    sid = start_session(
        project_conn,
        project_id="p1",
        model_provider="anthropic",
        model_name="claude-sonnet-4",
        system_prompt="prompt",
    )
    end_session(project_conn, session_id=sid, summary="done")
    result = verify_chain(project_conn, "p1")
    assert result["valid"] is True
    assert result["checked"] == 2
