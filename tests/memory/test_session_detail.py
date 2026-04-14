"""get_session derived fields: message_count, tool_call_count, duration_ms.

Locks in the fix for bug #9 — previously get_session returned only raw
row columns; it now joins message + tool_call counts and computes the
session duration in milliseconds.
"""

from __future__ import annotations

import sqlite3

from iris.projects.messages import append_message
from iris.projects.sessions import end_session, get_session
from iris.projects.tool_calls import append_tool_call


def test_open_session_has_zero_counts_and_null_duration(
    project_conn: sqlite3.Connection, session_id: str
) -> None:
    sess = get_session(project_conn, session_id)
    assert sess["message_count"] == 0
    assert sess["tool_call_count"] == 0
    assert sess["duration_ms"] is None
    assert sess["ended_at"] is None


def test_counts_reflect_appended_messages_and_tool_calls(
    project_conn: sqlite3.Connection, session_id: str
) -> None:
    for i in range(3):
        append_message(
            project_conn,
            session_id=session_id,
            role="user",
            content=f"msg-{i}",
        )
    for i in range(2):
        append_tool_call(
            project_conn,
            session_id=session_id,
            tool_name="Bash",
            input={"cmd": f"echo {i}"},
            success=True,
            output_summary=f"ok-{i}",
        )

    sess = get_session(project_conn, session_id)
    assert sess["message_count"] == 3
    assert sess["tool_call_count"] == 2
    # Still open — duration remains null even with rows appended.
    assert sess["duration_ms"] is None


def test_duration_ms_computed_after_end(project_conn: sqlite3.Connection, session_id: str) -> None:
    end_session(project_conn, session_id=session_id, summary="done")

    sess = get_session(project_conn, session_id)
    assert sess["ended_at"] is not None
    assert isinstance(sess["duration_ms"], int)
    assert sess["duration_ms"] >= 0

    # Cross-check: duration_ms matches the raw timestamp arithmetic.
    from datetime import datetime

    def _parse(ts: str) -> datetime:
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        return datetime.fromisoformat(ts)

    delta_ms = int((_parse(sess["ended_at"]) - _parse(sess["started_at"])).total_seconds() * 1000)
    assert sess["duration_ms"] == delta_ms
