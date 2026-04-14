"""Contradiction detection + resolution (REVAMP Task 16.1, spec §10.3, §11.3).

When a new active memory lands we optionally ask the LLM whether any
existing active memory of the same scope/type contradicts it. On a hit:

- A ``contradictions`` row records both memory_ids and the evidence
  pointer.
- The older memory flips to ``status='contradicted'`` so the retrieval
  layer stops surfacing it.

:func:`resolve` closes a contradiction by picking a winning memory and
marking the other as contradicted for good.

LLM call is injectable via ``llm_fn``. Tests never need network.
"""

from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from iris.projects import memory_entries as memory_mod

__all__ = [
    "detect_contradictions",
    "list_contradictions",
    "resolve",
]


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _default_llm_fn(prompt: str) -> str:  # pragma: no cover - network path
    import os

    try:
        from anthropic import Anthropic
    except ImportError as exc:
        raise RuntimeError("anthropic SDK not installed; pass llm_fn=... for tests") from exc

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    client = Anthropic(api_key=api_key) if api_key else Anthropic()
    resp = client.messages.create(
        model=os.environ.get("IRIS_CONTRADICTION_MODEL", "claude-sonnet-4-5"),
        max_tokens=256,
        messages=[{"role": "user", "content": prompt}],
    )
    parts = getattr(resp, "content", []) or []
    return "\n".join(getattr(p, "text", "") for p in parts).strip()


def _load_new_memory(conn: sqlite3.Connection, memory_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT memory_id, project_id, scope, memory_type, text, status "
        "FROM memory_entries WHERE memory_id = ?",
        (memory_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "memory_id": row[0],
        "project_id": row[1],
        "scope": row[2],
        "memory_type": row[3],
        "text": row[4],
        "status": row[5],
    }


def _candidates(
    conn: sqlite3.Connection, new: dict[str, Any], limit: int = 25
) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT memory_id, text FROM memory_entries "
        "WHERE project_id = ? AND scope = ? AND memory_type = ? "
        "AND status = 'active' AND memory_id != ? "
        "ORDER BY importance DESC, created_at DESC LIMIT ?",
        (new["project_id"], new["scope"], new["memory_type"], new["memory_id"], limit),
    ).fetchall()
    return [{"memory_id": r[0], "text": r[1]} for r in rows]


def _prompt(new: dict[str, Any], candidates: list[dict[str, Any]]) -> str:
    lines = [
        "You are deciding whether a new memory contradicts any existing ones.",
        "Return only the memory_id values of the contradicting existing memories,",
        "one per line. If none contradict, return an empty response.",
        "",
        f"New memory: {new['text']}",
        "",
        "Existing candidates:",
    ]
    for c in candidates:
        lines.append(f"[{c['memory_id']}] {c['text']}")
    return "\n".join(lines)


def _parse_ids(raw: str, allowed: set[str]) -> list[str]:
    ids: list[str] = []
    for line in (raw or "").splitlines():
        tok = line.strip().strip("[]").split()[0] if line.strip() else ""
        if tok in allowed and tok not in ids:
            ids.append(tok)
    return ids


def detect_contradictions(
    conn: sqlite3.Connection,
    new_memory_id: str,
    *,
    llm_fn: Callable[[str], str] | None = None,
) -> list[str]:
    """Return memory_ids of existing memories that contradict ``new_memory_id``.

    Side effects: for each contradiction, insert a ``contradictions`` row
    and flip the older memory to ``status='contradicted'``.
    """
    new = _load_new_memory(conn, new_memory_id)
    if new is None or new["status"] != "active":
        return []

    cands = _candidates(conn, new)
    if not cands:
        return []

    runner = llm_fn or _default_llm_fn
    raw = runner(_prompt(new, cands)) or ""
    allowed = {c["memory_id"] for c in cands}
    hits = _parse_ids(raw, allowed)
    if not hits:
        return []

    now = _now_iso()
    for other_id in hits:
        contradiction_id = uuid.uuid4().hex
        conn.execute(
            "INSERT INTO contradictions ("
            "contradiction_id, project_id, memory_id_a, memory_id_b, "
            "evidence_json, resolved, created_at"
            ") VALUES (?, ?, ?, ?, ?, 0, ?)",
            (contradiction_id, new["project_id"], new_memory_id, other_id, None, now),
        )
        memory_mod.set_status(conn, other_id, "contradicted")
    return hits


def list_contradictions(
    conn: sqlite3.Connection, *, project_id: str, resolved: bool | None = False
) -> list[dict[str, Any]]:
    """Return contradiction rows for ``project_id``, filtered by ``resolved``."""
    clauses = ["project_id = ?"]
    params: list[Any] = [project_id]
    if resolved is not None:
        clauses.append("resolved = ?")
        params.append(1 if resolved else 0)
    rows = conn.execute(
        "SELECT contradiction_id, project_id, memory_id_a, memory_id_b, "
        "resolved, resolution_text, created_at, resolved_at "
        f"FROM contradictions WHERE {' AND '.join(clauses)} "
        "ORDER BY created_at DESC",
        params,
    ).fetchall()
    return [
        {
            "contradiction_id": r[0],
            "project_id": r[1],
            "memory_id_a": r[2],
            "memory_id_b": r[3],
            "resolved": bool(r[4]),
            "resolution_text": r[5],
            "created_at": r[6],
            "resolved_at": r[7],
        }
        for r in rows
    ]


def resolve(
    conn: sqlite3.Connection,
    contradiction_id: str,
    *,
    resolution_text: str,
    winning_memory_id: str,
) -> None:
    """Close a contradiction. Loser flips to ``contradicted``, winner to ``active``."""
    row = conn.execute(
        "SELECT memory_id_a, memory_id_b FROM contradictions WHERE contradiction_id = ?",
        (contradiction_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"contradiction {contradiction_id!r} not found")
    a, b = row[0], row[1]
    if winning_memory_id not in (a, b):
        raise ValueError(f"winning_memory_id {winning_memory_id!r} must be one of {a!r}, {b!r}")
    loser = b if winning_memory_id == a else a

    now = _now_iso()
    conn.execute(
        "UPDATE contradictions SET resolved = 1, resolution_text = ?, resolved_at = ? "
        "WHERE contradiction_id = ?",
        (resolution_text, now, contradiction_id),
    )
    memory_mod.set_status(conn, winning_memory_id, "active")
    memory_mod.set_status(conn, loser, "contradicted")
