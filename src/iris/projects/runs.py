"""Analysis run lifecycle + lineage DAG (spec §4 Layer 4, §7.1 runs table).

Every pipeline execution — operation, plot, statistical test, LLM
reasoning step — writes a ``runs`` row so later sessions can reconstruct
*what* ran, *on what inputs*, and *whether it worked*. Runs form a DAG
via ``parent_run_id`` so branching exploration (re-run with different
params, compare two approaches) stays traceable.

Lifecycle
---------
1. :func:`start_run` inserts a row with ``status='running'`` and emits a
   ``transform_run`` event carrying ``{run_id, phase: 'start', ...}``.
2. :func:`complete_run` flips the row to ``status='completed'``, fills
   output metadata + ``execution_time_ms``, and emits another
   ``transform_run`` event (``phase: 'complete'``).
3. :func:`fail_run` flips to ``status='failed'`` with ``error_text`` and
   (optional) ``failure_reflection``; emits ``transform_run`` (``phase:
   'fail'``).

Lineage
-------
:func:`query_lineage` walks ``parent_run_id`` both directions with a
recursive CTE, returning ``{ancestors, descendants}`` for UI/LLM
consumption. Cycles are impossible in practice (parents are set once at
start and never mutated) but the CTE uses ``UNION`` rather than ``UNION
ALL`` so a pathological cycle terminates.

See ``IRIS Memory Restructure.md`` §4 (Layer 4) and §7.1 (rationale for
column choices).
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from typing import Any, Final

from iris.projects import events as events_mod

__all__ = [
    "RUN_STATUSES",
    "complete_run",
    "fail_run",
    "list_runs",
    "query_lineage",
    "start_run",
]

RUN_STATUSES: Final[frozenset[str]] = frozenset({"running", "completed", "failed"})


def _now_iso() -> str:
    """Return the current time as an ISO-8601 string with ``Z`` suffix."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


_SELECT_COLUMNS: Final[str] = (
    "run_id, parent_run_id, project_id, session_id, event_id, "
    "operation_type, operation_id, input_data_hash, input_versions_json, "
    "output_data_hash, output_artifact_ids, parameters_json, code_executed, "
    "llm_prompt_hash, llm_model, findings_text, status, error_text, "
    "failure_reflection, created_at, execution_time_ms"
)


def _row_to_dict(row: sqlite3.Row | tuple[Any, ...]) -> dict[str, Any]:
    """Decode a ``runs`` row into a JSON-ready dict."""
    (
        run_id,
        parent_run_id,
        project_id,
        session_id,
        event_id,
        operation_type,
        operation_id,
        input_data_hash,
        input_versions_json,
        output_data_hash,
        output_artifact_ids,
        parameters_json,
        code_executed,
        llm_prompt_hash,
        llm_model,
        findings_text,
        status,
        error_text,
        failure_reflection,
        created_at,
        execution_time_ms,
    ) = row
    return {
        "run_id": run_id,
        "parent_run_id": parent_run_id,
        "project_id": project_id,
        "session_id": session_id,
        "event_id": event_id,
        "operation_type": operation_type,
        "operation_id": operation_id,
        "input_data_hash": input_data_hash,
        "input_versions": json.loads(input_versions_json) if input_versions_json else None,
        "output_data_hash": output_data_hash,
        "output_artifact_ids": json.loads(output_artifact_ids) if output_artifact_ids else None,
        "parameters": json.loads(parameters_json) if parameters_json else None,
        "code_executed": code_executed,
        "llm_prompt_hash": llm_prompt_hash,
        "llm_model": llm_model,
        "findings_text": findings_text,
        "status": status,
        "error_text": error_text,
        "failure_reflection": failure_reflection,
        "created_at": created_at,
        "execution_time_ms": execution_time_ms,
    }


# -- public API -------------------------------------------------------------


def start_run(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    session_id: str,
    operation_type: str,
    operation_id: str | None = None,
    parent_run_id: str | None = None,
    input_versions: list[str] | None = None,
    input_data_hash: str | None = None,
    parameters: dict[str, Any] | None = None,
    code: str | None = None,
    llm_model: str | None = None,
    llm_prompt_hash: str | None = None,
) -> str:
    """Insert a ``running`` run row and emit a ``transform_run`` start event.

    ``operation_type`` is the free-form high-level label (``"plot"``,
    ``"correlation_analysis"``, ...). ``operation_id`` is the optional FK
    into the ``operations`` catalog when a stored op was used.

    Raises
    ------
    sqlite3.IntegrityError
        If ``project_id`` / ``session_id`` / ``parent_run_id`` violate a
        foreign key.
    """
    run_id = uuid.uuid4().hex
    ts = _now_iso()
    input_versions_json = json.dumps(input_versions) if input_versions is not None else None
    parameters_json = json.dumps(parameters) if parameters is not None else None

    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "INSERT INTO runs ("
            "run_id, parent_run_id, project_id, session_id, "
            "operation_type, operation_id, input_data_hash, input_versions_json, "
            "parameters_json, code_executed, llm_model, llm_prompt_hash, "
            "status, created_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'running', ?)",
            (
                run_id,
                parent_run_id,
                project_id,
                session_id,
                operation_type,
                operation_id,
                input_data_hash,
                input_versions_json,
                parameters_json,
                code,
                llm_model,
                llm_prompt_hash,
                ts,
            ),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    events_mod.append_event(
        conn,
        project_id=project_id,
        type=events_mod.EVT_TRANSFORM_RUN,
        session_id=session_id,
        payload={
            "run_id": run_id,
            "phase": "start",
            "operation_type": operation_type,
            "operation_id": operation_id,
            "parent_run_id": parent_run_id,
        },
    )
    return run_id


def _fetch_run_meta(
    conn: sqlite3.Connection, run_id: str
) -> tuple[str, str | None, str, str] | None:
    """Return ``(project_id, session_id, status, created_at)`` or ``None``."""
    row = conn.execute(
        "SELECT project_id, session_id, status, created_at FROM runs WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    if row is None:
        return None
    return (row[0], row[1], row[2], row[3])


def _elapsed_ms(started_iso: str) -> int:
    """Return ms between ``started_iso`` and now. Clamped to >= 0."""
    try:
        started = datetime.strptime(started_iso, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    except ValueError:
        # TODO: accept non-microsecond ISO stamps if we ever change _now_iso
        return 0
    delta = datetime.now(UTC) - started
    return max(0, int(delta.total_seconds() * 1000))


def complete_run(
    conn: sqlite3.Connection,
    run_id: str,
    *,
    output_data_hash: str | None = None,
    output_artifact_ids: list[str] | None = None,
    findings_text: str | None = None,
    execution_time_ms: int | None = None,
) -> None:
    """Mark ``run_id`` completed and emit a ``transform_run`` complete event.

    If ``execution_time_ms`` is not supplied we compute it from
    ``created_at`` vs. now. Non-running runs are left alone (idempotent).

    Raises
    ------
    ValueError
        If ``run_id`` does not exist.
    """
    meta = _fetch_run_meta(conn, run_id)
    if meta is None:
        raise ValueError(f"run {run_id!r} does not exist")
    project_id, session_id, status, created_at = meta
    if status != "running":
        return

    if execution_time_ms is None:
        execution_time_ms = _elapsed_ms(created_at)

    output_artifact_ids_json = (
        json.dumps(output_artifact_ids) if output_artifact_ids is not None else None
    )

    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "UPDATE runs SET "
            "status = 'completed', "
            "output_data_hash = ?, "
            "output_artifact_ids = ?, "
            "findings_text = ?, "
            "execution_time_ms = ? "
            "WHERE run_id = ?",
            (
                output_data_hash,
                output_artifact_ids_json,
                findings_text,
                execution_time_ms,
                run_id,
            ),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    events_mod.append_event(
        conn,
        project_id=project_id,
        type=events_mod.EVT_TRANSFORM_RUN,
        session_id=session_id,
        payload={
            "run_id": run_id,
            "phase": "complete",
            "execution_time_ms": execution_time_ms,
            "output_artifact_ids": output_artifact_ids or [],
        },
    )


def fail_run(
    conn: sqlite3.Connection,
    run_id: str,
    *,
    error_text: str,
    failure_reflection: str | None = None,
) -> None:
    """Mark ``run_id`` failed with ``error_text`` + optional reflection.

    Emits a ``transform_run`` fail event. Non-running runs are left alone.

    Raises
    ------
    ValueError
        If ``run_id`` does not exist.
    """
    meta = _fetch_run_meta(conn, run_id)
    if meta is None:
        raise ValueError(f"run {run_id!r} does not exist")
    project_id, session_id, status, created_at = meta
    if status != "running":
        return

    execution_time_ms = _elapsed_ms(created_at)

    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "UPDATE runs SET "
            "status = 'failed', "
            "error_text = ?, "
            "failure_reflection = ?, "
            "execution_time_ms = ? "
            "WHERE run_id = ?",
            (error_text, failure_reflection, execution_time_ms, run_id),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    events_mod.append_event(
        conn,
        project_id=project_id,
        type=events_mod.EVT_TRANSFORM_RUN,
        session_id=session_id,
        payload={
            "run_id": run_id,
            "phase": "fail",
            "error_text": error_text,
            "execution_time_ms": execution_time_ms,
        },
    )


def list_runs(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    session_id: str | None = None,
    status: str | None = None,
    operation_type: str | None = None,
    since: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """List runs matching filters, newest-first.

    ``since`` is an ISO-8601 timestamp: only rows with
    ``created_at >= since`` are returned.
    """
    if status is not None and status not in RUN_STATUSES:
        raise ValueError(f"unknown status {status!r}; expected one of {sorted(RUN_STATUSES)}")

    clauses = ["project_id = ?"]
    params: list[Any] = [project_id]
    if session_id is not None:
        clauses.append("session_id = ?")
        params.append(session_id)
    if status is not None:
        clauses.append("status = ?")
        params.append(status)
    if operation_type is not None:
        clauses.append("operation_type = ?")
        params.append(operation_type)
    if since is not None:
        clauses.append("created_at >= ?")
        params.append(since)

    sql = (
        f"SELECT {_SELECT_COLUMNS} FROM runs "
        f"WHERE {' AND '.join(clauses)} "
        f"ORDER BY created_at DESC, rowid DESC "
        f"LIMIT ?"
    )
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    return [_row_to_dict(r) for r in rows]


# -- lineage ----------------------------------------------------------------


_ANCESTORS_CTE: Final[str] = f"""
    WITH RECURSIVE ancestry(run_id) AS (
        SELECT parent_run_id FROM runs WHERE run_id = ? AND parent_run_id IS NOT NULL
        UNION
        SELECT r.parent_run_id FROM runs r
        JOIN ancestry a ON r.run_id = a.run_id
        WHERE r.parent_run_id IS NOT NULL
    )
    SELECT {_SELECT_COLUMNS} FROM runs WHERE run_id IN (SELECT run_id FROM ancestry)
    ORDER BY created_at ASC
"""

_DESCENDANTS_CTE: Final[str] = f"""
    WITH RECURSIVE descendants(run_id) AS (
        SELECT run_id FROM runs WHERE parent_run_id = ?
        UNION
        SELECT r.run_id FROM runs r
        JOIN descendants d ON r.parent_run_id = d.run_id
    )
    SELECT {_SELECT_COLUMNS} FROM runs WHERE run_id IN (SELECT run_id FROM descendants)
    ORDER BY created_at ASC
"""


def query_lineage(conn: sqlite3.Connection, run_id: str) -> dict[str, list[dict[str, Any]]]:
    """Return the ancestor + descendant DAG slices for ``run_id``.

    - ``ancestors``: oldest → newest, following ``parent_run_id`` upward.
    - ``descendants``: oldest → newest, following ``parent_run_id``
      downward (``run_id`` itself is excluded from both lists).

    Missing runs return empty lists rather than raising — callers often
    probe lineage speculatively.
    """
    ancestors = [_row_to_dict(r) for r in conn.execute(_ANCESTORS_CTE, (run_id,)).fetchall()]
    descendants = [_row_to_dict(r) for r in conn.execute(_DESCENDANTS_CTE, (run_id,)).fetchall()]
    return {"ancestors": ancestors, "descendants": descendants}
