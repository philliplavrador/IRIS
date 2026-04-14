"""append_tool_call must emit tool_call + tool_result events in one txn."""

from __future__ import annotations

import json
import sqlite3

from iris.projects.events import EVT_TOOL_CALL, EVT_TOOL_RESULT, verify_chain
from iris.projects.tool_calls import append_tool_call


def _events(conn: sqlite3.Connection, project_id: str = "p1") -> list[dict]:
    rows = conn.execute(
        "SELECT event_id, type, session_id, payload_json "
        "FROM events WHERE project_id = ? ORDER BY rowid ASC",
        (project_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def test_append_tool_call_emits_call_and_result_events(project_conn, session_id) -> None:
    before = _events(project_conn)
    tcid = append_tool_call(
        project_conn,
        session_id=session_id,
        tool_name="Bash",
        input={"cmd": "ls"},
        success=True,
        output_summary="3 files",
        execution_time_ms=17,
    )
    after = _events(project_conn)
    # session_started was already there; we expect +2 (call + result).
    assert len(after) == len(before) + 2

    call_ev, result_ev = after[-2], after[-1]
    assert call_ev["type"] == EVT_TOOL_CALL
    assert result_ev["type"] == EVT_TOOL_RESULT

    cp = json.loads(call_ev["payload_json"])
    rp = json.loads(result_ev["payload_json"])
    assert cp["tool_call_id"] == tcid
    assert cp["tool_name"] == "Bash"
    assert "input" not in cp  # don't leak inputs into the event log
    assert rp["tool_call_id"] == tcid
    assert rp["success"] is True
    assert rp["execution_time_ms"] == 17
    assert rp["error"] is None
    # The bulky row data (input_json, output_summary) lives on tool_calls,
    # not in the event payload.
    assert "output_summary" not in rp


def test_tool_call_error_payload_truncated(project_conn, session_id) -> None:
    big_err = "boom! " * 200
    append_tool_call(
        project_conn,
        session_id=session_id,
        tool_name="iris.run",
        input={"pipe": "x"},
        success=False,
        error=big_err,
    )
    rows = _events(project_conn)
    result_ev = [r for r in rows if r["type"] == EVT_TOOL_RESULT][-1]
    payload = json.loads(result_ev["payload_json"])
    assert payload["success"] is False
    assert payload["error"] is not None
    assert len(payload["error"]) <= 200


def test_chain_valid_mixed_sequence(project_conn, session_id) -> None:
    """session_started -> messages -> tool_calls -> session_ended — chain ok."""
    from iris.projects.messages import append_message
    from iris.projects.sessions import end_session

    append_message(project_conn, session_id=session_id, role="user", content="run it")
    append_tool_call(
        project_conn,
        session_id=session_id,
        tool_name="Bash",
        input={"cmd": "true"},
        success=True,
    )
    append_message(project_conn, session_id=session_id, role="assistant", content="done")
    append_tool_call(
        project_conn,
        session_id=session_id,
        tool_name="Bash",
        input={"cmd": "false"},
        success=False,
        error="exit 1",
    )
    end_session(project_conn, session_id=session_id, summary="ok")

    result = verify_chain(project_conn, "p1")
    assert result["valid"] is True
    assert result["first_break"] is None
    # 1 session_started + 1 message + (call+result) + 1 message +
    # (call+result) + 1 session_ended = 8
    assert result["checked"] == 8


def test_tool_call_rollback_on_missing_session(project_conn) -> None:
    before = _events(project_conn)
    try:
        append_tool_call(
            project_conn,
            session_id="nope",
            tool_name="Bash",
            input={},
            success=True,
        )
    except sqlite3.IntegrityError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected IntegrityError")

    after = _events(project_conn)
    assert after == before
    (count,) = project_conn.execute("SELECT count(*) FROM tool_calls").fetchone()
    assert count == 0
