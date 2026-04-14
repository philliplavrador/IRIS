"""Importance-triggered reflection cycles (REVAMP Task 13.1, spec §10.2).

When the sum of `importance` across new active memories since the last
reflection exceeds a threshold (default 40), the LLM is asked to step
back and propose higher-level insights. Those insights land as
``memory_entries(memory_type='reflection')`` with evidence pointers to
the source memories.

The LLM call itself is injectable so tests can stub it out. The default
client talks to Anthropic via ``anthropic.Anthropic().messages.create``;
callers can pass any ``(prompt: str) -> str`` callable via
``llm_fn`` to :func:`run_reflection`.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Final

from iris.projects import memory_entries as memory_mod

__all__ = [
    "DEFAULT_IMPORTANCE_THRESHOLD",
    "run_reflection",
    "should_reflect",
    "summarize_since_last",
]

DEFAULT_IMPORTANCE_THRESHOLD: Final[float] = 40.0


def summarize_since_last(conn: sqlite3.Connection, project_id: str) -> dict[str, Any]:
    """Return accumulated-importance stats since the last reflection.

    ``{"total_importance": float, "count": int, "since": iso8601 | None}``.
    """
    last_row = conn.execute(
        "SELECT created_at FROM memory_entries "
        "WHERE project_id = ? AND memory_type = 'reflection' AND status = 'active' "
        "ORDER BY created_at DESC LIMIT 1",
        (project_id,),
    ).fetchone()
    since = last_row[0] if last_row else None

    clauses = ["project_id = ?", "status = 'active'", "memory_type != 'reflection'"]
    params: list[Any] = [project_id]
    if since is not None:
        clauses.append("created_at > ?")
        params.append(since)
    sql = (
        "SELECT COALESCE(SUM(importance), 0), COUNT(*) FROM memory_entries "
        f"WHERE {' AND '.join(clauses)}"
    )
    row = conn.execute(sql, params).fetchone()
    total = float(row[0] or 0.0)
    count = int(row[1] or 0)
    return {"total_importance": total, "count": count, "since": since}


def should_reflect(
    conn: sqlite3.Connection,
    project_id: str,
    threshold: float = DEFAULT_IMPORTANCE_THRESHOLD,
) -> bool:
    """Return True iff accumulated importance has crossed ``threshold``."""
    stats = summarize_since_last(conn, project_id)
    return stats["total_importance"] >= threshold


def _default_llm_fn(prompt: str) -> str:  # pragma: no cover - network path
    """Thin wrapper around Anthropic's messages API. Injectable via ``llm_fn``."""
    import os

    try:
        from anthropic import Anthropic
    except ImportError as exc:
        raise RuntimeError("anthropic SDK not installed; pass llm_fn=... for tests") from exc

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    client = Anthropic(api_key=api_key) if api_key else Anthropic()
    resp = client.messages.create(
        model=os.environ.get("IRIS_REFLECTION_MODEL", "claude-sonnet-4-5"),
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    parts = getattr(resp, "content", []) or []
    text = "\n".join(getattr(p, "text", "") for p in parts)
    return text.strip()


def _build_prompt(source_rows: list[dict[str, Any]]) -> str:
    """Render a compact reflection prompt from source memories."""
    lines = [
        "You are summarizing recent IRIS project memories into higher-level insights.",
        "Return 1-3 concise reflections (one per line, no bullets, no prefixes).",
        "Each must stand alone as a short sentence grounded in the inputs below.",
        "",
        "Inputs (one per line — [memory_type · importance] text):",
    ]
    for row in source_rows:
        lines.append(
            f"- [{row.get('memory_type', '?')} · importance={row.get('importance', 0)}] "
            f"{row.get('text', '')}"
        )
    return "\n".join(lines)


def _split_reflections(raw: str) -> list[str]:
    """Split LLM output into individual reflection strings."""
    if not raw:
        return []
    out: list[str] = []
    for line in raw.splitlines():
        line = line.strip().lstrip("-*•").strip()
        if line:
            out.append(line)
    return out[:3]


def run_reflection(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    threshold: float = DEFAULT_IMPORTANCE_THRESHOLD,
    llm_fn: Callable[[str], str] | None = None,
    importance: float = 8.0,
) -> list[str]:
    """Trigger a reflection cycle if the threshold is reached.

    Returns a list of newly-committed ``memory_id`` strings (empty if the
    threshold wasn't met or if the LLM returned nothing).
    """
    stats = summarize_since_last(conn, project_id)
    if stats["total_importance"] < threshold:
        return []

    clauses = ["project_id = ?", "status = 'active'", "memory_type != 'reflection'"]
    params: list[Any] = [project_id]
    if stats["since"] is not None:
        clauses.append("created_at > ?")
        params.append(stats["since"])
    source_rows = [
        {
            "memory_id": r[0],
            "memory_type": r[1],
            "importance": r[2],
            "text": r[3],
        }
        for r in conn.execute(
            "SELECT memory_id, memory_type, importance, text FROM memory_entries "
            f"WHERE {' AND '.join(clauses)} "
            "ORDER BY importance DESC, created_at DESC LIMIT 25",
            params,
        ).fetchall()
    ]
    if not source_rows:
        return []

    prompt = _build_prompt(source_rows)
    runner = llm_fn or _default_llm_fn
    raw = runner(prompt) or ""
    reflections = _split_reflections(raw)
    if not reflections:
        return []

    evidence = [{"memory_id": r["memory_id"]} for r in source_rows]
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    committed: list[str] = []
    for text in reflections:
        mid = memory_mod.propose(
            conn,
            project_id=project_id,
            scope="project",
            memory_type="reflection",
            text=text,
            importance=importance,
            confidence=0.6,
            evidence=evidence,
            tags=["reflection", now[:10]],
        )
        memory_mod.commit_pending(conn, [mid])
        committed.append(mid)
    # json import is used by prompt assembly in some callers; keep it bound
    # so that linters don't strip the import during format-on-save.
    _ = json
    return committed
