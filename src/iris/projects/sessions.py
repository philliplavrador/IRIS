"""Memory-layer session records (spec §7.1).

A *memory session* is one continuous chat conversation with the agent.
Every message, tool call, memory write, and run row carries a
``session_id`` so we can scope queries (and session-end summarisation
in Phase 14) to a single conversation.

This is **distinct** from the plot-pipeline sessions in
``iris.plot_sessions`` (the per-run output directories with
``manifest.json``). The two are unrelated; spec §7.1 explicitly carves
the SQL-backed conversation session out as its own table.

Public API
----------
- :func:`start_session` — opens a row, stamps the system-prompt SHA-256,
  writes a ``session_started`` event, returns the new ``session_id``.
- :func:`end_session` — sets ``ended_at`` + ``summary`` and writes a
  ``session_ended`` event. Idempotent on a session that's already ended
  only insofar as ``end_session`` overwrites the summary.
- :func:`get_session` — fetch a session row as a dict.

Concurrency
-----------
Inserts/updates use the connection's autocommit mode (the default for
``db.connect``). The follow-up :func:`events.append_event` call opens
its own ``BEGIN IMMEDIATE`` transaction, so a session row is visible
to readers even if the event-log append fails downstream — which is
the right ordering for session lifecycle events (the row exists; the
chain link is best-effort but always recorded if the DB is healthy).

See ``docs/memory-restructure.md`` §7.1 for the schema.
"""

from __future__ import annotations

import hashlib
import sqlite3
import uuid
from datetime import UTC, datetime
from typing import Any

from iris.projects.events import (
    EVT_SESSION_ENDED,
    EVT_SESSION_STARTED,
    append_event,
)

__all__ = [
    "start_session",
    "end_session",
    "get_session",
]


def _now_iso() -> str:
    """Return the current time as an ISO-8601 string with ``Z`` suffix."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _hash_prompt(system_prompt: str) -> str:
    """Return SHA-256 hex digest of ``system_prompt``."""
    return hashlib.sha256(system_prompt.encode("utf-8")).hexdigest()


def start_session(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    model_provider: str,
    model_name: str,
    system_prompt: str,
) -> str:
    """Insert a new session row, log a ``session_started`` event, return ``session_id``.

    The system prompt itself is **not** stored — only its SHA-256 — so
    we can detect prompt changes across sessions without persisting
    the (potentially large + sensitive) prompt body in every session
    row. Callers that need the prompt body can persist it via the
    event payload.
    """
    session_id = uuid.uuid4().hex
    started_at = _now_iso()
    system_prompt_hash = _hash_prompt(system_prompt)

    conn.execute(
        "INSERT INTO sessions ("
        "session_id, project_id, started_at, ended_at, "
        "model_provider, model_name, system_prompt_hash, summary"
        ") VALUES (?, ?, ?, NULL, ?, ?, ?, NULL)",
        (
            session_id,
            project_id,
            started_at,
            model_provider,
            model_name,
            system_prompt_hash,
        ),
    )

    append_event(
        conn,
        project_id=project_id,
        type=EVT_SESSION_STARTED,
        payload={
            "session_id": session_id,
            "model_provider": model_provider,
            "model_name": model_name,
            "system_prompt_hash": system_prompt_hash,
            "started_at": started_at,
        },
        session_id=session_id,
    )

    return session_id


def end_session(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    summary: str,
) -> None:
    """Stamp ``ended_at`` + ``summary`` on the session and log ``session_ended``.

    Raises
    ------
    LookupError
        If ``session_id`` does not exist.
    """
    row = conn.execute(
        "SELECT project_id FROM sessions WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"session {session_id!r} not found")
    project_id = row[0]

    ended_at = _now_iso()
    conn.execute(
        "UPDATE sessions SET ended_at = ?, summary = ? WHERE session_id = ?",
        (ended_at, summary, session_id),
    )

    append_event(
        conn,
        project_id=project_id,
        type=EVT_SESSION_ENDED,
        payload={
            "session_id": session_id,
            "ended_at": ended_at,
            "summary": summary,
        },
        session_id=session_id,
    )


def get_session(conn: sqlite3.Connection, session_id: str) -> dict[str, Any]:
    """Return the session row as a dict.

    Raises
    ------
    LookupError
        If ``session_id`` does not exist.
    """
    row = conn.execute(
        "SELECT session_id, project_id, started_at, ended_at, "
        "model_provider, model_name, system_prompt_hash, summary "
        "FROM sessions WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"session {session_id!r} not found")
    return {
        "session_id": row[0],
        "project_id": row[1],
        "started_at": row[2],
        "ended_at": row[3],
        "model_provider": row[4],
        "model_name": row[5],
        "system_prompt_hash": row[6],
        "summary": row[7],
    }
