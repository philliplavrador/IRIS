"""Chat message persistence with FTS5 BM25 search (spec §7.1, §9.3).

Every user / assistant / tool message that crosses the agent bridge lands
in the ``messages`` table and its FTS5 shadow (``messages_fts``). FTS5 gives
us cheap BM25 lexical search for Phase 9 retrieval.

The schema (see ``schema.sql``) declares ``messages_fts`` as a
``content=messages``-backed virtual table but **does not** define triggers
to sync it. We therefore perform the FTS insert explicitly on every append.
Using ``content=messages, content_rowid=rowid`` means the FTS rowid must
match the base-table rowid, which is why we insert into ``messages`` first
and reuse ``lastrowid``.

Public API
----------
- :func:`append_message` — insert into ``messages`` + mirror into
  ``messages_fts`` inside a single transaction. Returns the new
  ``message_id``.
- :func:`search` — FTS5 BM25 search scoped to one project. Returns the
  hits as dicts ordered by ascending BM25 score (most-relevant first).

Concurrency
-----------
The insert runs inside ``BEGIN IMMEDIATE`` so the base-table + FTS-table
pair stays consistent under concurrent writers. Rollback on failure is
unconditional so we never end up with a half-synced FTS row.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime
from typing import Any

__all__ = [
    "ROLES",
    "append_message",
    "search",
]

# Accepted role values. ``tool`` covers both tool_use (assistant-issued
# invocations embedded in an assistant block) and tool_result payloads
# the user side of the SDK stream forwards back to the model.
ROLES: frozenset[str] = frozenset({"user", "assistant", "tool", "system"})


def _now_iso() -> str:
    """Return the current time as an ISO-8601 string with ``Z`` suffix."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def append_message(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    role: str,
    content: str,
    event_id: str | None = None,
    token_count: int | None = None,
) -> str:
    """Append one chat message to the log and return its ``message_id``.

    Writes to ``messages`` (base row) **and** ``messages_fts`` (FTS5
    shadow) in a single ``BEGIN IMMEDIATE`` transaction. The FTS rowid is
    forced to match the base-table rowid so ``content=messages`` stays
    consistent — this is how SQLite's external-content FTS pattern
    recommends wiring manual sync.

    Raises
    ------
    ValueError
        If ``role`` is not one of :data:`ROLES`.
    sqlite3.IntegrityError
        If ``session_id`` or ``event_id`` violates a foreign key.
    """
    if role not in ROLES:
        raise ValueError(f"unknown role {role!r}; expected one of {sorted(ROLES)}")

    message_id = uuid.uuid4().hex
    ts = _now_iso()

    conn.execute("BEGIN IMMEDIATE")
    try:
        cursor = conn.execute(
            "INSERT INTO messages ("
            "message_id, session_id, event_id, role, content, ts, token_count"
            ") VALUES (?, ?, ?, ?, ?, ?, ?)",
            (message_id, session_id, event_id, role, content, ts, token_count),
        )
        rowid = cursor.lastrowid
        # Mirror into the external-content FTS table. rowid must match so
        # ``content=messages`` can resolve hits back to the base row.
        conn.execute(
            "INSERT INTO messages_fts(rowid, content) VALUES (?, ?)",
            (rowid, content),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    return message_id


def search(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    query: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """FTS5 BM25 search over messages scoped to one project.

    Joins ``messages_fts`` to ``messages`` (via ``rowid``) and
    ``sessions`` (to filter by ``project_id``). Ordered by ascending BM25
    score — FTS5's ``bm25()`` returns **lower scores for better matches**
    (it's a negative log-probability), which is why we order ``ASC``.

    Parameters
    ----------
    query
        Raw FTS5 query. Callers should sanitize/escape if they pass user
        input — this module does not quote-wrap the string because that
        would disable FTS5 operators (``NEAR``, ``AND``, prefix ``*``).

    Returns
    -------
    list of dicts, each with ``message_id``, ``session_id``, ``role``,
    ``content``, ``ts``, ``token_count``, ``event_id``, and ``score``.
    ``score`` is the raw BM25 value (lower = better).
    """
    rows = conn.execute(
        "SELECT m.message_id, m.session_id, m.event_id, m.role, m.content, "
        "m.ts, m.token_count, bm25(messages_fts) AS score "
        "FROM messages_fts "
        "JOIN messages m ON m.rowid = messages_fts.rowid "
        "JOIN sessions s ON s.session_id = m.session_id "
        "WHERE messages_fts MATCH ? AND s.project_id = ? "
        "ORDER BY score ASC "
        "LIMIT ?",
        (query, project_id, limit),
    ).fetchall()

    return [
        {
            "message_id": r[0],
            "session_id": r[1],
            "event_id": r[2],
            "role": r[3],
            "content": r[4],
            "ts": r[5],
            "token_count": r[6],
            "score": r[7],
        }
        for r in rows
    ]
