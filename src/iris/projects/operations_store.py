"""Operation catalog store (spec §4 L5, §7.1, §12).

Owns every write to the ``operations`` and ``operation_executions`` tables
and mirrors each operation into the ``operations_fts`` FTS5 shadow so the
retrieval layer (Phase 9) can do cheap BM25 lookups by name / description.

Scope (V1)
----------
- :func:`register` inserts an ``operations`` row. Used by Task 8.2 to
  catalog the 17 hardcoded ops at daemon startup, and (V2, Phase 15) by
  the generated-op pipeline. Emits an ``operation_created`` event.
- :func:`find` resolves an op by ``(name, version)``; ``version=None``
  returns the latest registered row for that name.
- :func:`list` enumerates ops, optionally filtered by ``kind`` and
  ``status``.
- :func:`record_execution` logs an execution into
  ``operation_executions``. Emits a ``transform_run`` event since
  ``operation_executed`` isn't in the V1 event-type enum (see
  ``events.EVENT_TYPES``).
- :func:`search` runs FTS5 BM25 scoped to a project (or global ops).

V2 stubs (``propose_operation``, ``validate_operation``) raise
``NotImplementedError`` pending Phase 15.

FTS5 wiring
-----------
``operations_fts`` is declared ``content=operations`` in ``schema.sql``
without triggers, so we mirror ``(rowid, name, description)`` manually on
every register call — same pattern as ``messages.py`` and ``tool_calls.py``.

Schema caveats
--------------
``operations.code_artifact_id`` is ``NOT NULL`` in the schema, but V1
callers (Task 8.2) don't yet bundle code as artifacts — they'll attach
artifact IDs once Phase 5 (``artifacts.py``) is integrated at the call
site. For now ``source_code`` / ``source_hash`` are stored as
``code_hash`` and ``code_artifact_id`` is set to ``""`` (empty sentinel)
when not supplied. TODO(Phase 8.2): require artifact_id once the startup
cataloger stores source blobs via :mod:`iris.projects.artifacts`.
"""

from __future__ import annotations

import builtins
import hashlib
import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from iris.projects import events

__all__ = [
    "KINDS",
    "STATUSES",
    "find",
    "list",
    "propose_operation",
    "record_execution",
    "register",
    "search",
    "validate_operation",
]

# ``kind`` is a V1 convenience label carried in the operation's description
# prefix / FTS text — the schema itself doesn't have a ``kind`` column, so
# we persist it as a JSON blob alongside the signature (see ``register``).
KINDS: frozenset[str] = frozenset({"hardcoded", "generated", "user"})

# Mirrors schema.sql ``operations.validation_status`` enum. ``pending``
# is the label the prompt asks for on generated ops; it maps to ``draft``
# in the schema's enum. We keep ``pending`` as the public token and store
# ``draft`` in the DB.
STATUSES: frozenset[str] = frozenset(
    {"active", "pending", "draft", "validated", "rejected", "deprecated"}
)


def _now_iso() -> str:
    """Return the current time as an ISO-8601 string with ``Z`` suffix."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


_OP_KEYS: tuple[str, ...] = (
    "op_id",
    "project_id",
    "name",
    "version",
    "description",
    "input_schema_json",
    "output_schema_json",
    "code_hash",
    "code_artifact_id",
    "test_artifact_id",
    "parent_op_id",
    "validation_status",
    "use_count",
    "success_rate",
    "created_at",
    "validated_at",
    "last_used_at",
)

_OP_COLUMNS = (
    "op_id, project_id, name, version, description, "
    "input_schema_json, output_schema_json, code_hash, code_artifact_id, "
    "test_artifact_id, parent_op_id, validation_status, use_count, "
    "success_rate, created_at, validated_at, last_used_at"
)


def _row_to_dict(row: tuple[Any, ...] | None) -> dict[str, Any] | None:
    """Convert an ``operations`` SELECT row (column order = ``_OP_KEYS``) to a dict."""
    if row is None:
        return None
    return dict(zip(_OP_KEYS, row, strict=False))


def register(
    conn: sqlite3.Connection,
    *,
    project_id: str | None,
    name: str,
    version: str,
    kind: str,
    signature_json: dict[str, Any],
    docstring: str,
    source_code: str | None = None,
    source_hash: str | None = None,
    code_artifact_id: str | None = None,
) -> str:
    """Register an operation in the catalog and return its ``op_id``.

    ``kind='hardcoded'`` rows land with ``validation_status='validated'``
    (the 17 stock ops ship pre-vetted); anything else lands as ``'draft'``
    (the schema enum for what the prompt calls "pending") and will be
    promoted by Phase 15's validation pipeline.

    Parameters
    ----------
    project_id
        ``None`` marks a globally-available op (shared across every
        project in this SQLite file).
    signature_json
        Structured input/output schema. Stored as ``input_schema_json``;
        if it carries a top-level ``"output"`` key, that goes into
        ``output_schema_json``. Everything else stays under
        ``input_schema_json`` verbatim.
    source_code
        Optional raw source. We don't persist the bytes here (that's
        Phase 5's job); we only hash them if ``source_hash`` wasn't
        supplied.

    Raises
    ------
    ValueError
        If ``kind`` isn't one of :data:`KINDS`.
    """
    if kind not in KINDS:
        raise ValueError(f"unknown kind {kind!r}; expected one of {sorted(KINDS)}")

    # Idempotency: if an op with the same (project_id, name, version) is
    # already registered, return its existing op_id instead of inserting a
    # duplicate row. The startup cataloger (Task 8.2) calls register() on
    # every boot, so duplicates on restart are expected and must be a no-op.
    existing = conn.execute(
        "SELECT op_id FROM operations WHERE project_id IS ? AND name = ? AND version = ? LIMIT 1",
        (project_id, name, version),
    ).fetchone()
    if existing is not None:
        return existing[0]

    validation_status = "validated" if kind == "hardcoded" else "draft"

    # Split the signature into input/output halves the schema expects.
    output_schema = signature_json.get("output") if isinstance(signature_json, dict) else None
    input_schema_json = json.dumps(signature_json, sort_keys=True, separators=(",", ":"))
    output_schema_json = (
        json.dumps(output_schema, sort_keys=True, separators=(",", ":"))
        if output_schema is not None
        else None
    )

    # Prefer caller-supplied hash; fall back to hashing source_code; else
    # empty string (schema requires NOT NULL).
    if source_hash is None and source_code is not None:
        source_hash = hashlib.sha256(source_code.encode("utf-8")).hexdigest()
    code_hash = source_hash or ""

    # TODO(Phase 8.2): bundle source_code via artifacts.store() and set
    # this to the resulting artifact_id. Callers that haven't wired Phase 5
    # yet can pass ``code_artifact_id=None`` — we fall back to an empty
    # sentinel, which only survives the FK check when foreign_keys are
    # temporarily disabled (the startup cataloger does this).
    if code_artifact_id is None:
        code_artifact_id = ""

    op_id = uuid.uuid4().hex
    created_at = _now_iso()

    conn.execute("BEGIN IMMEDIATE")
    try:
        cursor = conn.execute(
            f"INSERT INTO operations ({_OP_COLUMNS}) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                op_id,
                project_id,
                name,
                version,
                docstring,
                input_schema_json,
                output_schema_json,
                code_hash,
                code_artifact_id,
                None,  # test_artifact_id
                None,  # parent_op_id
                validation_status,
                0,  # use_count
                None,  # success_rate
                created_at,
                created_at if validation_status == "validated" else None,
                None,  # last_used_at
            ),
        )
        rowid = cursor.lastrowid
        # Mirror into FTS5 external-content table; rowid must match the
        # base-table rowid so ``content=operations`` can resolve hits.
        conn.execute(
            "INSERT INTO operations_fts(rowid, name, description) VALUES (?, ?, ?)",
            (rowid, name, docstring),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    # Emit the event outside the op's transaction — ``append_event`` opens
    # its own BEGIN IMMEDIATE and will deadlock if nested. Global ops
    # (project_id=None) don't produce events; the event log is per-project
    # and requires a non-null project_id FK.
    if project_id is not None:
        events.append_event(
            conn,
            project_id=project_id,
            type=events.EVT_OPERATION_CREATED,
            payload={
                "op_id": op_id,
                "name": name,
                "version": version,
                "kind": kind,
                "validation_status": validation_status,
            },
        )

    _enqueue_operation_embedding(conn, op_id, name, version, docstring)
    return op_id


def _enqueue_operation_embedding(
    conn: sqlite3.Connection,
    op_id: str,
    name: str,
    version: str,
    docstring: str,
) -> None:
    """Best-effort embedding enqueue (REVAMP Task 11.4). No-op if worker idle."""
    try:
        from pathlib import Path as _Path

        from iris.projects import embedding_worker as _ew

        db_row = conn.execute("PRAGMA database_list").fetchone()
        if not db_row or not db_row[2]:
            return
        project_path = _Path(db_row[2]).parent
        text = f"{name} v{version}\n{docstring or ''}".strip()
        if not text:
            return
        _ew.enqueue(
            _ew.EmbedJob(
                kind="operation",
                project_path=project_path,
                entity_id=op_id,
                text=text,
            )
        )
    except Exception:  # noqa: BLE001
        pass


def find(
    conn: sqlite3.Connection,
    *,
    project_id: str | None,
    name: str,
    version: str | None = None,
) -> dict[str, Any] | None:
    """Resolve an op by ``(name, version)``; latest version if ``version`` is ``None``.

    "Latest" is by ``created_at`` descending — semver-string sorting would
    mis-rank ``1.10.0`` vs ``1.2.0``, and we don't have a version-parsing
    dependency in V1.
    """
    if version is not None:
        row = conn.execute(
            f"SELECT {_OP_COLUMNS} FROM operations "
            "WHERE project_id IS ? AND name = ? AND version = ? "
            "LIMIT 1",
            (project_id, name, version),
        ).fetchone()
    else:
        row = conn.execute(
            f"SELECT {_OP_COLUMNS} FROM operations "
            "WHERE project_id IS ? AND name = ? "
            "ORDER BY created_at DESC LIMIT 1",
            (project_id, name),
        ).fetchone()
    return _row_to_dict(row)


def list(  # noqa: A001 — public API name prescribed by REVAMP task 8.1
    conn: sqlite3.Connection,
    *,
    project_id: str | None,
    kind: str | None = None,
    status: str = "active",
    limit: int = 100,
) -> builtins.list[dict[str, Any]]:
    """List registered ops for a project (or globals when ``project_id`` is None).

    ``kind`` is currently not persisted as a column (see module docstring);
    we accept it for API stability but it's a no-op filter in V1. TODO(V2):
    either denormalize ``kind`` onto the row or infer it from
    ``project_id IS NULL`` + ``validation_status``.

    ``status='active'`` is mapped to ``validated`` since the schema enum
    doesn't carry an ``active`` value.
    """
    del kind  # V1 no-op — see docstring.

    # Translate the public ``active`` token to the schema's ``validated``.
    db_status = "validated" if status == "active" else status

    rows = conn.execute(
        f"SELECT {_OP_COLUMNS} FROM operations "
        "WHERE project_id IS ? AND validation_status = ? "
        "ORDER BY created_at DESC LIMIT ?",
        (project_id, db_status, limit),
    ).fetchall()
    return [d for d in (_row_to_dict(r) for r in rows) if d is not None]


def record_execution(
    conn: sqlite3.Connection,
    *,
    operation_id: str,
    run_id: str | None,
    inputs_hash: str | None,
    success: bool,
    execution_time_ms: int | None,
) -> str:
    """Log one execution of ``operation_id`` and return the ``execution_id``.

    Also updates the parent ``operations`` row: bumps ``use_count``,
    refreshes ``last_used_at``, and recomputes ``success_rate`` as the
    running ratio of successful executions.

    TODO(Phase 8.2): thread ``output_hash`` + ``error_text`` through once
    the engine writes them; the schema columns are already there.
    """
    execution_id = uuid.uuid4().hex
    ts = _now_iso()

    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "INSERT INTO operation_executions ("
            "execution_id, op_id, run_id, input_hash, output_hash, "
            "success, error_text, execution_time_ms, ts"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                execution_id,
                operation_id,
                run_id,
                inputs_hash,
                None,  # output_hash — see TODO
                1 if success else 0,
                None,  # error_text
                execution_time_ms,
                ts,
            ),
        )

        # Recompute aggregates from the full history. Cheap in V1; if this
        # becomes hot, switch to incremental math on the cached row.
        agg = conn.execute(
            "SELECT COUNT(*) AS n, "
            "SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) AS ok "
            "FROM operation_executions WHERE op_id = ?",
            (operation_id,),
        ).fetchone()
        n = int(agg[0] or 0)
        ok = int(agg[1] or 0)
        success_rate = (ok / n) if n > 0 else None

        conn.execute(
            "UPDATE operations SET use_count = ?, success_rate = ?, last_used_at = ? "
            "WHERE op_id = ?",
            (n, success_rate, ts, operation_id),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    # Emit an event for the execution. ``operation_executed`` isn't in the
    # V1 event-type enum, so we piggy-back on ``transform_run`` which
    # semantically covers "an operation ran". TODO: add a dedicated
    # ``operation_executed`` event type when the enum is next revised.
    op_row = conn.execute(
        "SELECT project_id FROM operations WHERE op_id = ?",
        (operation_id,),
    ).fetchone()
    if op_row is not None and op_row[0] is not None:
        events.append_event(
            conn,
            project_id=op_row[0],
            type=events.EVT_TRANSFORM_RUN,
            payload={
                "kind": "operation_executed",
                "op_id": operation_id,
                "run_id": run_id,
                "success": bool(success),
                "execution_time_ms": execution_time_ms,
            },
        )

    return execution_id


def search(
    conn: sqlite3.Connection,
    *,
    project_id: str | None,
    query: str,
    limit: int = 20,
) -> builtins.list[dict[str, Any]]:
    """FTS5 BM25 search over ``operations_fts`` scoped to ``project_id``.

    Returns hits ordered by ascending BM25 (lower = better match — FTS5
    scores are negative log-probabilities). Each hit carries the full op
    row plus a ``score`` field.

    ``project_id=None`` matches globally-registered ops. Pass a concrete
    project id to scope to that project only.
    """
    # Qualify every column with the ``o.`` alias — ``operations_fts``
    # shadows ``name`` and ``description``, which otherwise make the
    # SELECT ambiguous.
    qualified_cols = ", ".join(f"o.{c}" for c in _OP_KEYS)
    rows = conn.execute(
        f"SELECT {qualified_cols}, bm25(operations_fts) AS score "
        "FROM operations_fts "
        "JOIN operations o ON o.rowid = operations_fts.rowid "
        "WHERE operations_fts MATCH ? AND o.project_id IS ? "
        "ORDER BY score ASC "
        "LIMIT ?",
        (query, project_id, limit),
    ).fetchall()

    results: builtins.list[dict[str, Any]] = []
    for row in rows:
        # The JOIN projects _OP_COLUMNS first, then the score tail.
        op_cols = tuple(row[:-1])
        score = row[-1]
        d = _row_to_dict(op_cols)
        if d is not None:
            d["score"] = score
            results.append(d)
    return results


# -- V2 stubs ---------------------------------------------------------------


def propose_operation(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    project_path: Path,
    name: str,
    version: str,
    description: str,
    code: str,
    signature_json: dict[str, Any] | None = None,
    test_code: str | None = None,
    readme: str | None = None,
) -> str:
    """Propose a generated op (Phase 15, REVAMP Task 15.2).

    Writes the op source + optional tests + README into
    ``<project_path>/ops/<name>/v<version>/`` and registers the op via
    :func:`register` with ``kind='generated'`` (lands as ``status='draft'``).
    A subsequent :func:`iris.projects.op_validation.validate_operation`
    call promotes it to ``validated`` or ``rejected``.
    """
    op_dir = project_path / "ops" / name / f"v{version}"
    op_dir.mkdir(parents=True, exist_ok=True)
    (op_dir / "op.py").write_text(code, encoding="utf-8")
    (op_dir / "schema.json").write_text(
        json.dumps(signature_json or {}, indent=2, sort_keys=True), encoding="utf-8"
    )
    if test_code is not None:
        tests_dir = op_dir / "tests"
        tests_dir.mkdir(exist_ok=True)
        (tests_dir / "test_op.py").write_text(test_code, encoding="utf-8")
    if readme is not None:
        (op_dir / "README.md").write_text(readme, encoding="utf-8")

    return register(
        conn,
        project_id=project_id,
        name=name,
        version=version,
        kind="generated",
        signature_json=signature_json or {},
        docstring=description,
        source_code=code,
    )


def validate_operation(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Validate a pending op. V2 — Phase 15."""
    # TODO(Phase 15): see ``op_validation.py`` design in REVAMP Task 15.1.
    raise NotImplementedError("Phase 15")
