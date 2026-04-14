"""Unified L3 memory store (spec §4 Layer 3, §7.1, §10.1, §10.4).

Every curated long-term memory — findings, decisions, caveats, open
questions, user preferences, failure reflections, higher-level reflections
(V2) — lives in the ``memory_entries`` table. The per-type tables that
preceded this rewrite (``findings``, ``decisions``, etc.) were collapsed in
Phase 0; the discriminator is ``memory_type``.

Lifecycle
---------
1. :func:`propose` writes a row with ``status='draft'`` and an attached
   ``memory_write`` event. Drafts are candidates for the curation ritual.
2. :func:`commit_pending` flips batches of drafts to ``status='active'``
   and writes a ``memory_update`` event per id.
3. :func:`discard_pending` hard-deletes drafts. Rejected proposals have no
   audit value (spec §10.4) — we do not leave a tombstone row.
4. :func:`supersede` points one active memory at another via
   ``superseded_by`` and flips status to ``'superseded'``.
5. :func:`soft_delete` sets ``status='archived'`` and writes a
   ``memory_delete`` event. Unlike draft discard this is a soft op so we
   keep the lineage.
6. :func:`set_status` is the general-purpose transition hook
   (``archived``/``contradicted``/``stale``) used by Phase 16 modules.
7. :func:`touch` bumps ``last_accessed_at`` + ``access_count`` for
   retrieval ranking; no event.

FTS5 sync
---------
``memory_entries_fts`` is a ``content=memory_entries`` external-content
virtual table with no declarative triggers. Every insert that targets
``memory_entries`` must mirror the ``text`` + ``tags`` columns at the same
rowid. Writes happen inside ``BEGIN IMMEDIATE`` so the base + FTS rows stay
atomic under concurrent writers. FTS rows are tombstoned via the
``'delete'`` command on hard-delete and rewritten via ``'delete'`` +
``INSERT`` on text/tag updates (we don't update text today, but the
pattern is in place).

Public API
----------
- :func:`propose`
- :func:`commit_pending`
- :func:`discard_pending`
- :func:`query`
- :func:`set_status`
- :func:`supersede`
- :func:`soft_delete`
- :func:`touch`
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from typing import Any, Final

from iris.projects import events as events_mod

__all__ = [
    "MEMORY_TYPES",
    "SCOPES",
    "STATUSES",
    "commit_pending",
    "discard_pending",
    "propose",
    "query",
    "set_status",
    "soft_delete",
    "supersede",
    "touch",
]

# Mirrors the CHECK-less enum-by-convention columns in ``schema.sql``. We
# validate at the Python boundary instead of via DB constraints so the
# error surface is clean (``ValueError``) and the schema file stays
# forward-compatible with V2 additions like ``session_summary``.
MEMORY_TYPES: Final[frozenset[str]] = frozenset(
    {
        "finding",
        "assumption",
        "caveat",
        "open_question",
        "decision",
        "preference",
        "failure_reflection",
        "reflection",
        # V2 additions land here as they come online. Extending the set is
        # cheap; removing a value is not, so we keep V2 members enabled
        # defensively.
        "session_summary",
    }
)

SCOPES: Final[frozenset[str]] = frozenset({"project", "dataset", "user", "tool"})

STATUSES: Final[frozenset[str]] = frozenset(
    {"draft", "active", "superseded", "archived", "contradicted", "stale"}
)

_ALLOWED_ORDER_BY: Final[frozenset[str]] = frozenset(
    {
        "importance DESC",
        "importance ASC",
        "created_at DESC",
        "created_at ASC",
        "last_accessed_at DESC",
        "last_accessed_at ASC",
        "access_count DESC",
    }
)


def _now_iso() -> str:
    """Return the current time as an ISO-8601 string with ``Z`` suffix."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _row_to_dict(row: sqlite3.Row | tuple[Any, ...]) -> dict[str, Any]:
    """Decode a ``memory_entries`` row into a JSON-ready dict."""
    (
        memory_id,
        project_id,
        scope,
        dataset_id,
        memory_type,
        text,
        importance,
        confidence,
        status,
        created_at,
        last_validated_at,
        last_accessed_at,
        access_count,
        evidence_json,
        tags,
        superseded_by,
    ) = row
    return {
        "memory_id": memory_id,
        "project_id": project_id,
        "scope": scope,
        "dataset_id": dataset_id,
        "memory_type": memory_type,
        "text": text,
        "importance": importance,
        "confidence": confidence,
        "status": status,
        "created_at": created_at,
        "last_validated_at": last_validated_at,
        "last_accessed_at": last_accessed_at,
        "access_count": access_count,
        "evidence": json.loads(evidence_json) if evidence_json else None,
        "tags": json.loads(tags) if tags else None,
        "superseded_by": superseded_by,
    }


_SELECT_COLUMNS: Final[str] = (
    "memory_id, project_id, scope, dataset_id, memory_type, text, "
    "importance, confidence, status, created_at, last_validated_at, "
    "last_accessed_at, access_count, evidence_json, tags, superseded_by"
)


# -- public API -------------------------------------------------------------


def propose(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    scope: str,
    memory_type: str,
    text: str,
    importance: float = 5.0,
    confidence: float = 0.5,
    evidence: list[Any] | None = None,
    tags: list[str] | None = None,
    dataset_id: str | None = None,
    session_id: str | None = None,
) -> str:
    """Insert a draft memory + its FTS row + a ``memory_write`` event.

    Drafts are the only thing extraction writes; the curation ritual is
    what promotes them to ``active``. Spec §10.1.

    Raises
    ------
    ValueError
        If ``scope`` or ``memory_type`` is unknown, or if ``scope='dataset'``
        is passed without ``dataset_id``.
    sqlite3.IntegrityError
        If ``project_id`` violates the foreign key.
    """
    if scope not in SCOPES:
        raise ValueError(f"unknown scope {scope!r}; expected one of {sorted(SCOPES)}")
    if memory_type not in MEMORY_TYPES:
        raise ValueError(
            f"unknown memory_type {memory_type!r}; expected one of {sorted(MEMORY_TYPES)}"
        )
    if scope == "dataset" and dataset_id is None:
        raise ValueError("scope='dataset' requires dataset_id")

    memory_id = uuid.uuid4().hex
    ts = _now_iso()
    evidence_json = json.dumps(evidence) if evidence is not None else None
    tags_json = json.dumps(tags) if tags is not None else None
    # FTS index over ``tags`` uses the raw JSON text; that's fine for BM25
    # because tokens like ``["spikes","noise"]`` still split on the default
    # tokenizer.

    conn.execute("BEGIN IMMEDIATE")
    try:
        cursor = conn.execute(
            "INSERT INTO memory_entries ("
            "memory_id, project_id, scope, dataset_id, memory_type, text, "
            "importance, confidence, status, created_at, evidence_json, tags"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?, ?)",
            (
                memory_id,
                project_id,
                scope,
                dataset_id,
                memory_type,
                text,
                importance,
                confidence,
                ts,
                evidence_json,
                tags_json,
            ),
        )
        rowid = cursor.lastrowid
        conn.execute(
            "INSERT INTO memory_entries_fts(rowid, text, tags) VALUES (?, ?, ?)",
            (rowid, text, tags_json or ""),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    events_mod.append_event(
        conn,
        project_id=project_id,
        type=events_mod.EVT_MEMORY_WRITE,
        session_id=session_id,
        payload={
            "memory_id": memory_id,
            "memory_type": memory_type,
            "scope": scope,
            "status": "draft",
            "importance": importance,
        },
    )
    return memory_id


def _fetch_project_id(conn: sqlite3.Connection, memory_id: str) -> tuple[str, str] | None:
    """Return ``(project_id, status)`` for ``memory_id`` or ``None``."""
    row = conn.execute(
        "SELECT project_id, status FROM memory_entries WHERE memory_id = ?",
        (memory_id,),
    ).fetchone()
    if row is None:
        return None
    return (row[0], row[1])


def commit_pending(
    conn: sqlite3.Connection, ids: list[str], *, session_id: str | None = None
) -> None:
    """Flip each draft memory in ``ids`` to ``status='active'``.

    Emits one ``memory_update`` event per id. Ids that are already active
    (or don't exist) are silently skipped — the curation UI can call this
    idempotently on a batch.
    """
    if not ids:
        return
    for memory_id in ids:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT project_id, status FROM memory_entries WHERE memory_id = ?",
                (memory_id,),
            ).fetchone()
            if row is None or row[1] != "draft":
                conn.execute("COMMIT")
                continue
            project_id = row[0]
            conn.execute(
                "UPDATE memory_entries SET status = 'active' WHERE memory_id = ?",
                (memory_id,),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        events_mod.append_event(
            conn,
            project_id=project_id,
            type=events_mod.EVT_MEMORY_UPDATE,
            session_id=session_id,
            payload={"memory_id": memory_id, "status": "active", "from_status": "draft"},
        )
        _enqueue_embedding(conn, memory_id)


def _enqueue_embedding(conn: sqlite3.Connection, memory_id: str) -> None:
    """Fire-and-forget embed hook (REVAMP Task 11.4).

    No-op unless :func:`embedding_worker.start_worker` has been called
    and the DB path is resolvable — keeping V1 memory paths risk-free.
    """
    try:
        from pathlib import Path as _Path

        from iris.projects import embedding_worker as _ew

        row = conn.execute(
            "SELECT text FROM memory_entries WHERE memory_id = ?", (memory_id,)
        ).fetchone()
        if row is None or not row[0]:
            return
        db_file = None
        db_row = conn.execute("PRAGMA database_list").fetchone()
        if db_row and db_row[2]:
            db_file = _Path(db_row[2]).parent
        if db_file is None:
            return
        _ew.enqueue(
            _ew.EmbedJob(
                kind="memory_entry",
                project_path=db_file,
                entity_id=memory_id,
                text=str(row[0]),
            )
        )
    except Exception:  # noqa: BLE001 - hot path must never raise
        pass


def discard_pending(conn: sqlite3.Connection, ids: list[str]) -> None:
    """Hard-delete draft rows in ``ids``. Non-draft rows are left alone.

    No event is written — rejected drafts have no audit-trail value
    (spec §10.4). The FTS shadow row is deleted via the external-content
    ``'delete'`` command so the virtual table stays in sync.
    """
    if not ids:
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        for memory_id in ids:
            row = conn.execute(
                "SELECT rowid, text, tags, status FROM memory_entries WHERE memory_id = ?",
                (memory_id,),
            ).fetchone()
            if row is None or row[3] != "draft":
                continue
            rowid, text, tags, _status = row
            conn.execute(
                "INSERT INTO memory_entries_fts(memory_entries_fts, rowid, text, tags) "
                "VALUES('delete', ?, ?, ?)",
                (rowid, text, tags or ""),
            )
            conn.execute("DELETE FROM memory_entries WHERE memory_id = ?", (memory_id,))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def query(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    memory_type: str | None = None,
    status: str | None = "active",
    dataset_id: str | None = None,
    scope: str | None = None,
    limit: int = 100,
    order_by: str = "importance DESC",
) -> list[dict[str, Any]]:
    """Return memory rows matching the given filters, decoded to dicts.

    Pass ``status=None`` to skip the status filter (useful for the curation
    UI which shows drafts + active together). ``order_by`` is whitelisted
    against :data:`_ALLOWED_ORDER_BY` — arbitrary strings are rejected to
    close a SQL-injection hole.
    """
    if order_by not in _ALLOWED_ORDER_BY:
        raise ValueError(
            f"unsupported order_by {order_by!r}; expected one of {sorted(_ALLOWED_ORDER_BY)}"
        )

    clauses = ["project_id = ?"]
    params: list[Any] = [project_id]
    if memory_type is not None:
        clauses.append("memory_type = ?")
        params.append(memory_type)
    if status is not None:
        clauses.append("status = ?")
        params.append(status)
    if dataset_id is not None:
        clauses.append("dataset_id = ?")
        params.append(dataset_id)
    if scope is not None:
        clauses.append("scope = ?")
        params.append(scope)

    sql = (
        f"SELECT {_SELECT_COLUMNS} FROM memory_entries "
        f"WHERE {' AND '.join(clauses)} "
        f"ORDER BY {order_by} "
        f"LIMIT ?"
    )
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    return [_row_to_dict(r) for r in rows]


def set_status(
    conn: sqlite3.Connection,
    id: str,
    new_status: str,
    *,
    session_id: str | None = None,
) -> None:
    """Transition ``id`` to ``new_status`` and write a ``memory_update`` event.

    Used by Phase 16 (contradiction/staleness) to flip statuses in bulk.
    For archive specifically, prefer :func:`soft_delete` — it picks the
    right event type (``memory_delete``).

    Raises
    ------
    ValueError
        On unknown status, or if the memory does not exist.
    """
    if new_status not in STATUSES:
        raise ValueError(f"unknown status {new_status!r}; expected one of {sorted(STATUSES)}")
    found = _fetch_project_id(conn, id)
    if found is None:
        raise ValueError(f"memory {id!r} does not exist")
    project_id, from_status = found
    if from_status == new_status:
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "UPDATE memory_entries SET status = ? WHERE memory_id = ?",
            (new_status, id),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    events_mod.append_event(
        conn,
        project_id=project_id,
        type=events_mod.EVT_MEMORY_UPDATE,
        session_id=session_id,
        payload={"memory_id": id, "status": new_status, "from_status": from_status},
    )


def supersede(
    conn: sqlite3.Connection,
    *,
    old_id: str,
    new_id: str,
    session_id: str | None = None,
) -> None:
    """Mark ``old_id`` superseded by ``new_id``.

    Sets ``superseded_by = new_id`` and ``status = 'superseded'`` on the
    old row, then writes a ``memory_update`` event. The new memory must
    already exist; we don't auto-create it.

    Raises
    ------
    ValueError
        If either id is missing.
    """
    old = _fetch_project_id(conn, old_id)
    new = _fetch_project_id(conn, new_id)
    if old is None:
        raise ValueError(f"memory {old_id!r} does not exist")
    if new is None:
        raise ValueError(f"memory {new_id!r} does not exist")
    project_id, from_status = old
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "UPDATE memory_entries SET superseded_by = ?, status = 'superseded' "
            "WHERE memory_id = ?",
            (new_id, old_id),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    events_mod.append_event(
        conn,
        project_id=project_id,
        type=events_mod.EVT_MEMORY_UPDATE,
        session_id=session_id,
        payload={
            "memory_id": old_id,
            "status": "superseded",
            "from_status": from_status,
            "superseded_by": new_id,
        },
    )


def soft_delete(conn: sqlite3.Connection, id: str, *, session_id: str | None = None) -> None:
    """Archive a memory and write a ``memory_delete`` event.

    Non-destructive by design: the row stays queryable with
    ``status='archived'`` so lineage is preserved (spec §10.4 contrasts
    this against draft :func:`discard_pending`).
    """
    found = _fetch_project_id(conn, id)
    if found is None:
        raise ValueError(f"memory {id!r} does not exist")
    project_id, from_status = found
    if from_status == "archived":
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "UPDATE memory_entries SET status = 'archived' WHERE memory_id = ?",
            (id,),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    events_mod.append_event(
        conn,
        project_id=project_id,
        type=events_mod.EVT_MEMORY_DELETE,
        session_id=session_id,
        payload={"memory_id": id, "status": "archived", "from_status": from_status},
    )


def touch(conn: sqlite3.Connection, id: str) -> None:
    """Bump ``last_accessed_at`` + ``access_count``. Used by retrieval.

    Silently no-op if the memory doesn't exist — touching a vanished
    memory during retrieval is not an error worth raising.
    """
    ts = _now_iso()
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "UPDATE memory_entries "
            "SET last_accessed_at = ?, access_count = COALESCE(access_count, 0) + 1 "
            "WHERE memory_id = ?",
            (ts, id),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
