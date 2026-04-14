"""L3 curated knowledge — SQLite-backed, user-confirmed memory.

Tables: ``goals``, ``decisions``, ``learned_facts``, ``declined_suggestions``,
``data_profile_fields``. All writes are user-gated (proposed mid-session,
committed at session-end via :func:`commit_pending`). See
docs/iris-behavior.md §3.4 and §7.

Also supports lifecycle fields (status, supersedes, last_referenced_at) per
§14.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

KNOWLEDGE_FILENAME = "knowledge.sqlite"
SCHEMA_VERSION = 1

STATUSES = ("active", "done", "superseded", "abandoned")

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    opened_session TEXT,
    closed_session TEXT,
    last_referenced_at TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_goals_status ON goals(status);

CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    rationale TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    supersedes INTEGER,                   -- fk -> decisions.id, nullable
    created_session TEXT,
    last_referenced_at TEXT,
    tags TEXT,                            -- JSON array
    created_at TEXT NOT NULL,
    FOREIGN KEY(supersedes) REFERENCES decisions(id)
);
CREATE INDEX IF NOT EXISTS idx_decisions_status ON decisions(status);
CREATE INDEX IF NOT EXISTS idx_decisions_supersedes ON decisions(supersedes);

CREATE TABLE IF NOT EXISTS learned_facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    source_session TEXT,
    confidence REAL,                      -- 0..1
    superseded_by INTEGER,
    last_referenced_at TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(superseded_by) REFERENCES learned_facts(id)
);
CREATE INDEX IF NOT EXISTS idx_facts_key ON learned_facts(key);

CREATE TABLE IF NOT EXISTS declined_suggestions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    declined_session TEXT,
    last_re_offered_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS data_profile_fields (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    field_path TEXT NOT NULL,             -- e.g. "file.csv::column.t"
    annotation TEXT,                      -- user-supplied semantic meaning
    confirmed_by_user INTEGER NOT NULL DEFAULT 0,  -- 0/1 boolean
    session TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(field_path)
);

-- Pending-write staging. Rows are accumulated mid-session via propose_* and
-- flushed to the real tables at session-end by commit_pending().
CREATE TABLE IF NOT EXISTS pending_writes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,                   -- decision | goal | fact | declined | profile_annotation
    payload TEXT NOT NULL,                -- JSON
    session_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pending_session ON pending_writes(session_id);
"""


# -- init / connection ------------------------------------------------------


def knowledge_path(project_path: Path) -> Path:
    return Path(project_path) / KNOWLEDGE_FILENAME


def init_knowledge(project_path: Path) -> Path:
    """Create ``knowledge.sqlite`` with the current schema. Idempotent."""
    path = knowledge_path(project_path)
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
def open_knowledge(project_path: Path) -> Iterator[sqlite3.Connection]:
    path = knowledge_path(project_path)
    if not path.is_file():
        init_knowledge(project_path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# -- helpers ----------------------------------------------------------------


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _validate_status(status: str) -> None:
    if status not in STATUSES:
        raise ValueError(f"invalid status {status!r}; must be one of {STATUSES}")


# -- proposals (pending, not yet committed) ---------------------------------


_PROPOSAL_KINDS = ("decision", "goal", "fact", "declined", "profile_annotation")


def propose(
    project_path: Path,
    kind: str,
    payload: dict,
    session_id: str,
) -> int:
    """Stage a proposed write. Returns the pending row id.

    Pending rows live in ``pending_writes`` until :func:`commit_pending`
    promotes them to their target table (or :func:`discard_pending` drops them).
    """
    import json

    if kind not in _PROPOSAL_KINDS:
        raise ValueError(f"unknown proposal kind {kind!r}; must be one of {_PROPOSAL_KINDS}")
    with open_knowledge(project_path) as conn:
        cur = conn.execute(
            """INSERT INTO pending_writes(kind, payload, session_id, created_at)
               VALUES (?, ?, ?, ?)""",
            (kind, json.dumps(payload, sort_keys=True), session_id, _now()),
        )
        return int(cur.lastrowid)


def list_pending(project_path: Path, session_id: Optional[str] = None) -> list[dict]:
    import json

    with open_knowledge(project_path) as conn:
        if session_id is None:
            rows = conn.execute(
                "SELECT * FROM pending_writes ORDER BY id ASC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM pending_writes WHERE session_id = ? ORDER BY id ASC",
                (session_id,),
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["payload"] = json.loads(d["payload"])
            out.append(d)
        return out


def discard_pending(project_path: Path, pending_ids: list[int]) -> int:
    """Delete specified pending rows. Returns number deleted."""
    if not pending_ids:
        return 0
    with open_knowledge(project_path) as conn:
        placeholders = ",".join("?" * len(pending_ids))
        cur = conn.execute(
            f"DELETE FROM pending_writes WHERE id IN ({placeholders})",
            pending_ids,
        )
        return cur.rowcount


def commit_pending(
    project_path: Path,
    session_id: str,
    *,
    approve_ids: Optional[list[int]] = None,
) -> dict:
    """Flush pending writes for ``session_id`` to their target tables.

    If ``approve_ids`` is None, approves all pending rows for the session.
    Otherwise only those ids are committed; the rest remain pending.

    Returns a report dict: ``{committed: int, by_kind: {kind: count}}``.
    Atomic — rolls back on any error.
    """
    import json

    report = {"committed": 0, "by_kind": {}}
    with open_knowledge(project_path) as conn:
        if approve_ids is None:
            rows = conn.execute(
                "SELECT * FROM pending_writes WHERE session_id = ? ORDER BY id ASC",
                (session_id,),
            ).fetchall()
        else:
            if not approve_ids:
                return report
            placeholders = ",".join("?" * len(approve_ids))
            rows = conn.execute(
                f"""SELECT * FROM pending_writes
                    WHERE session_id = ? AND id IN ({placeholders})
                    ORDER BY id ASC""",
                (session_id, *approve_ids),
            ).fetchall()

        for r in rows:
            kind = r["kind"]
            payload = json.loads(r["payload"])
            _commit_one(conn, kind, payload, session_id)
            report["by_kind"][kind] = report["by_kind"].get(kind, 0) + 1
            report["committed"] += 1
            conn.execute("DELETE FROM pending_writes WHERE id = ?", (r["id"],))
    return report


def _commit_one(conn: sqlite3.Connection, kind: str, p: dict, session_id: str) -> int:
    import json

    now = _now()
    if kind == "goal":
        cur = conn.execute(
            """INSERT INTO goals(text, status, opened_session, last_referenced_at, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (
                p["text"],
                p.get("status", "active"),
                session_id,
                now,
                now,
            ),
        )
        return int(cur.lastrowid)
    if kind == "decision":
        cur = conn.execute(
            """INSERT INTO decisions(text, rationale, status, supersedes,
                 created_session, last_referenced_at, tags, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                p["text"],
                p.get("rationale"),
                p.get("status", "active"),
                p.get("supersedes"),
                session_id,
                now,
                json.dumps(p.get("tags") or []),
                now,
            ),
        )
        new_id = int(cur.lastrowid)
        # Mark superseded row accordingly.
        if p.get("supersedes"):
            conn.execute(
                "UPDATE decisions SET status = 'superseded' WHERE id = ?",
                (p["supersedes"],),
            )
        return new_id
    if kind == "fact":
        cur = conn.execute(
            """INSERT INTO learned_facts(key, value, source_session,
                 confidence, last_referenced_at, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                p["key"],
                p["value"],
                session_id,
                p.get("confidence"),
                now,
                now,
            ),
        )
        return int(cur.lastrowid)
    if kind == "declined":
        cur = conn.execute(
            """INSERT INTO declined_suggestions(text, declined_session, created_at)
               VALUES (?, ?, ?)""",
            (p["text"], session_id, now),
        )
        return int(cur.lastrowid)
    if kind == "profile_annotation":
        cur = conn.execute(
            """INSERT INTO data_profile_fields(field_path, annotation,
                 confirmed_by_user, session, created_at)
               VALUES (?, ?, 1, ?, ?)
               ON CONFLICT(field_path) DO UPDATE SET
                 annotation = excluded.annotation,
                 confirmed_by_user = 1,
                 session = excluded.session""",
            (p["field_path"], p.get("annotation"), session_id, now),
        )
        return int(cur.lastrowid or 0)
    raise ValueError(f"unknown kind {kind!r}")


# -- direct readers (post-commit) -------------------------------------------


def active_goals(project_path: Path, limit: int = 5) -> list[dict]:
    with open_knowledge(project_path) as conn:
        rows = conn.execute(
            """SELECT * FROM goals WHERE status = 'active'
               ORDER BY COALESCE(last_referenced_at, created_at) DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def active_decisions(project_path: Path, limit: int = 10) -> list[dict]:
    with open_knowledge(project_path) as conn:
        rows = conn.execute(
            """SELECT * FROM decisions WHERE status = 'active'
               ORDER BY COALESCE(last_referenced_at, created_at) DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def recent_facts(project_path: Path, limit: int = 10) -> list[dict]:
    with open_knowledge(project_path) as conn:
        rows = conn.execute(
            """SELECT * FROM learned_facts WHERE superseded_by IS NULL
               ORDER BY COALESCE(last_referenced_at, created_at) DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def confirmed_profile_annotations(project_path: Path) -> list[dict]:
    with open_knowledge(project_path) as conn:
        rows = conn.execute(
            """SELECT * FROM data_profile_fields WHERE confirmed_by_user = 1
               ORDER BY id ASC"""
        ).fetchall()
        return [dict(r) for r in rows]


def bump_referenced(project_path: Path, table: str, row_id: int) -> None:
    """Mark a row as freshly referenced (drives recency scoring)."""
    allowed = {"goals", "decisions", "learned_facts"}
    if table not in allowed:
        raise ValueError(f"bump_referenced: bad table {table!r}")
    with open_knowledge(project_path) as conn:
        conn.execute(
            f"UPDATE {table} SET last_referenced_at = ? WHERE id = ?",
            (_now(), row_id),
        )


def set_status(project_path: Path, table: str, row_id: int, status: str) -> None:
    _validate_status(status)
    allowed = {"goals", "decisions"}
    if table not in allowed:
        raise ValueError(f"set_status: bad table {table!r}")
    with open_knowledge(project_path) as conn:
        conn.execute(
            f"UPDATE {table} SET status = ? WHERE id = ?", (status, row_id)
        )


_INSPECTOR_TABLES = (
    "goals",
    "decisions",
    "learned_facts",
    "declined_suggestions",
    "data_profile_fields",
)


def list_table(
    project_path: Path,
    table: str,
    *,
    status: Optional[str] = None,
    limit: int = 200,
) -> list[dict]:
    """List rows from any inspector table.

    Optional ``status`` filter applies to goals and decisions.
    """
    if table not in _INSPECTOR_TABLES:
        raise ValueError(
            f"list_table: bad table {table!r}; must be one of {_INSPECTOR_TABLES}"
        )
    with open_knowledge(project_path) as conn:
        cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        where = ""
        params: list = []
        if status is not None and "status" in cols:
            _validate_status(status)
            where = " WHERE status = ?"
            params.append(status)
        order_col = (
            "last_referenced_at"
            if "last_referenced_at" in cols
            else "created_at"
        )
        rows = conn.execute(
            f"SELECT * FROM {table}{where} ORDER BY COALESCE({order_col}, created_at) DESC LIMIT ?",
            (*params, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def delete_row(project_path: Path, table: str, row_id: int) -> int:
    """Hard delete. Used by inspector for facts and declined entries."""
    allowed = {"learned_facts", "declined_suggestions", "data_profile_fields"}
    if table not in allowed:
        raise ValueError(f"delete_row: table {table!r} not deletable")
    with open_knowledge(project_path) as conn:
        cur = conn.execute(f"DELETE FROM {table} WHERE id = ?", (row_id,))
        return cur.rowcount


def supersede_fact(
    project_path: Path, old_id: int, new_key: str, new_value: str, session_id: str
) -> int:
    """Create a new fact and point the old one's ``superseded_by`` at it."""
    with open_knowledge(project_path) as conn:
        now = _now()
        cur = conn.execute(
            """INSERT INTO learned_facts(key, value, source_session,
                 last_referenced_at, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (new_key, new_value, session_id, now, now),
        )
        new_id = int(cur.lastrowid)
        conn.execute(
            "UPDATE learned_facts SET superseded_by = ? WHERE id = ?",
            (new_id, old_id),
        )
        return new_id


def get(project_path: Path, table: str, row_id: int) -> Optional[dict]:
    """Fetch a single row by id (for citation resolution)."""
    allowed = {
        "goals",
        "decisions",
        "learned_facts",
        "declined_suggestions",
        "data_profile_fields",
    }
    if table not in allowed:
        raise ValueError(f"get: bad table {table!r}")
    with open_knowledge(project_path) as conn:
        row = conn.execute(
            f"SELECT * FROM {table} WHERE id = ?", (row_id,)
        ).fetchone()
        return dict(row) if row else None
