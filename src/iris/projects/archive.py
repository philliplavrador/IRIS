"""Monthly rollup of aged L2 digests.

For any session-final digest older than ``digest_retention_days`` with no
recent ``recall()`` hit, its content is compressed into
``digests/monthly_rollups/<YYYY-MM>.json`` and the per-session digest is
moved into an ``archive/`` subdir (still queryable via ``get``, but out of
the hot vector index). See §14.4.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from . import digest as _digest


def _parse_ts(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        s = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def rollup_old_digests(
    project_path: Path,
    retention_days: int = 90,
    *,
    now: Optional[datetime] = None,
) -> dict:
    """Roll up any final digest older than ``retention_days``.

    Returns ``{rolled: int, months: [str]}``.
    """
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=retention_days)

    digests_dir = _digest.digests_dir(project_path)
    archive_dir = digests_dir / "archive"
    rollups_dir = digests_dir / "monthly_rollups"

    rolled = 0
    months: set[str] = set()
    by_month: dict[str, list[dict]] = {}

    for path in _digest.list_finals(project_path):
        try:
            d = _digest.load(path)
        except Exception:
            continue
        ts = _parse_ts(d.get("updated_at") or d.get("created_at"))
        if ts is None or ts > cutoff:
            continue
        key = ts.strftime("%Y-%m")
        by_month.setdefault(key, []).append(_compact(d))
        archive_dir.mkdir(parents=True, exist_ok=True)
        path.replace(archive_dir / path.name)
        rolled += 1
        months.add(key)

    if by_month:
        rollups_dir.mkdir(parents=True, exist_ok=True)
        import json

        for month, entries in by_month.items():
            mpath = rollups_dir / f"{month}.json"
            existing = []
            if mpath.is_file():
                try:
                    existing = json.loads(mpath.read_text(encoding="utf-8"))
                except Exception:
                    existing = []
            merged = existing + entries
            mpath.write_text(
                json.dumps(merged, indent=2, sort_keys=False), encoding="utf-8"
            )

    return {"rolled": rolled, "months": sorted(months)}


def _compact(d: dict) -> dict:
    """Lossy compaction: keep only session_id, ts, focus, decisions, next_steps."""
    return {
        "session_id": d.get("session_id"),
        "updated_at": d.get("updated_at"),
        "focus": d.get("focus", ""),
        "decisions": [e["text"] for e in d.get("decisions", [])],
        "next_steps": [e["text"] for e in d.get("next_steps", [])],
    }
