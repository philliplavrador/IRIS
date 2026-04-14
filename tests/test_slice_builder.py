"""Tests for ``iris.projects.slice_builder`` — 7-segment assembly."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from iris.projects import memory_entries as me
from iris.projects import sessions as sessions_mod
from iris.projects import slice_builder
from iris.projects.db import connect, init_schema


def _make_project(conn: sqlite3.Connection, project_id: str = "p1") -> str:
    conn.execute(
        "INSERT INTO projects (project_id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (project_id, "demo", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
    )
    return project_id


@pytest.fixture
def ctx(tmp_path: Path):
    conn = connect(tmp_path)
    init_schema(conn)
    _make_project(conn)
    sid = sessions_mod.start_session(
        conn,
        project_id="p1",
        model_provider="anthropic",
        model_name="claude-sonnet-4",
        system_prompt="x",
    )
    try:
        yield conn, sid
    finally:
        conn.close()


def test_build_slice_returns_seven_segments_in_order(
    ctx: tuple[sqlite3.Connection, str],
) -> None:
    conn, sid = ctx
    out = slice_builder.build_slice(conn, project_id="p1", session_id=sid)
    names = [s["name"] for s in out["segments"]]
    assert names == list(slice_builder.SEGMENT_NAMES)
    assert len(out["segments"]) == 7
    assert isinstance(out["total_tokens"], int)
    assert isinstance(out["retrieval_skipped"], bool)


def test_build_slice_segment_4_empty_when_gate_says_no(
    ctx: tuple[sqlite3.Connection, str],
) -> None:
    conn, sid = ctx
    out = slice_builder.build_slice(conn, project_id="p1", session_id=sid, current_query="thanks")
    seg4 = next(s for s in out["segments"] if s["name"] == "retrieved_memories")
    assert seg4["content"] == ""
    assert out["retrieval_skipped"] is True


def test_build_slice_includes_core_memory_for_high_importance(
    ctx: tuple[sqlite3.Connection, str],
) -> None:
    conn, sid = ctx
    mid = me.propose(
        conn,
        project_id="p1",
        scope="project",
        memory_type="finding",
        text="critical invariant about the pipeline",
        importance=9.0,
    )
    me.commit_pending(conn, [mid])

    out = slice_builder.build_slice(conn, project_id="p1", session_id=sid)
    core = next(s for s in out["segments"] if s["name"] == "core_memory")
    assert "critical invariant" in core["content"]


def test_build_slice_enforces_token_budgets(
    ctx: tuple[sqlite3.Connection, str],
) -> None:
    conn, sid = ctx
    # Squeeze every segment to a tiny budget; each segment's reported
    # token_count must not exceed its budget.
    tight = {name: 10 for name in slice_builder.SEGMENT_NAMES}
    out = slice_builder.build_slice(conn, project_id="p1", session_id=sid, budgets=tight)
    for seg in out["segments"]:
        assert seg["token_count"] <= 10, seg


def test_build_slice_missing_session_yields_empty_conversation(
    ctx: tuple[sqlite3.Connection, str],
) -> None:
    conn, _ = ctx
    out = slice_builder.build_slice(conn, project_id="p1", session_id="no-such-session")
    conv = next(s for s in out["segments"] if s["name"] == "conversation_window")
    assert conv["content"] == ""
