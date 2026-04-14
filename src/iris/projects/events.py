"""Append-only event log with SHA-256 hash chain (spec §4 L4, §7.1, §7.2).

This module owns every write to the ``events`` table. Events are the
project's source-of-truth audit trail: every state change downstream of
Phase 2 must call :func:`append_event` so it shows up here.

Design
------
- **Append-only**: never UPDATE or DELETE. The hash chain is what makes
  the log tamper-evident; mutating a row breaks every downstream hash.
- **Hash chain**: each event's ``event_hash`` is
  ``sha256(type + canonical_json(payload) + (prev_event_hash or ""))``.
  Canonical JSON is ``json.dumps(payload, sort_keys=True,
  separators=(",", ":"))`` so equivalent dicts always hash the same.
- **Chain head per project**: looked up with
  ``SELECT event_hash FROM events WHERE project_id=? ORDER BY rowid DESC
  LIMIT 1``. Append + read happen inside one ``BEGIN IMMEDIATE``
  transaction so concurrent writers serialize cleanly under SQLite's
  WAL. ``rowid`` (insertion order) is the chain spine — ``ts`` is human
  metadata only and may go non-monotonic across threads when wall-clock
  resolution coincides or system time skews.
- **Concurrency**: SQLite WAL allows many readers but one writer; the
  daemon is single-process and ``BEGIN IMMEDIATE`` plus the row lock
  on ``events`` is sufficient.

See ``docs/memory-restructure.md`` §4 (Layer 4) and §7.2 (rationale).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import UTC, datetime
from typing import Any, Final

__all__ = [
    "EVENT_TYPES",
    "EventType",
    "append_event",
    "append_event_in_txn",
    "verify_chain",
    # Individual constants, re-exported for autocomplete-friendly use.
    "EVT_MESSAGE",
    "EVT_TOOL_CALL",
    "EVT_TOOL_RESULT",
    "EVT_DATASET_IMPORT",
    "EVT_DATASET_PROFILED",
    "EVT_TRANSFORM_RUN",
    "EVT_ARTIFACT_CREATED",
    "EVT_MEMORY_WRITE",
    "EVT_MEMORY_UPDATE",
    "EVT_MEMORY_DELETE",
    "EVT_OPERATION_CREATED",
    "EVT_PREFERENCE_CHANGED",
    "EVT_SESSION_STARTED",
    "EVT_SESSION_ENDED",
]

# -- event-type constants ---------------------------------------------------

EVT_MESSAGE: Final[str] = "message"
EVT_TOOL_CALL: Final[str] = "tool_call"
EVT_TOOL_RESULT: Final[str] = "tool_result"
EVT_DATASET_IMPORT: Final[str] = "dataset_import"
EVT_DATASET_PROFILED: Final[str] = "dataset_profiled"
EVT_TRANSFORM_RUN: Final[str] = "transform_run"
EVT_ARTIFACT_CREATED: Final[str] = "artifact_created"
EVT_MEMORY_WRITE: Final[str] = "memory_write"
EVT_MEMORY_UPDATE: Final[str] = "memory_update"
EVT_MEMORY_DELETE: Final[str] = "memory_delete"
EVT_OPERATION_CREATED: Final[str] = "operation_created"
EVT_PREFERENCE_CHANGED: Final[str] = "preference_changed"
EVT_SESSION_STARTED: Final[str] = "session_started"
EVT_SESSION_ENDED: Final[str] = "session_ended"

EVENT_TYPES: Final[frozenset[str]] = frozenset(
    {
        EVT_MESSAGE,
        EVT_TOOL_CALL,
        EVT_TOOL_RESULT,
        EVT_DATASET_IMPORT,
        EVT_DATASET_PROFILED,
        EVT_TRANSFORM_RUN,
        EVT_ARTIFACT_CREATED,
        EVT_MEMORY_WRITE,
        EVT_MEMORY_UPDATE,
        EVT_MEMORY_DELETE,
        EVT_OPERATION_CREATED,
        EVT_PREFERENCE_CHANGED,
        EVT_SESSION_STARTED,
        EVT_SESSION_ENDED,
    }
)

# Type alias kept loose (str) so callers don't need a Literal import for
# every event-type they emit; validation happens at runtime against
# EVENT_TYPES.
EventType = str


# -- helpers ----------------------------------------------------------------


def _canonical_json(payload: dict[str, Any]) -> str:
    """Return canonical JSON for ``payload``: sorted keys, no whitespace."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _hash(type_: str, payload_json: str, prev_event_hash: str | None) -> str:
    """Compute the hash for a new event."""
    h = hashlib.sha256()
    h.update(type_.encode("utf-8"))
    h.update(payload_json.encode("utf-8"))
    h.update((prev_event_hash or "").encode("utf-8"))
    return h.hexdigest()


def _now_iso() -> str:
    """Return the current time as an ISO-8601 string with ``Z`` suffix."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


# -- public API -------------------------------------------------------------


def append_event(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    type: str,
    payload: dict[str, Any],
    session_id: str | None = None,
) -> str:
    """Append a new event to the log and return its ``event_id``.

    Computes the hash chain link inside a ``BEGIN IMMEDIATE`` transaction
    so concurrent writers serialize without losing the chain head.

    Raises
    ------
    ValueError
        If ``type`` is not one of :data:`EVENT_TYPES`.
    sqlite3.IntegrityError
        If ``project_id`` (or ``session_id``) does not satisfy a foreign
        key.
    """
    if type not in EVENT_TYPES:
        raise ValueError(f"unknown event type {type!r}; expected one of {sorted(EVENT_TYPES)}")

    # Connections opened by db.connect use isolation_level=None (autocommit).
    # We need an explicit transaction so the chain-head read and the insert
    # are atomic with respect to other writers.
    conn.execute("BEGIN IMMEDIATE")
    try:
        event_id = append_event_in_txn(
            conn,
            project_id=project_id,
            type=type,
            payload=payload,
            session_id=session_id,
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    return event_id


def append_event_in_txn(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    type: str,
    payload: dict[str, Any],
    session_id: str | None = None,
) -> str:
    """Append an event without opening a transaction.

    Caller must already hold an open transaction (typically
    ``BEGIN IMMEDIATE``). This exists so domain modules
    (``messages.append_message``, ``tool_calls.append_tool_call``) can
    wrap their row insert + hash-chain link in a single atomic unit
    without the nested-BEGIN error SQLite would otherwise raise.

    Raises
    ------
    ValueError
        If ``type`` is not one of :data:`EVENT_TYPES`.
    """
    if type not in EVENT_TYPES:
        raise ValueError(f"unknown event type {type!r}; expected one of {sorted(EVENT_TYPES)}")

    payload_json = _canonical_json(payload)
    event_id = uuid.uuid4().hex
    ts = _now_iso()

    row = conn.execute(
        "SELECT event_hash FROM events WHERE project_id = ? ORDER BY rowid DESC LIMIT 1",
        (project_id,),
    ).fetchone()
    prev_event_hash: str | None = row[0] if row is not None else None
    event_hash = _hash(type, payload_json, prev_event_hash)
    conn.execute(
        "INSERT INTO events ("
        "event_id, project_id, session_id, ts, type, "
        "payload_json, prev_event_hash, event_hash"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            event_id,
            project_id,
            session_id,
            ts,
            type,
            payload_json,
            prev_event_hash,
            event_hash,
        ),
    )
    return event_id


def verify_chain(conn: sqlite3.Connection, project_id: str) -> dict[str, Any]:
    """Re-walk the hash chain for ``project_id`` and report integrity.

    Returns a dict ``{"valid": bool, "first_break": event_id | None,
    "checked": int}``. The walk stops at the first mismatched row.

    The check both re-derives ``event_hash`` from the stored
    ``(type, payload_json, prev_event_hash)`` triple AND verifies that
    each row's ``prev_event_hash`` equals the previous row's
    ``event_hash``.
    """
    rows = conn.execute(
        "SELECT event_id, type, payload_json, prev_event_hash, event_hash "
        "FROM events WHERE project_id = ? "
        "ORDER BY rowid ASC",
        (project_id,),
    ).fetchall()

    expected_prev: str | None = None
    checked = 0
    for row in rows:
        event_id = row[0]
        type_ = row[1]
        payload_json = row[2]
        stored_prev = row[3]
        stored_hash = row[4]

        if stored_prev != expected_prev:
            return {"valid": False, "first_break": event_id, "checked": checked}

        recomputed = _hash(type_, payload_json, stored_prev)
        if recomputed != stored_hash:
            return {"valid": False, "first_break": event_id, "checked": checked}

        expected_prev = stored_hash
        checked += 1

    return {"valid": True, "first_break": None, "checked": checked}
