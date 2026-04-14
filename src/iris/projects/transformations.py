"""Derived dataset versions — chaining and lineage (spec §7.1, Phase 6.2).

Phase 6.1 (``datasets.py``) captures raw dataset versions — files hashed
into ``datasets/raw/`` with ``derived_from_dataset_version_id = NULL``.
This module handles the other half: *derived* versions, i.e. the rows
produced when a transform run (filter, resample, trim, ...) takes an
existing dataset version as input and writes a new one.

A derived version is distinguished by ``derived_from_dataset_version_id``
being set. Chained back through that column, every derived version
reaches exactly one raw ancestor — the lineage. :func:`lineage` walks
that chain with a recursive CTE.

Design notes
------------
- The transform output is materialised as an **artifact** (see
  ``artifacts.py``) before landing a derived-version row. We reuse the
  artifact's ``content_hash`` and ``storage_path`` so a derived dataset
  version is just a pointer into the content-addressed store — no
  second copy on disk.
- ``transform_params`` is stashed in the ``description`` column as a
  canonical-JSON prefix ``"<transform_name>: <json>\n<description>"``.
  The current schema has no dedicated params column; when Phase 7 adds
  ``runs.params_json``, the canonical home for this is the linked run
  row. For now we keep params inline so lineage is self-describing
  without a join.
- We emit a ``transform_run`` event (the closest existing event type in
  :data:`EVENT_TYPES`). Phase 7 replaces the ad-hoc event with a real
  run row + linked event; the payload shape here is deliberately a
  superset of what that migration will need.

Public API
----------
- :func:`record_derived_version`
- :func:`list_versions`
- :func:`lineage`
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from typing import Any

from iris.projects import events as events_mod

__all__ = [
    "lineage",
    "list_versions",
    "record_derived_version",
]


def _now_iso() -> str:
    """Return the current time as an ISO-8601 string with ``Z`` suffix."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _resolve_project_id(conn: sqlite3.Connection, dataset_id: str) -> str:
    """Return the ``project_id`` that owns ``dataset_id``."""
    row = conn.execute(
        "SELECT project_id FROM datasets WHERE dataset_id = ?",
        (dataset_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"dataset {dataset_id!r} does not exist")
    return row[0]


def _resolve_artifact(conn: sqlite3.Connection, artifact_id: str) -> tuple[str, str]:
    """Return ``(content_hash, storage_path)`` for ``artifact_id``.

    Raises
    ------
    ValueError
        If no artifact row matches.
    """
    row = conn.execute(
        "SELECT content_hash, storage_path FROM artifacts WHERE artifact_id = ?",
        (artifact_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"artifact {artifact_id!r} does not exist")
    return row[0], row[1]


def _encode_description(
    transform_name: str,
    transform_params: dict[str, Any],
    description: str | None,
) -> str:
    """Pack ``(transform_name, transform_params, description)`` into one string.

    The prefix is a canonical-JSON header so downstream code (or a human
    reading the Markdown export) can round-trip the params.
    """
    header = json.dumps(
        {"transform": transform_name, "params": transform_params},
        sort_keys=True,
        separators=(",", ":"),
    )
    if description:
        return f"{header}\n{description}"
    return header


# -- public API -------------------------------------------------------------


def record_derived_version(
    conn: sqlite3.Connection,
    *,
    dataset_id: str,
    parent_version_id: str,
    transform_name: str,
    transform_params: dict[str, Any],
    artifact_id: str,
    description: str | None = None,
) -> str:
    """Insert a derived ``dataset_versions`` row and return its id.

    Preconditions
    -------------
    - ``parent_version_id`` must exist and must belong to ``dataset_id``.
    - ``artifact_id`` must reference an existing artifact row; its
      ``content_hash`` and ``storage_path`` are copied onto the new
      version so the derived dataset is pointer-equal to the artifact's
      on-disk bytes.

    The write runs inside a ``BEGIN IMMEDIATE`` transaction. On success a
    ``transform_run`` event is appended with the lineage payload.
    """
    parent = conn.execute(
        "SELECT dataset_id FROM dataset_versions WHERE dataset_version_id = ?",
        (parent_version_id,),
    ).fetchone()
    if parent is None:
        raise ValueError(f"parent version {parent_version_id!r} does not exist")
    if parent[0] != dataset_id:
        raise ValueError(
            f"parent version {parent_version_id!r} belongs to dataset "
            f"{parent[0]!r}, not {dataset_id!r}"
        )

    content_hash, storage_path = _resolve_artifact(conn, artifact_id)
    project_id = _resolve_project_id(conn, dataset_id)

    dataset_version_id = uuid.uuid4().hex
    ts = _now_iso()
    packed_description = _encode_description(transform_name, transform_params, description)

    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "INSERT INTO dataset_versions ("
            "dataset_version_id, dataset_id, created_at, content_hash, "
            "storage_path, derived_from_dataset_version_id, transform_run_id, "
            "schema_json, row_count, description"
            ") VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, NULL, ?)",
            (
                dataset_version_id,
                dataset_id,
                ts,
                content_hash,
                storage_path,
                parent_version_id,
                packed_description,
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
        payload={
            "dataset_id": dataset_id,
            "dataset_version_id": dataset_version_id,
            "parent_version_id": parent_version_id,
            "transform_name": transform_name,
            "transform_params": transform_params,
            "artifact_id": artifact_id,
            "content_hash": content_hash,
            "storage_path": storage_path,
            "version_type": "derived",
        },
    )

    return dataset_version_id


def list_versions(conn: sqlite3.Connection, *, dataset_id: str) -> list[dict[str, Any]]:
    """Return every version of ``dataset_id`` ordered by ``created_at`` asc.

    Chronological order means raw first, then derived versions in the
    order they were recorded — the natural read order for an audit trail.
    """
    rows = conn.execute(
        "SELECT dataset_version_id, dataset_id, created_at, content_hash, "
        "storage_path, derived_from_dataset_version_id, transform_run_id, "
        "schema_json, row_count, description "
        "FROM dataset_versions WHERE dataset_id = ? "
        "ORDER BY created_at ASC, rowid ASC",
        (dataset_id,),
    ).fetchall()
    return [
        {
            "dataset_version_id": r[0],
            "dataset_id": r[1],
            "created_at": r[2],
            "content_hash": r[3],
            "storage_path": r[4],
            "derived_from_dataset_version_id": r[5],
            "transform_run_id": r[6],
            "schema_json": r[7],
            "row_count": r[8],
            "description": r[9],
        }
        for r in rows
    ]


def lineage(conn: sqlite3.Connection, version_id: str) -> list[dict[str, Any]]:
    """Walk parent links back to the raw ancestor.

    Uses a recursive CTE so the whole chain comes back in one query. The
    returned list is ordered **leaf-to-root**: index 0 is ``version_id``
    itself, the last element is the raw version (``derived_from_... IS
    NULL``). Returns an empty list if ``version_id`` does not exist.
    """
    rows = conn.execute(
        """
        WITH RECURSIVE chain(
            dataset_version_id, dataset_id, created_at, content_hash,
            storage_path, derived_from_dataset_version_id, transform_run_id,
            schema_json, row_count, description, depth
        ) AS (
            SELECT
                dataset_version_id, dataset_id, created_at, content_hash,
                storage_path, derived_from_dataset_version_id, transform_run_id,
                schema_json, row_count, description, 0
            FROM dataset_versions
            WHERE dataset_version_id = ?
            UNION ALL
            SELECT
                p.dataset_version_id, p.dataset_id, p.created_at, p.content_hash,
                p.storage_path, p.derived_from_dataset_version_id, p.transform_run_id,
                p.schema_json, p.row_count, p.description, c.depth + 1
            FROM dataset_versions p
            JOIN chain c ON p.dataset_version_id = c.derived_from_dataset_version_id
        )
        SELECT
            dataset_version_id, dataset_id, created_at, content_hash,
            storage_path, derived_from_dataset_version_id, transform_run_id,
            schema_json, row_count, description
        FROM chain
        ORDER BY depth ASC
        """,
        (version_id,),
    ).fetchall()
    return [
        {
            "dataset_version_id": r[0],
            "dataset_id": r[1],
            "created_at": r[2],
            "content_hash": r[3],
            "storage_path": r[4],
            "derived_from_dataset_version_id": r[5],
            "transform_run_id": r[6],
            "schema_json": r[7],
            "row_count": r[8],
            "description": r[9],
        }
        for r in rows
    ]
