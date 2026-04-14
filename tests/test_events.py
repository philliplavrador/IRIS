"""Tests for ``iris.projects.events`` — append-only event log + hash chain.

Covers the Task 2.2 checklist:
- append produces increasing rowids and chained hashes
- ``verify_chain`` returns ``valid=True`` on a clean chain
- a manual UPDATE on a payload makes ``verify_chain`` return ``valid=False``
- canonical JSON: dicts with same keys but different insertion order hash equal
- many concurrent appends from threads keep the chain intact
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest

from iris.projects.db import connect, init_schema
from iris.projects.events import (
    EVENT_TYPES,
    EVT_MEMORY_WRITE,
    EVT_MESSAGE,
    EVT_SESSION_STARTED,
    _canonical_json,
    _hash,
    append_event,
    verify_chain,
)

# --- helpers --------------------------------------------------------------


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


# --- tests ----------------------------------------------------------------


def test_event_type_constants_match_enum() -> None:
    # Sanity: EVENT_TYPES holds the documented set; every constant lands in it.
    assert EVT_MESSAGE in EVENT_TYPES
    assert EVT_SESSION_STARTED in EVENT_TYPES
    assert EVT_MEMORY_WRITE in EVENT_TYPES
    assert len(EVENT_TYPES) == 13


def test_unknown_event_type_raises(project_conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError):
        append_event(
            project_conn,
            project_id="p1",
            type="not_a_real_type",
            payload={"x": 1},
        )


def test_append_chains_hashes_and_increments_rowid(project_conn: sqlite3.Connection) -> None:
    e1 = append_event(project_conn, project_id="p1", type=EVT_MESSAGE, payload={"i": 1})
    e2 = append_event(project_conn, project_id="p1", type=EVT_MESSAGE, payload={"i": 2})
    e3 = append_event(project_conn, project_id="p1", type=EVT_MESSAGE, payload={"i": 3})

    rows = project_conn.execute(
        "SELECT event_id, rowid, prev_event_hash, event_hash "
        "FROM events WHERE project_id=? ORDER BY rowid ASC",
        ("p1",),
    ).fetchall()

    assert [r[0] for r in rows] == [e1, e2, e3]
    rowids = [r[1] for r in rows]
    assert rowids == sorted(rowids) and len(set(rowids)) == 3

    # First event has no predecessor.
    assert rows[0][2] is None
    # Each later event's prev_event_hash equals the previous event's event_hash.
    assert rows[1][2] == rows[0][3]
    assert rows[2][2] == rows[1][3]
    # Hashes are unique (different payloads + different prev hashes).
    hashes = {r[3] for r in rows}
    assert len(hashes) == 3


def test_verify_chain_on_clean_chain(project_conn: sqlite3.Connection) -> None:
    for i in range(5):
        append_event(project_conn, project_id="p1", type=EVT_MESSAGE, payload={"i": i})

    result = verify_chain(project_conn, "p1")
    assert result == {"valid": True, "first_break": None, "checked": 5}


def test_verify_chain_empty_project_is_valid(project_conn: sqlite3.Connection) -> None:
    assert verify_chain(project_conn, "p1") == {
        "valid": True,
        "first_break": None,
        "checked": 0,
    }


def test_payload_tamper_breaks_chain(project_conn: sqlite3.Connection) -> None:
    append_event(project_conn, project_id="p1", type=EVT_MESSAGE, payload={"i": 1})
    target = append_event(project_conn, project_id="p1", type=EVT_MESSAGE, payload={"i": 2})
    append_event(project_conn, project_id="p1", type=EVT_MESSAGE, payload={"i": 3})

    # Mutate the middle event's payload directly — exactly the kind of
    # tampering the hash chain is meant to detect.
    project_conn.execute(
        "UPDATE events SET payload_json=? WHERE event_id=?",
        ('{"i":999}', target),
    )

    result = verify_chain(project_conn, "p1")
    assert result["valid"] is False
    assert result["first_break"] == target
    # We checked the 1st event before hitting the broken one.
    assert result["checked"] == 1


def test_canonical_json_is_key_order_invariant() -> None:
    # The hash inputs are exactly what ``_canonical_json`` returns, so it's
    # the layer that matters. Two dicts with the same content but different
    # insertion order must serialize identically.
    a = {"a": 1, "b": 2, "c": [1, 2, 3]}
    b = {"c": [1, 2, 3], "b": 2, "a": 1}
    assert _canonical_json(a) == _canonical_json(b)
    assert _hash(EVT_MESSAGE, _canonical_json(a), None) == _hash(
        EVT_MESSAGE, _canonical_json(b), None
    )


def test_canonical_json_payloads_hash_equal_in_db(tmp_path: Path) -> None:
    # Two separate projects, identical payload appended in different key order.
    # The resulting event_hash (with no predecessor) must match.
    conn = connect(tmp_path)
    try:
        init_schema(conn)
        _make_project(conn, "pA")
        _make_project(conn, "pB")

        append_event(conn, project_id="pA", type=EVT_MESSAGE, payload={"a": 1, "b": 2})
        append_event(conn, project_id="pB", type=EVT_MESSAGE, payload={"b": 2, "a": 1})

        h_a = conn.execute("SELECT event_hash FROM events WHERE project_id='pA'").fetchone()[0]
        h_b = conn.execute("SELECT event_hash FROM events WHERE project_id='pB'").fetchone()[0]
        assert h_a == h_b
    finally:
        conn.close()


def test_concurrent_appends_keep_chain_intact(tmp_path: Path) -> None:
    # 1000 events from N threads, each with its own connection. The chain
    # must verify cleanly afterwards. This exercises the BEGIN IMMEDIATE
    # serialization path in ``append_event``.
    db_dir = tmp_path
    setup_conn = connect(db_dir)
    try:
        init_schema(setup_conn)
        _make_project(setup_conn, "p1")
    finally:
        setup_conn.close()

    n_threads = 8
    per_thread = 125  # 8 * 125 == 1000
    errors: list[BaseException] = []

    def worker(start: int) -> None:
        # Each thread opens its own connection — sqlite3.Connection is not
        # thread-safe, but separate connections to a WAL DB are fine.
        conn = connect(db_dir)
        try:
            for k in range(per_thread):
                append_event(
                    conn,
                    project_id="p1",
                    type=EVT_MESSAGE,
                    payload={"i": start + k},
                )
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            conn.close()

    threads = [threading.Thread(target=worker, args=(t * per_thread,)) for t in range(n_threads)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()

    assert errors == [], f"worker raised: {errors!r}"

    check_conn = connect(db_dir)
    try:
        result = verify_chain(check_conn, "p1")
        assert result["valid"] is True
        assert result["checked"] == n_threads * per_thread
        assert result["first_break"] is None
    finally:
        check_conn.close()
