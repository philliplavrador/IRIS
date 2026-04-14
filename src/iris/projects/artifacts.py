"""Content-addressed artifact store (spec §5.1 Store 2, §7.1).

Every "heavy" output — plot PNG/SVG, report HTML/PDF, slide deck, code
file, cache object, data export, notebook — lives on disk at
``<project_path>/artifacts/<sha256>/blob`` with its metadata mirrored in
the ``artifacts`` SQLite table. The SHA-256 of the content is both the
storage directory name and the row's ``content_hash``; the ``artifact_id``
is derived from the same hash so identical bytes dedup to a single row.

Design
------
- **Content-addressed dedup**: :func:`store` computes SHA-256 over the
  bytes. If a row with that ``content_hash`` already exists for the same
  project we return the existing ``artifact_id`` without rewriting the
  blob. Same bytes uploaded twice = one file, one row.
- **Deleted tombstones**: :func:`soft_delete` flips a ``deleted_at``
  column that the schema does not carry by default. We add it lazily via
  ``ALTER TABLE`` on first call — the PRAGMA probe is cheap and makes this
  module safe against older DBs that were created before Phase 5.
- **Event trail**: every successful new-row insert writes an
  ``artifact_created`` event via :mod:`iris.projects.events` so the hash
  chain covers artifact lineage.

Public API
----------
- :func:`store`
- :func:`get_bytes`
- :func:`get_metadata`
- :func:`list_artifacts` (exposed as ``list`` in ``__all__``; the builtin
  shadow is unavoidable at the module boundary so we provide the alias).
- :func:`soft_delete`
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from iris.projects import events as events_mod

__all__ = [
    "ARTIFACT_TYPES",
    "get_bytes",
    "get_metadata",
    "list_artifacts",
    "soft_delete",
    "store",
]

# Matches the comment on ``artifacts.type`` in schema.sql. Enforced at
# the Python boundary (ValueError) rather than via CHECK so V2 can extend.
ARTIFACT_TYPES: Final[frozenset[str]] = frozenset(
    {
        "plot_png",
        "plot_svg",
        "report_html",
        "report_pdf",
        "slide_deck",
        "code_file",
        "cache_object",
        "data_export",
        "notebook",
    }
)

_SELECT_COLUMNS: Final[str] = (
    "artifact_id, project_id, type, created_at, content_hash, "
    "storage_path, metadata_json, description"
)


def _now_iso() -> str:
    """Return the current time as an ISO-8601 string with ``Z`` suffix."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _ensure_deleted_at_column(conn: sqlite3.Connection) -> None:
    """Add ``deleted_at`` to ``artifacts`` if it isn't there yet.

    Idempotent. The schema.sql shipped at Phase 1 predates this column;
    rather than bump the schema version we lazily migrate the one table
    that needs it. PRAGMA ``table_info`` is cheap and avoids a try/except
    on ``ALTER TABLE`` that would also need to discriminate error codes.
    """
    cols = {row[1] for row in conn.execute("PRAGMA table_info(artifacts)").fetchall()}
    if "deleted_at" not in cols:
        conn.execute("ALTER TABLE artifacts ADD COLUMN deleted_at TEXT")


def _row_to_dict(row: sqlite3.Row | tuple[Any, ...]) -> dict[str, Any]:
    """Decode an ``artifacts`` row into a JSON-ready dict."""
    (
        artifact_id,
        project_id,
        type_,
        created_at,
        content_hash,
        storage_path,
        metadata_json,
        description,
    ) = row
    return {
        "artifact_id": artifact_id,
        "project_id": project_id,
        "type": type_,
        "created_at": created_at,
        "content_hash": content_hash,
        "storage_path": storage_path,
        "metadata": json.loads(metadata_json) if metadata_json else None,
        "description": description,
    }


def _resolve_project_id(conn: sqlite3.Connection, project_path: Path) -> str:
    """Return the ``project_id`` for this DB.

    IRIS keeps one SQLite file per project (``<project_path>/iris.sqlite``),
    so the ``projects`` table has exactly one row. ``project_path`` is
    accepted for symmetry with the rest of the memory API (and to make
    any future multi-project DB explicit) but today it's informational:
    the id comes from the sole row. Raises ``ValueError`` if the table
    is empty — the project lifecycle is expected to have registered the
    project before anyone calls into the artifacts store.
    """
    _ = Path(project_path)  # touched purely to assert it's a valid path value
    row = conn.execute("SELECT project_id FROM projects LIMIT 1").fetchone()
    if row is None:
        raise ValueError(
            "projects table is empty; create_project must register a project "
            "row before storing artifacts"
        )
    return row[0]


# -- public API -------------------------------------------------------------


def store(
    conn: sqlite3.Connection,
    project_path: Path | str,
    *,
    content: bytes,
    type: str,
    metadata: dict[str, Any] | None = None,
    description: str | None = None,
) -> str:
    """Content-address ``content`` and register it as an artifact.

    Path on disk is ``<project_path>/artifacts/<sha256>/blob``. The
    ``artifact_id`` is the same SHA-256 so dedup is a direct PK lookup.

    If the row already exists (same bytes previously stored for this
    project) we short-circuit: no rewrite, no new event. The on-disk
    blob is rewritten only if it's missing, which makes the store
    self-healing against a clobbered workspace.

    Raises
    ------
    ValueError
        If ``type`` is not one of :data:`ARTIFACT_TYPES` or the project
        is not registered.
    """
    if type not in ARTIFACT_TYPES:
        raise ValueError(
            f"unknown artifact type {type!r}; expected one of {sorted(ARTIFACT_TYPES)}"
        )

    project_root = Path(project_path).resolve()
    project_id = _resolve_project_id(conn, project_root)

    sha = hashlib.sha256(content).hexdigest()
    artifact_id = sha
    rel_dir = Path("artifacts") / sha
    rel_path = rel_dir / "blob"
    abs_dir = project_root / rel_dir
    abs_path = project_root / rel_path

    # Dedup check first — cheapest path.
    existing = conn.execute(
        "SELECT artifact_id FROM artifacts WHERE artifact_id = ? AND project_id = ?",
        (artifact_id, project_id),
    ).fetchone()

    if existing is not None:
        # Self-heal: if the row is there but the blob has been deleted out
        # from under us, rewrite it. Callers rely on get_bytes succeeding
        # for any live row.
        if not abs_path.exists():
            abs_dir.mkdir(parents=True, exist_ok=True)
            abs_path.write_bytes(content)
        return artifact_id

    abs_dir.mkdir(parents=True, exist_ok=True)
    if not abs_path.exists():
        abs_path.write_bytes(content)

    ts = _now_iso()
    metadata_json = json.dumps(metadata) if metadata is not None else None
    storage_path = rel_path.as_posix()

    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "INSERT INTO artifacts ("
            "artifact_id, project_id, type, created_at, content_hash, "
            "storage_path, metadata_json, description"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                artifact_id,
                project_id,
                type,
                ts,
                sha,
                storage_path,
                metadata_json,
                description,
            ),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    events_mod.append_event(
        conn,
        project_id=project_id,
        type=events_mod.EVT_ARTIFACT_CREATED,
        payload={
            "artifact_id": artifact_id,
            "artifact_type": type,
            "content_hash": sha,
            "storage_path": storage_path,
        },
    )
    return artifact_id


def get_bytes(
    conn: sqlite3.Connection,
    project_path: Path | str,
    artifact_id: str,
) -> bytes:
    """Return the raw bytes for ``artifact_id``.

    Reads the ``storage_path`` from SQLite and resolves it under
    ``project_path``. Raises ``FileNotFoundError`` if the blob is gone
    and ``ValueError`` if the row does not exist.
    """
    row = conn.execute(
        "SELECT storage_path FROM artifacts WHERE artifact_id = ?",
        (artifact_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"artifact {artifact_id!r} does not exist")
    abs_path = Path(project_path).resolve() / row[0]
    return abs_path.read_bytes()


def get_metadata(conn: sqlite3.Connection, artifact_id: str) -> dict[str, Any]:
    """Return the full ``artifacts`` row for ``artifact_id`` as a dict.

    The ``metadata`` field is JSON-decoded. Raises ``ValueError`` if the
    id is unknown.
    """
    row = conn.execute(
        f"SELECT {_SELECT_COLUMNS} FROM artifacts WHERE artifact_id = ?",
        (artifact_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"artifact {artifact_id!r} does not exist")
    return _row_to_dict(row)


def list_artifacts(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    type: str | None = None,
    run_id: str | None = None,
) -> list[dict[str, Any]]:
    """List artifacts for a project, optionally filtered by type / run.

    ``run_id`` filters by ``runs.output_artifact_ids_json`` containing the
    artifact id; we do a TEXT LIKE match since the column is a JSON
    array. Good enough for Phase 5 — Phase 7 can swap in a proper join.
    """
    clauses = ["a.project_id = ?"]
    params: list[Any] = [project_id]
    if type is not None:
        clauses.append("a.type = ?")
        params.append(type)

    # Filter out soft-deleted rows. We probe the column presence so we
    # don't blow up on pre-Phase-5 DBs that haven't had ``soft_delete``
    # called yet.
    cols = {row[1] for row in conn.execute("PRAGMA table_info(artifacts)").fetchall()}
    if "deleted_at" in cols:
        clauses.append("a.deleted_at IS NULL")

    if run_id is not None:
        # Per-row membership: the artifact_id must appear as a quoted token
        # in the run's output_artifact_ids_json array. Good enough for
        # Phase 5 — Phase 7 can swap in a proper join table.
        clauses.append(
            "EXISTS (SELECT 1 FROM runs r WHERE r.run_id = ? "
            "AND r.output_artifact_ids LIKE '%\"' || a.artifact_id || '\"%')"
        )
        params.append(run_id)

    sql = (
        f"SELECT {_SELECT_COLUMNS} FROM artifacts a "
        f"WHERE {' AND '.join(clauses)} "
        "ORDER BY a.created_at DESC"
    )
    rows = conn.execute(sql, params).fetchall()
    return [_row_to_dict(r) for r in rows]


# The REVAMP task names this symbol ``list`` in the public-API block;
# we export it as :func:`list_artifacts` to avoid shadowing the builtin
# module-wide (which would break ``list[dict[...]]`` type hints on the
# function itself). Callers that want the spec name can do
# ``from iris.projects.artifacts import list_artifacts as list``.


def soft_delete(conn: sqlite3.Connection, artifact_id: str) -> None:
    """Mark ``artifact_id`` as deleted without touching the blob.

    Sets ``deleted_at`` on the row (lazy-adding the column if this is
    the first soft-delete call against this DB). The on-disk blob is
    preserved for the retention window — callers that want to reclaim
    space should run a separate sweep that respects retention policy.

    No-op if the row is already soft-deleted. Raises ``ValueError`` if
    the id is unknown.
    """
    _ensure_deleted_at_column(conn)
    row = conn.execute(
        "SELECT deleted_at FROM artifacts WHERE artifact_id = ?",
        (artifact_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"artifact {artifact_id!r} does not exist")
    if row[0] is not None:
        return
    ts = _now_iso()
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "UPDATE artifacts SET deleted_at = ? WHERE artifact_id = ?",
            (ts, artifact_id),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
