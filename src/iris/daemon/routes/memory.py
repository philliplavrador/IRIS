"""Memory-layer HTTP routes for the IRIS daemon.

Phase 2 (Task 2.4) reactivates this router. The Phase 0 stub handlers are
gone — the endpoints listed below return real data. Everything else on the
legacy surface (/memory/recall, /memory/commit_session_writes, etc.) is
still absent; Phases 3-10 will add those as their corresponding modules
land.

Endpoints (all mounted under ``/api`` by ``daemon.app``)::

    GET  /memory/events                   List events (project-scoped, filterable)
    GET  /memory/events/{event_id}        Fetch one event
    POST /memory/events/verify_chain      Verify hash-chain integrity
    POST /memory/sessions/start           Open a memory-layer session
    POST /memory/sessions/{sid}/end       Close a session + stamp summary
    GET  /memory/sessions/{sid}           Fetch a session row
    POST /memory/messages                 Append one chat message
    GET  /memory/messages                 List messages for a session
    GET  /memory/messages/search          FTS5 BM25 search across a project
    POST /memory/tool_calls               Append one tool-call row
    PATCH /memory/tool_calls/{id}/output_artifact  Attach artifact id to a tool-call
    POST /memory/entries                  Propose a draft memory
    POST /memory/entries/commit           Flip drafts to active
    POST /memory/entries/discard          Hard-delete drafts
    GET  /memory/entries                  Query/filter entries
    GET  /memory/entries/{id}             Fetch one entry
    PATCH /memory/entries/{id}/status     Transition status
    POST /memory/entries/supersede        Supersede one entry with another
    DELETE /memory/entries/{id}           Soft-delete (archive)
    POST /memory/extract                  LLM session extraction (lazy import)

All routes resolve the **active** project via
:func:`iris.projects.resolve_active_project`. There is no ``?project=``
override for now — the daemon is single-tenant by design (spec §6 + the
active-project contract). Callers that need to operate on a different
project must flip the active pointer first via ``POST /api/projects/active``.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from iris.projects import db as _db
from iris.projects import events as _events
from iris.projects import memory_entries as _memory_entries
from iris.projects import messages as _messages
from iris.projects import resolve_active_project
from iris.projects import sessions as _sessions
from iris.projects import tool_calls as _tool_calls

router = APIRouter(tags=["memory"])


# -- helpers ----------------------------------------------------------------


def _active_project() -> Path:
    """Return the active project path or raise ``HTTPException(400)``."""
    path = resolve_active_project()
    if path is None:
        raise HTTPException(
            status_code=400,
            detail="No active project; POST /api/projects/active first.",
        )
    return path


def _project_id_for(path: Path) -> str:
    """Derive the stable ``project_id`` for a project on disk.

    V1 uses the project's directory name as its ``project_id``. This keeps
    the identifier deterministic (restarting the daemon gets the same id)
    without needing to persist a separate UUID in ``config.toml``.
    """
    return path.name


def _ensure_project_row(conn: sqlite3.Connection, project_id: str, name: str) -> None:
    """Upsert a row in ``projects`` so FK constraints are satisfied.

    ``iris.projects.create_project`` initialises the schema but does **not**
    insert a projects row — nothing in Phase 1 required it. The first time a
    memory-layer write happens we backfill that row here. Idempotent via
    ``INSERT OR IGNORE``; ``updated_at`` is refreshed on every call so
    ``SELECT name, updated_at FROM projects`` reflects recent activity.
    """
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute(
        "INSERT OR IGNORE INTO projects (project_id, name, created_at, updated_at) "
        "VALUES (?, ?, ?, ?)",
        (project_id, name, now, now),
    )
    conn.execute(
        "UPDATE projects SET updated_at = ? WHERE project_id = ?",
        (now, project_id),
    )


def _open() -> tuple[sqlite3.Connection, str]:
    """Open the active project's DB and return ``(conn, project_id)``.

    The connection is caller-closed; every route handler wraps this in a
    try/finally to close. Raises ``HTTPException(400)`` when no project is
    active and ``HTTPException(500)`` if schema init fails.
    """
    path = _active_project()
    conn = _db.connect(path)
    try:
        _db.init_schema(conn)
        project_id = _project_id_for(path)
        _ensure_project_row(conn, project_id, path.name)
    except Exception:
        conn.close()
        raise
    return conn, project_id


def _row_to_event_dict(row: sqlite3.Row) -> dict[str, Any]:
    """Shape an ``events`` row for the HTTP response.

    ``payload_json`` is decoded back into a dict so callers don't have to
    parse strings. If the row was written through :func:`events.append_event`
    this is guaranteed to be valid JSON; a ``JSONDecodeError`` here means
    the DB was tampered with outside the public API and the route returns
    the raw string as a fallback under a ``payload_raw`` key.
    """
    payload_raw = row["payload_json"]
    try:
        payload: Any = json.loads(payload_raw)
        return {
            "event_id": row["event_id"],
            "project_id": row["project_id"],
            "session_id": row["session_id"],
            "ts": row["ts"],
            "type": row["type"],
            "payload": payload,
            "prev_event_hash": row["prev_event_hash"],
            "event_hash": row["event_hash"],
        }
    except json.JSONDecodeError:
        return {
            "event_id": row["event_id"],
            "project_id": row["project_id"],
            "session_id": row["session_id"],
            "ts": row["ts"],
            "type": row["type"],
            "payload_raw": payload_raw,
            "prev_event_hash": row["prev_event_hash"],
            "event_hash": row["event_hash"],
        }


# -- request bodies ---------------------------------------------------------


class StartSessionRequest(BaseModel):
    model_provider: str = Field(min_length=1)
    model_name: str = Field(min_length=1)
    system_prompt: str


class EndSessionRequest(BaseModel):
    summary: str


class AppendMessageRequest(BaseModel):
    session_id: str = Field(min_length=1)
    role: str = Field(min_length=1)
    content: str
    event_id: str | None = None
    token_count: int | None = None


class AppendToolCallRequest(BaseModel):
    session_id: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    input: Any
    success: bool
    event_id: str | None = None
    output_summary: str | None = None
    output_artifact_id: str | None = None
    error: str | None = None
    execution_time_ms: int | None = None


class AttachArtifactRequest(BaseModel):
    artifact_id: str = Field(min_length=1)


class ProposeMemoryRequest(BaseModel):
    scope: str = Field(min_length=1)
    memory_type: str = Field(min_length=1)
    text: str = Field(min_length=1)
    importance: float = 5.0
    confidence: float = 0.5
    evidence: list[Any] | None = None
    tags: list[str] | None = None
    dataset_id: str | None = None
    session_id: str | None = None


class IdsRequest(BaseModel):
    ids: list[str]
    session_id: str | None = None


class StatusRequest(BaseModel):
    status: str = Field(min_length=1)
    session_id: str | None = None


class SupersedeRequest(BaseModel):
    old_id: str = Field(min_length=1)
    new_id: str = Field(min_length=1)
    session_id: str | None = None


class ExtractRequest(BaseModel):
    session_id: str = Field(min_length=1)


# -- events -----------------------------------------------------------------


@router.get("/memory/events")
async def list_events(
    type: str | None = Query(default=None),
    since: str | None = Query(default=None, description="ISO-8601 lower bound on ts (inclusive)"),
    until: str | None = Query(default=None, description="ISO-8601 upper bound on ts (exclusive)"),
    session_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=10_000),
) -> dict[str, Any]:
    """List events for the active project with optional filters."""
    conn, project_id = _open()
    try:
        if type is not None and type not in _events.EVENT_TYPES:
            raise HTTPException(status_code=400, detail=f"unknown event type {type!r}")

        clauses = ["project_id = ?"]
        params: list[Any] = [project_id]
        if type is not None:
            clauses.append("type = ?")
            params.append(type)
        if since is not None:
            clauses.append("ts >= ?")
            params.append(since)
        if until is not None:
            clauses.append("ts < ?")
            params.append(until)
        if session_id is not None:
            clauses.append("session_id = ?")
            params.append(session_id)

        sql = (
            "SELECT event_id, project_id, session_id, ts, type, payload_json, "
            "prev_event_hash, event_hash FROM events WHERE "
            + " AND ".join(clauses)
            + " ORDER BY rowid DESC LIMIT ?"
        )
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
        return {"data": [_row_to_event_dict(r) for r in rows]}
    finally:
        conn.close()


@router.get("/memory/events/{event_id}")
async def get_event(event_id: str) -> dict[str, Any]:
    """Fetch a single event by id (project-scoped)."""
    conn, project_id = _open()
    try:
        row = conn.execute(
            "SELECT event_id, project_id, session_id, ts, type, payload_json, "
            "prev_event_hash, event_hash FROM events "
            "WHERE event_id = ? AND project_id = ?",
            (event_id, project_id),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"event {event_id!r} not found")
        return {"data": _row_to_event_dict(row)}
    finally:
        conn.close()


@router.post("/memory/events/verify_chain")
async def verify_chain() -> dict[str, Any]:
    """Re-walk the hash chain for the active project; return integrity report."""
    conn, project_id = _open()
    try:
        result = _events.verify_chain(conn, project_id)
        return {
            "data": {
                "valid": result["valid"],
                "first_break": result["first_break"],
                "checked": result["checked"],
            }
        }
    finally:
        conn.close()


# -- sessions ---------------------------------------------------------------


@router.post("/memory/sessions/start")
async def start_session(req: StartSessionRequest) -> dict[str, Any]:
    """Open a new memory-layer session. Returns the new ``session_id``."""
    conn, project_id = _open()
    try:
        session_id = _sessions.start_session(
            conn,
            project_id=project_id,
            model_provider=req.model_provider,
            model_name=req.model_name,
            system_prompt=req.system_prompt,
        )
        return {"data": _sessions.get_session(conn, session_id)}
    except sqlite3.IntegrityError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    finally:
        conn.close()


@router.post("/memory/sessions/{session_id}/end")
async def end_session(session_id: str, req: EndSessionRequest) -> dict[str, Any]:
    """Stamp ``ended_at`` + ``summary`` on a session and log ``session_ended``."""
    conn, _ = _open()
    try:
        try:
            _sessions.end_session(conn, session_id=session_id, summary=req.summary)
        except LookupError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        return {"data": _sessions.get_session(conn, session_id)}
    finally:
        conn.close()


@router.get("/memory/sessions/{session_id}")
async def get_session(session_id: str) -> dict[str, Any]:
    """Fetch a session row."""
    conn, _ = _open()
    try:
        try:
            return {"data": _sessions.get_session(conn, session_id)}
        except LookupError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
    finally:
        conn.close()


# -- messages ---------------------------------------------------------------


@router.post("/memory/messages")
async def append_message(req: AppendMessageRequest) -> dict[str, Any]:
    """Append one chat message to the active project."""
    conn, _ = _open()
    try:
        try:
            message_id = _messages.append_message(
                conn,
                session_id=req.session_id,
                role=req.role,
                content=req.content,
                event_id=req.event_id,
                token_count=req.token_count,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except sqlite3.IntegrityError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return {"data": {"message_id": message_id}}
    finally:
        conn.close()


@router.get("/memory/messages")
async def list_messages(
    session_id: str = Query(..., min_length=1),
    limit: int = Query(default=100, ge=1, le=10_000),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """List messages for a session in chronological order."""
    conn, _ = _open()
    try:
        rows = conn.execute(
            "SELECT message_id, session_id, event_id, role, content, ts, token_count "
            "FROM messages WHERE session_id = ? "
            "ORDER BY rowid ASC LIMIT ? OFFSET ?",
            (session_id, limit, offset),
        ).fetchall()
        return {"data": [dict(r) for r in rows]}
    finally:
        conn.close()


@router.get("/memory/messages/search")
async def search_messages(
    q: str = Query(..., min_length=1),
    limit: int = Query(default=20, ge=1, le=500),
) -> dict[str, Any]:
    """FTS5 BM25 search over messages in the active project."""
    conn, project_id = _open()
    try:
        try:
            hits = _messages.search(conn, project_id=project_id, query=q, limit=limit)
        except sqlite3.OperationalError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return {"data": hits}
    finally:
        conn.close()


# -- tool_calls -------------------------------------------------------------


@router.post("/memory/tool_calls")
async def append_tool_call(req: AppendToolCallRequest) -> dict[str, Any]:
    """Append one tool-call row to the active project."""
    conn, _ = _open()
    try:
        try:
            tool_call_id = _tool_calls.append_tool_call(
                conn,
                session_id=req.session_id,
                tool_name=req.tool_name,
                input=req.input,
                success=req.success,
                event_id=req.event_id,
                output_summary=req.output_summary,
                output_artifact_id=req.output_artifact_id,
                error=req.error,
                execution_time_ms=req.execution_time_ms,
            )
        except sqlite3.IntegrityError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return {"data": {"tool_call_id": tool_call_id}}
    finally:
        conn.close()


@router.patch("/memory/tool_calls/{tool_call_id}/output_artifact")
async def attach_tool_call_artifact(
    tool_call_id: str, req: AttachArtifactRequest
) -> dict[str, Any]:
    """Late-bind an artifact id onto a stored tool-call row."""
    conn, _ = _open()
    try:
        try:
            _tool_calls.attach_output_artifact(conn, tool_call_id, req.artifact_id)
        except LookupError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        return {"data": {"tool_call_id": tool_call_id, "artifact_id": req.artifact_id}}
    finally:
        conn.close()


# -- memory entries ---------------------------------------------------------


_MEMORY_SELECT_COLUMNS = (
    "memory_id, project_id, scope, dataset_id, memory_type, text, "
    "importance, confidence, status, created_at, last_validated_at, "
    "last_accessed_at, access_count, evidence_json, tags, superseded_by"
)


def _fetch_memory_row(conn: sqlite3.Connection, memory_id: str, project_id: str) -> dict[str, Any]:
    """Return a single memory_entries row as a dict or raise 404."""
    row = conn.execute(
        f"SELECT {_MEMORY_SELECT_COLUMNS} FROM memory_entries "
        "WHERE memory_id = ? AND project_id = ?",
        (memory_id, project_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"memory {memory_id!r} not found")
    evidence_raw = row["evidence_json"]
    tags_raw = row["tags"]
    return {
        "memory_id": row["memory_id"],
        "project_id": row["project_id"],
        "scope": row["scope"],
        "dataset_id": row["dataset_id"],
        "memory_type": row["memory_type"],
        "text": row["text"],
        "importance": row["importance"],
        "confidence": row["confidence"],
        "status": row["status"],
        "created_at": row["created_at"],
        "last_validated_at": row["last_validated_at"],
        "last_accessed_at": row["last_accessed_at"],
        "access_count": row["access_count"],
        "evidence": json.loads(evidence_raw) if evidence_raw else None,
        "tags": json.loads(tags_raw) if tags_raw else None,
        "superseded_by": row["superseded_by"],
    }


@router.post("/memory/entries")
async def propose_memory(req: ProposeMemoryRequest) -> dict[str, Any]:
    """Insert a draft memory entry. Returns the new ``memory_id``."""
    conn, project_id = _open()
    try:
        try:
            memory_id = _memory_entries.propose(
                conn,
                project_id=project_id,
                scope=req.scope,
                memory_type=req.memory_type,
                text=req.text,
                importance=req.importance,
                confidence=req.confidence,
                evidence=req.evidence,
                tags=req.tags,
                dataset_id=req.dataset_id,
                session_id=req.session_id,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except sqlite3.IntegrityError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return {"data": {"memory_id": memory_id}}
    finally:
        conn.close()


@router.post("/memory/entries/commit")
async def commit_memory_entries(req: IdsRequest) -> dict[str, Any]:
    """Flip each draft memory in ``ids`` to ``status='active'``."""
    conn, _ = _open()
    try:
        _memory_entries.commit_pending(conn, req.ids, session_id=req.session_id)
        return {"data": {"committed": req.ids}}
    finally:
        conn.close()


@router.post("/memory/entries/discard")
async def discard_memory_entries(req: IdsRequest) -> dict[str, Any]:
    """Hard-delete draft memory rows in ``ids``."""
    conn, _ = _open()
    try:
        _memory_entries.discard_pending(conn, req.ids)
        return {"data": {"discarded": req.ids}}
    finally:
        conn.close()


@router.get("/memory/entries")
async def list_memory_entries(
    type: str | None = Query(default=None),
    status: str | None = Query(default="active"),
    scope: str | None = Query(default=None),
    dataset_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=10_000),
) -> dict[str, Any]:
    """Query memory entries for the active project with optional filters.

    Pass ``status=all`` to skip the status filter (the underlying module
    accepts ``None``; we translate the sentinel here).
    """
    conn, project_id = _open()
    try:
        effective_status: str | None = None if status == "all" else status
        try:
            rows = _memory_entries.query(
                conn,
                project_id=project_id,
                memory_type=type,
                status=effective_status,
                dataset_id=dataset_id,
                scope=scope,
                limit=limit,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return {"data": rows}
    finally:
        conn.close()


@router.get("/memory/entries/{memory_id}")
async def get_memory_entry(memory_id: str) -> dict[str, Any]:
    """Fetch a single memory entry by id (project-scoped)."""
    conn, project_id = _open()
    try:
        return {"data": _fetch_memory_row(conn, memory_id, project_id)}
    finally:
        conn.close()


@router.patch("/memory/entries/{memory_id}/status")
async def set_memory_status(memory_id: str, req: StatusRequest) -> dict[str, Any]:
    """Transition a memory entry to a new status."""
    conn, project_id = _open()
    try:
        # Scope-check first so we return 404 (not ValueError) for cross-project ids.
        _fetch_memory_row(conn, memory_id, project_id)
        try:
            _memory_entries.set_status(conn, memory_id, req.status, session_id=req.session_id)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return {"data": _fetch_memory_row(conn, memory_id, project_id)}
    finally:
        conn.close()


@router.post("/memory/entries/supersede")
async def supersede_memory_entry(req: SupersedeRequest) -> dict[str, Any]:
    """Mark ``old_id`` superseded by ``new_id``."""
    conn, _ = _open()
    try:
        try:
            _memory_entries.supersede(
                conn,
                old_id=req.old_id,
                new_id=req.new_id,
                session_id=req.session_id,
            )
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        return {"data": {"old_id": req.old_id, "new_id": req.new_id}}
    finally:
        conn.close()


@router.delete("/memory/entries/{memory_id}")
async def soft_delete_memory_entry(memory_id: str) -> dict[str, Any]:
    """Archive a memory entry (soft delete)."""
    conn, project_id = _open()
    try:
        _fetch_memory_row(conn, memory_id, project_id)
        try:
            _memory_entries.soft_delete(conn, memory_id)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        return {"data": _fetch_memory_row(conn, memory_id, project_id)}
    finally:
        conn.close()


@router.post("/memory/extract")
async def extract_memory(req: ExtractRequest) -> dict[str, Any]:
    """Run LLM extraction on a session's transcript, proposing draft memories.

    Imports :mod:`iris.projects.extraction` lazily so the daemon can start
    without ``ANTHROPIC_API_KEY`` set. If the module isn't importable yet
    (Task 4.2 lands in a sibling worktree), returns 503.
    """
    try:
        from iris.projects import extraction as _extraction  # noqa: PLC0415
    except ImportError as e:
        raise HTTPException(
            status_code=503,
            detail=f"extraction module unavailable: {e}",
        ) from e

    conn, _ = _open()
    try:
        try:
            ids = _extraction.extract_session(conn, req.session_id)
        except LookupError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return {"data": {"ids": list(ids)}}
    finally:
        conn.close()
