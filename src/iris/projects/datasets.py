"""Dataset import + raw-version capture (spec §7.1).

Phase 6.1 lands the ingestion half of the dataset pipeline: a user-supplied
file is hashed (SHA-256), copied into the project's content-addressed
``datasets/raw/`` tree, and two DB rows are written — one in ``datasets``
(the logical handle) and one in ``dataset_versions`` (the immutable raw
version). A ``dataset_import`` event is appended so the log records
lineage.

Derived versions (Phase 6.2) and profiling (Phase 6.3) layer on top of
these rows. Column-level annotation proposals are NOT written here.

Public API
----------
- :func:`import_dataset`
- :func:`list_datasets`
- :func:`get_dataset`
- :func:`get_version`
"""

from __future__ import annotations

import hashlib
import shutil
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from iris.projects import events as events_mod

__all__ = [
    "get_dataset",
    "get_version",
    "import_dataset",
    "list_datasets",
]

RAW_SUBDIR: Final[str] = "datasets/raw"
_HASH_CHUNK: Final[int] = 1024 * 1024  # 1 MiB


def _now_iso() -> str:
    """Return the current time as an ISO-8601 string with ``Z`` suffix."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _sha256_file(path: Path) -> str:
    """Stream-hash ``path`` with SHA-256. Avoids loading big files into RAM."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(_HASH_CHUNK)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _resolve_project_id(conn: sqlite3.Connection) -> str:
    """Return the project_id for the single project row in this DB.

    Each ``iris.sqlite`` file scopes exactly one project; the ``projects``
    table pattern is per-DB (spec §6 filesystem layout). If more than one
    row ever lands here we take the first deterministically — a future
    multi-project-per-DB layout would grow an explicit argument.
    """
    row = conn.execute("SELECT project_id FROM projects ORDER BY created_at ASC LIMIT 1").fetchone()
    if row is None:
        raise RuntimeError("no project row found; init_schema + project bootstrap must run first")
    return row[0]


# -- public API -------------------------------------------------------------


def import_dataset(
    conn: sqlite3.Connection,
    project_path: Path,
    *,
    source_path: Path,
    name: str,
    description: str | None = None,
) -> tuple[str, str]:
    """Copy ``source_path`` into the project and record a raw dataset version.

    Steps:
      1. SHA-256 the source file.
      2. Copy it to ``<project>/datasets/raw/<sha>/<filename>`` (idempotent
         on the content-address — duplicate imports reuse the file).
      3. Insert a ``datasets`` row (one logical dataset per import call).
      4. Insert a ``dataset_versions`` row with ``derived_from_... = NULL``
         and ``transform_run_id = NULL`` to mark it as the raw capture.
      5. Emit a ``dataset_import`` event.

    Returns ``(dataset_id, dataset_version_id)``.

    Raises
    ------
    FileNotFoundError
        If ``source_path`` does not exist.
    """
    source_path = Path(source_path)
    project_path = Path(project_path)
    if not source_path.is_file():
        raise FileNotFoundError(f"dataset source not found: {source_path}")

    content_hash = _sha256_file(source_path)
    filename = source_path.name
    dest_dir = project_path / RAW_SUBDIR / content_hash
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / filename
    if not dest_path.exists():
        shutil.copy2(source_path, dest_path)

    storage_path = f"{RAW_SUBDIR}/{content_hash}/{filename}"

    project_id = _resolve_project_id(conn)
    dataset_id = uuid.uuid4().hex
    dataset_version_id = uuid.uuid4().hex
    ts = _now_iso()

    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "INSERT INTO datasets ("
            "dataset_id, project_id, name, original_filename, created_at"
            ") VALUES (?, ?, ?, ?, ?)",
            (dataset_id, project_id, name, filename, ts),
        )
        conn.execute(
            "INSERT INTO dataset_versions ("
            "dataset_version_id, dataset_id, created_at, content_hash, "
            "storage_path, derived_from_dataset_version_id, transform_run_id, "
            "schema_json, row_count, description"
            ") VALUES (?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, ?)",
            (
                dataset_version_id,
                dataset_id,
                ts,
                content_hash,
                storage_path,
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
        type=events_mod.EVT_DATASET_IMPORT,
        payload={
            "dataset_id": dataset_id,
            "dataset_version_id": dataset_version_id,
            "name": name,
            "original_filename": filename,
            "content_hash": content_hash,
            "storage_path": storage_path,
            "version_type": "raw",
        },
    )

    return dataset_id, dataset_version_id


def list_datasets(conn: sqlite3.Connection, *, project_id: str) -> list[dict[str, Any]]:
    """Return every dataset row for ``project_id``, newest first."""
    rows = conn.execute(
        "SELECT dataset_id, project_id, name, original_filename, created_at "
        "FROM datasets WHERE project_id = ? ORDER BY created_at DESC",
        (project_id,),
    ).fetchall()
    return [
        {
            "dataset_id": r[0],
            "project_id": r[1],
            "name": r[2],
            "original_filename": r[3],
            "created_at": r[4],
        }
        for r in rows
    ]


def get_dataset(conn: sqlite3.Connection, dataset_id: str) -> dict[str, Any] | None:
    """Return a single ``datasets`` row as a dict, or ``None`` if missing."""
    row = conn.execute(
        "SELECT dataset_id, project_id, name, original_filename, created_at "
        "FROM datasets WHERE dataset_id = ?",
        (dataset_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "dataset_id": row[0],
        "project_id": row[1],
        "name": row[2],
        "original_filename": row[3],
        "created_at": row[4],
    }


def get_version(conn: sqlite3.Connection, version_id: str) -> dict[str, Any] | None:
    """Return a single ``dataset_versions`` row as a dict, or ``None``."""
    row = conn.execute(
        "SELECT dataset_version_id, dataset_id, created_at, content_hash, "
        "storage_path, derived_from_dataset_version_id, transform_run_id, "
        "schema_json, row_count, description "
        "FROM dataset_versions WHERE dataset_version_id = ?",
        (version_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "dataset_version_id": row[0],
        "dataset_id": row[1],
        "created_at": row[2],
        "content_hash": row[3],
        "storage_path": row[4],
        "derived_from_dataset_version_id": row[5],
        "transform_run_id": row[6],
        "schema_json": row[7],
        "row_count": row[8],
        "description": row[9],
    }
