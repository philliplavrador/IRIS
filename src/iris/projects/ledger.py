"""L1 event ledger — SQLite-backed structured facts about what happened.

Tables: ``ops_runs``, ``plots_generated``, ``references_added``,
``cache_entries``. Writes are automatic (no user gate) — this layer records
what happened, not interpretation. See docs/iris-behavior.md §3.2.

The ledger file lives at ``<project>/ledger.sqlite`` and is initialized
lazily by :func:`open_ledger` (or eagerly by :func:`init_ledger` when a
project is created).
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional

LEDGER_FILENAME = "ledger.sqlite"
SCHEMA_VERSION = 1

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS ops_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    op_name TEXT NOT NULL,
    input_content_hashes TEXT NOT NULL,   -- JSON array
    params_hash TEXT NOT NULL,
    output_path TEXT,
    bytes INTEGER,
    runtime_ms INTEGER,
    session_id TEXT NOT NULL,
    timestamp TEXT NOT NULL               -- ISO-8601 UTC
);
CREATE INDEX IF NOT EXISTS idx_ops_runs_session ON ops_runs(session_id);
CREATE INDEX IF NOT EXISTS idx_ops_runs_op ON ops_runs(op_name);
CREATE INDEX IF NOT EXISTS idx_ops_runs_ts ON ops_runs(timestamp);

CREATE TABLE IF NOT EXISTS plots_generated (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    op_name TEXT NOT NULL,
    input_content_hashes TEXT NOT NULL,
    params_hash TEXT NOT NULL,
    plot_path TEXT NOT NULL,
    sidecar_path TEXT,
    bytes INTEGER,
    session_id TEXT NOT NULL,
    timestamp TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_plots_session ON plots_generated(session_id);
CREATE INDEX IF NOT EXISTS idx_plots_ts ON plots_generated(timestamp);

CREATE TABLE IF NOT EXISTS references_added (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reference_path TEXT NOT NULL,
    source TEXT NOT NULL,                 -- web | user | claude
    title TEXT,
    session_id TEXT NOT NULL,
    timestamp TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_refs_session ON references_added(session_id);

CREATE TABLE IF NOT EXISTS cache_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    op_name TEXT NOT NULL,
    input_content_hashes TEXT NOT NULL,
    params_hash TEXT NOT NULL,
    output_path TEXT NOT NULL,
    bytes INTEGER,
    created_at TEXT NOT NULL,
    last_hit_at TEXT,
    hit_count INTEGER NOT NULL DEFAULT 0,
    UNIQUE(op_name, input_content_hashes, params_hash)
);
CREATE INDEX IF NOT EXISTS idx_cache_lookup
    ON cache_entries(op_name, params_hash);
"""


# -- init / connection ------------------------------------------------------


def ledger_path(project_path: Path) -> Path:
    return Path(project_path) / LEDGER_FILENAME


def init_ledger(project_path: Path) -> Path:
    """Create ``ledger.sqlite`` with the current schema. Idempotent."""
    path = ledger_path(project_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA_SQL)
        conn.execute(
            "INSERT OR IGNORE INTO schema_version(version) VALUES (?)",
            (SCHEMA_VERSION,),
        )
        conn.commit()
    return path


@contextmanager
def open_ledger(project_path: Path) -> Iterator[sqlite3.Connection]:
    """Open (creating if needed) the ledger DB as a context-managed connection."""
    path = ledger_path(project_path)
    if not path.is_file():
        init_ledger(project_path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# -- writers ----------------------------------------------------------------


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _jdump(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def record_op_run(
    project_path: Path,
    *,
    op_name: str,
    input_content_hashes: Iterable[str],
    params_hash: str,
    session_id: str,
    output_path: Optional[str] = None,
    bytes_: Optional[int] = None,
    runtime_ms: Optional[int] = None,
    timestamp: Optional[str] = None,
) -> int:
    """Insert a row into ``ops_runs``. Returns the new row id."""
    with open_ledger(project_path) as conn:
        cur = conn.execute(
            """INSERT INTO ops_runs(op_name, input_content_hashes, params_hash,
                 output_path, bytes, runtime_ms, session_id, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                op_name,
                _jdump(list(input_content_hashes)),
                params_hash,
                output_path,
                bytes_,
                runtime_ms,
                session_id,
                timestamp or _now(),
            ),
        )
        return int(cur.lastrowid)


def record_plot(
    project_path: Path,
    *,
    op_name: str,
    input_content_hashes: Iterable[str],
    params_hash: str,
    plot_path: str,
    session_id: str,
    sidecar_path: Optional[str] = None,
    bytes_: Optional[int] = None,
    timestamp: Optional[str] = None,
) -> int:
    with open_ledger(project_path) as conn:
        cur = conn.execute(
            """INSERT INTO plots_generated(op_name, input_content_hashes,
                 params_hash, plot_path, sidecar_path, bytes, session_id, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                op_name,
                _jdump(list(input_content_hashes)),
                params_hash,
                plot_path,
                sidecar_path,
                bytes_,
                session_id,
                timestamp or _now(),
            ),
        )
        return int(cur.lastrowid)


def record_reference(
    project_path: Path,
    *,
    reference_path: str,
    source: str,
    session_id: str,
    title: Optional[str] = None,
    timestamp: Optional[str] = None,
) -> int:
    with open_ledger(project_path) as conn:
        cur = conn.execute(
            """INSERT INTO references_added(reference_path, source, title,
                 session_id, timestamp)
               VALUES (?, ?, ?, ?, ?)""",
            (reference_path, source, title, session_id, timestamp or _now()),
        )
        return int(cur.lastrowid)


def upsert_cache_entry(
    project_path: Path,
    *,
    op_name: str,
    input_content_hashes: Iterable[str],
    params_hash: str,
    output_path: str,
    bytes_: Optional[int] = None,
) -> int:
    """Insert or refresh a cache row. On conflict, bumps ``hit_count``."""
    now = _now()
    hashes_json = _jdump(list(input_content_hashes))
    with open_ledger(project_path) as conn:
        cur = conn.execute(
            """INSERT INTO cache_entries(op_name, input_content_hashes,
                 params_hash, output_path, bytes, created_at, last_hit_at, hit_count)
               VALUES (?, ?, ?, ?, ?, ?, ?, 0)
               ON CONFLICT(op_name, input_content_hashes, params_hash) DO UPDATE SET
                 last_hit_at = excluded.last_hit_at,
                 hit_count = cache_entries.hit_count + 1""",
            (op_name, hashes_json, params_hash, output_path, bytes_, now, now),
        )
        if cur.lastrowid:
            return int(cur.lastrowid)
        row = conn.execute(
            """SELECT id FROM cache_entries
               WHERE op_name = ? AND input_content_hashes = ? AND params_hash = ?""",
            (op_name, hashes_json, params_hash),
        ).fetchone()
        return int(row["id"])


def lookup_cache(
    project_path: Path,
    *,
    op_name: str,
    input_content_hashes: Iterable[str],
    params_hash: str,
) -> Optional[dict]:
    """Return the cache row if it exists, else None. Does not bump hit_count."""
    hashes_json = _jdump(list(input_content_hashes))
    with open_ledger(project_path) as conn:
        row = conn.execute(
            """SELECT * FROM cache_entries
               WHERE op_name = ? AND input_content_hashes = ? AND params_hash = ?""",
            (op_name, hashes_json, params_hash),
        ).fetchone()
        return dict(row) if row else None


# -- readers ----------------------------------------------------------------


@dataclass(frozen=True)
class LedgerRow:
    table: str
    row: dict


def read_ledger(
    project_path: Path,
    table: str,
    filters: Optional[dict] = None,
    limit: int = 100,
) -> list[dict]:
    """Structured query against a ledger table.

    ``filters`` is an equality-match dict (e.g. ``{"session_id": "abc"}``).
    Unknown columns raise ValueError to prevent silent empty results.
    """
    allowed = {
        "ops_runs",
        "plots_generated",
        "references_added",
        "cache_entries",
    }
    if table not in allowed:
        raise ValueError(f"unknown ledger table {table!r}; must be one of {allowed}")
    filters = filters or {}
    with open_ledger(project_path) as conn:
        cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        bad = set(filters) - cols
        if bad:
            raise ValueError(f"unknown columns {bad} for table {table}")
        where = ""
        params: list = []
        if filters:
            where = " WHERE " + " AND ".join(f"{k} = ?" for k in filters)
            params = list(filters.values())
        rows = conn.execute(
            f"SELECT * FROM {table}{where} ORDER BY id DESC LIMIT ?",
            (*params, limit),
        ).fetchall()
        return [dict(r) for r in rows]
