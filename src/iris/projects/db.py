"""SQLite connection + schema-migration helpers for IRIS project memory.

This is the single source of truth for SQLite access across the
``iris.projects`` package. Every other memory module (events, sessions,
messages, tool_calls, memory_entries, artifacts, datasets, runs,
operations, retrieval, ...) imports ``connect`` and ``init_schema`` from
here — nobody else opens the database directly.

Design notes
------------
- One SQLite file per project, at ``<project_path>/iris.sqlite``.
- ``PRAGMA journal_mode=WAL`` — concurrent readers + single writer, the
  daemon is single-process so no pooling is needed.
- ``PRAGMA foreign_keys=ON`` — every schema cross-reference is enforced.
- ``PRAGMA synchronous=NORMAL`` — durable on WAL checkpoints, much faster
  than the default FULL for the write patterns we have (lots of small
  event/message inserts).
- Schema migration is tracked via ``PRAGMA user_version``. V1 ships
  ``schema.sql`` with ``user_version = 1`` at the bottom. ``migrate`` is
  a placeholder for future bumps; currently a no-op when
  ``target_version == current_version``.

See ``IRIS Memory Restructure.md`` §5.1 (Store 1) and §7 for rationale.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Final

__all__ = [
    "DB_FILENAME",
    "SCHEMA_VERSION",
    "connect",
    "init_schema",
    "current_version",
    "migrate",
]

DB_FILENAME: Final[str] = "iris.sqlite"
SCHEMA_VERSION: Final[int] = 1

_SCHEMA_SQL_PATH: Final[Path] = Path(__file__).with_name("schema.sql")


def _db_path(project_path: Path) -> Path:
    """Return the ``iris.sqlite`` path for ``project_path``."""
    return Path(project_path) / DB_FILENAME


def connect(project_path: Path) -> sqlite3.Connection:
    """Open (or create) the project's ``iris.sqlite`` and apply standard PRAGMAs.

    This does **not** run the schema. Callers that need the schema applied
    should invoke :func:`init_schema` after connecting. ``init_schema`` is
    idempotent, so it's safe to call on every connect.
    """
    path = _db_path(project_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def current_version(conn: sqlite3.Connection) -> int:
    """Return ``PRAGMA user_version`` for the connection."""
    row = conn.execute("PRAGMA user_version").fetchone()
    if row is None:
        return 0
    # sqlite3.Row supports integer indexing
    return int(row[0])


def init_schema(conn: sqlite3.Connection) -> None:
    """Apply ``schema.sql`` iff ``user_version == 0``; otherwise no-op.

    Idempotent by design — Phase 1's project lifecycle calls this on every
    connect so fresh TEMPLATE copies pick up the schema, while already-
    initialised projects skip straight through.
    """
    version = current_version(conn)
    if version != 0:
        return
    sql = _SCHEMA_SQL_PATH.read_text(encoding="utf-8")
    conn.executescript(sql)
    # schema.sql ends with `PRAGMA user_version = 1;` so this should already
    # be set; re-assert defensively in case a future edit drops that line.
    if current_version(conn) == 0:
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def migrate(conn: sqlite3.Connection, target_version: int) -> None:
    """Migrate the schema to ``target_version``. V1 no-op unless target == current.

    Reserved for future schema bumps (V2 adds sqlite-vec virtual tables,
    V3 adds a ``retrieval_events`` table). Today: raises
    ``NotImplementedError`` if the caller asks for a version we don't
    know how to reach.
    """
    version = current_version(conn)
    if target_version == version:
        return
    raise NotImplementedError(
        f"migrate({version} -> {target_version}) not implemented; "
        f"V1 schema is version {SCHEMA_VERSION}"
    )
