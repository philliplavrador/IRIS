"""append_message must also append a `message` event in the same txn.

Covers the routes/CLAUDE.md §5 invariant: every mutating memory write
appends an event so the hash chain reflects the change.
"""

from __future__ import annotations

import json
import sqlite3

from iris.projects.events import EVT_MESSAGE, verify_chain
from iris.projects.messages import append_message


def _events(conn: sqlite3.Connection, project_id: str = "p1") -> list[dict]:
    rows = conn.execute(
        "SELECT event_id, type, session_id, payload_json "
        "FROM events WHERE project_id = ? ORDER BY rowid ASC",
        (project_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def test_append_message_emits_message_event(project_conn, session_id) -> None:
    before = _events(project_conn)
    mid = append_message(
        project_conn,
        session_id=session_id,
        role="user",
        content="detect spikes in channel 3",
    )
    after = _events(project_conn)
    assert len(after) == len(before) + 1

    ev = after[-1]
    assert ev["type"] == EVT_MESSAGE
    assert ev["session_id"] == session_id

    payload = json.loads(ev["payload_json"])
    # Payload links back to the row but does NOT carry the full content blob.
    assert payload["message_id"] == mid
    assert payload["session_id"] == session_id
    assert payload["role"] == "user"
    assert payload["content_len"] == len("detect spikes in channel 3")
    assert "content" not in payload


def test_n_messages_preserve_chain(project_conn, session_id) -> None:
    for i in range(8):
        append_message(
            project_conn,
            session_id=session_id,
            role="user" if i % 2 == 0 else "assistant",
            content=f"message {i} body text",
        )
    result = verify_chain(project_conn, "p1")
    assert result["valid"] is True
    assert result["first_break"] is None
    # 1 session_started + 8 message events.
    assert result["checked"] == 9


def test_message_event_rollback_on_fk_failure(project_conn) -> None:
    """Missing session -> no row, no event (atomicity)."""
    before = _events(project_conn)
    try:
        append_message(
            project_conn,
            session_id="does-not-exist",
            role="user",
            content="hi",
        )
    except sqlite3.IntegrityError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected IntegrityError")

    after = _events(project_conn)
    assert after == before
    # No orphan message row either.
    (count,) = project_conn.execute("SELECT count(*) FROM messages").fetchone()
    assert count == 0
