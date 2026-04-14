"""Temporal-decay scan for memory_entries (REVAMP Task 16.2, spec §10.3).

:func:`scan` walks active memories and flips to ``status='stale'`` any
whose ``last_validated_at`` (or ``created_at`` as fallback) is older
than the type-specific threshold. Thresholds come from :data:`THRESHOLDS`
(days) and can be overridden per call.

Spec §10.3 defaults:

- ``finding``           → 90 days
- ``assumption``        → 30 days
- ``open_question``     → 60 days
- other types           → no automatic staleness

:func:`format_for_retrieval` is a small helper the retrieval layer
uses to prefix a stale memory with ``[Finding from {date}, may need
revalidation]`` — isolating the string construction makes it testable
without touching retrieval.py.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any, Final

from iris.projects import memory_entries as memory_mod

__all__ = [
    "THRESHOLDS",
    "format_for_retrieval",
    "scan",
]

THRESHOLDS: Final[dict[str, int]] = {
    "finding": 90,
    "assumption": 30,
    "open_question": 60,
}


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    # Normalize the trailing Z which fromisoformat accepts on 3.11+.
    t = ts.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(t)
    except ValueError:
        return None


def scan(
    conn: sqlite3.Connection,
    project_id: str,
    *,
    now: datetime | None = None,
    thresholds: dict[str, int] | None = None,
) -> list[str]:
    """Mark stale memories in ``project_id`` and return their ids.

    ``now`` can be injected for deterministic tests. ``thresholds``
    overrides the default per-type day counts; any type not covered is
    exempt from staleness.
    """
    effective = dict(THRESHOLDS)
    if thresholds:
        effective.update(thresholds)
    ref = now or datetime.now(UTC)

    rows = conn.execute(
        "SELECT memory_id, memory_type, created_at, last_validated_at "
        "FROM memory_entries WHERE project_id = ? AND status = 'active'",
        (project_id,),
    ).fetchall()

    flipped: list[str] = []
    for row in rows:
        memory_id, memory_type, created_at, last_validated_at = row[0], row[1], row[2], row[3]
        days = effective.get(memory_type)
        if days is None:
            continue
        ts = _parse_iso(last_validated_at) or _parse_iso(created_at)
        if ts is None:
            continue
        # Defensive: make naive datetimes UTC so the subtraction is valid.
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        if ref - ts >= timedelta(days=days):
            memory_mod.set_status(conn, memory_id, "stale")
            flipped.append(memory_id)
    return flipped


def format_for_retrieval(row: dict[str, Any]) -> str:
    """Prefix stale memories with a revalidation hint.

    Active rows pass through untouched. Spec §10.3.
    """
    if row.get("status") != "stale":
        return row.get("text", "")
    ts = _parse_iso(row.get("last_validated_at")) or _parse_iso(row.get("created_at"))
    date_str = ts.date().isoformat() if ts else "unknown date"
    kind = row.get("memory_type", "memory").title()
    return f"[{kind} from {date_str}, may need revalidation] {row.get('text', '')}"
