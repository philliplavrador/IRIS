"""Tests for ``iris.projects.summarization``."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from iris.projects import memory_entries as me
from iris.projects import summarization
from iris.projects.db import connect, init_schema
from iris.projects.messages import append_message
from iris.projects.sessions import end_session, start_session


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


def _make_session(conn: sqlite3.Connection) -> str:
    return start_session(
        conn,
        project_id="p1",
        model_provider="anthropic",
        model_name="claude-sonnet-4",
        system_prompt="x",
    )


def test_summarize_session_empty_returns_empty(conn: sqlite3.Connection) -> None:
    sid = _make_session(conn)
    assert summarization.summarize_session(conn, session_id=sid, llm_fn=lambda _p: "x") == ""


def test_summarize_session_calls_llm_with_messages(conn: sqlite3.Connection) -> None:
    sid = _make_session(conn)
    append_message(conn, session_id=sid, role="user", content="what is the spike rate?")
    append_message(conn, session_id=sid, role="assistant", content="it varies by block")

    captured: list[str] = []

    def fake(prompt: str) -> str:
        captured.append(prompt)
        return "Discussed spike rate variability across blocks."

    out = summarization.summarize_session(conn, session_id=sid, llm_fn=fake)
    assert out.startswith("Discussed")
    assert "spike rate" in captured[0]


def test_summarize_summaries_requires_n(conn: sqlite3.Connection) -> None:
    sid = _make_session(conn)
    end_session(conn, session_id=sid, summary="single short summary")
    assert (
        summarization.summarize_summaries(conn, project_id="p1", n=3, llm_fn=lambda _: "x") is None
    )


def test_summarize_summaries_commits_super_summary(conn: sqlite3.Connection) -> None:
    for i in range(3):
        sid = _make_session(conn)
        append_message(conn, session_id=sid, role="user", content=f"msg-{i}")
        end_session(conn, session_id=sid, summary=f"session {i} findings")

    def fake(prompt: str) -> str:
        assert "super-summary" in prompt
        return "Across three sessions, the team refined the signal pipeline."

    mid = summarization.summarize_summaries(conn, project_id="p1", n=3, llm_fn=fake)
    assert mid is not None

    rows = me.query(conn, project_id="p1", memory_type="session_summary", status="active")
    assert len(rows) == 1
    assert rows[0]["text"].startswith("Across three sessions")


def test_summarize_summaries_empty_llm_skips_commit(conn: sqlite3.Connection) -> None:
    for i in range(3):
        sid = _make_session(conn)
        end_session(conn, session_id=sid, summary=f"session {i}")
    assert (
        summarization.summarize_summaries(conn, project_id="p1", n=3, llm_fn=lambda _p: "") is None
    )
