"""Progressive summarization (REVAMP Task 14.1, spec §10.2).

Two levels:

1. :func:`summarize_session` — boils a session's messages + findings into
   a short paragraph. Returned string is what callers hand to
   :func:`iris.projects.sessions.end_session` as the ``summary`` arg.
2. :func:`summarize_summaries` — once ``n`` session summaries have
   accumulated, asks the LLM for a super-summary and commits it as a
   ``memory_type='session_summary'`` memory entry with high importance.

The LLM call is injectable via ``llm_fn`` so tests don't need network.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import Any, Final

from iris.projects import memory_entries as memory_mod

__all__ = [
    "DEFAULT_SUMMARIZE_BATCH",
    "summarize_session",
    "summarize_summaries",
]

DEFAULT_SUMMARIZE_BATCH: Final[int] = 10


def _default_llm_fn(prompt: str) -> str:  # pragma: no cover - network path
    import os

    try:
        from anthropic import Anthropic
    except ImportError as exc:
        raise RuntimeError("anthropic SDK not installed; pass llm_fn=... for tests") from exc

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    client = Anthropic(api_key=api_key) if api_key else Anthropic()
    resp = client.messages.create(
        model=os.environ.get("IRIS_SUMMARY_MODEL", "claude-sonnet-4-5"),
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )
    parts = getattr(resp, "content", []) or []
    return "\n".join(getattr(p, "text", "") for p in parts).strip()


def _load_session_context(
    conn: sqlite3.Connection, session_id: str, message_limit: int = 40
) -> dict[str, Any]:
    """Collect the raw material a summarizer needs for one session."""
    messages = [
        {"role": r[0], "content": r[1]}
        for r in conn.execute(
            "SELECT role, content FROM messages WHERE session_id = ? "
            "ORDER BY ts ASC, rowid ASC LIMIT ?",
            (session_id, message_limit),
        ).fetchall()
    ]
    findings = [
        {"memory_type": r[0], "text": r[1], "importance": r[2]}
        for r in conn.execute(
            "SELECT memory_type, text, importance FROM memory_entries "
            "WHERE status = 'active' AND memory_type != 'session_summary' "
            "ORDER BY importance DESC, created_at DESC LIMIT 20"
        ).fetchall()
    ]
    return {"messages": messages, "findings": findings}


def _session_prompt(ctx: dict[str, Any]) -> str:
    lines = [
        "Summarize the following IRIS session in 2-4 sentences.",
        "Focus on what was decided, what was found, and any open questions.",
        "Plain prose only — no bullet points, no preamble.",
        "",
        "Messages:",
    ]
    for m in ctx["messages"]:
        snippet = (m["content"] or "").replace("\n", " ")[:200]
        lines.append(f"[{m['role']}] {snippet}")
    if ctx["findings"]:
        lines.append("")
        lines.append("Related active memories:")
        for f in ctx["findings"]:
            lines.append(f"- ({f['memory_type']} · importance={f['importance']}) {f['text']}")
    return "\n".join(lines)


def summarize_session(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    llm_fn: Callable[[str], str] | None = None,
) -> str:
    """Return a short summary string for ``session_id``.

    Returns an empty string if the session has no messages (still safe to
    pass to ``end_session``).
    """
    ctx = _load_session_context(conn, session_id)
    if not ctx["messages"]:
        return ""
    prompt = _session_prompt(ctx)
    runner = llm_fn or _default_llm_fn
    return (runner(prompt) or "").strip()


def _load_recent_session_summaries(
    conn: sqlite3.Connection, project_id: str, limit: int
) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT session_id, started_at, ended_at, summary "
        "FROM sessions WHERE project_id = ? AND summary IS NOT NULL "
        "ORDER BY COALESCE(ended_at, started_at) DESC LIMIT ?",
        (project_id, limit),
    ).fetchall()
    return [
        {
            "session_id": r[0],
            "started_at": r[1],
            "ended_at": r[2],
            "summary": r[3],
        }
        for r in rows
    ]


def _summaries_prompt(rows: list[dict[str, Any]]) -> str:
    lines = [
        "You are compressing the following session summaries into a single",
        "super-summary paragraph (3-5 sentences) capturing themes, trends,",
        "and recurring questions. Plain prose, no bullets.",
        "",
    ]
    for r in rows:
        lines.append(f"[{r['started_at'] or '?'} → {r['ended_at'] or '?'}] {r['summary']}")
    return "\n".join(lines)


def summarize_summaries(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    n: int = DEFAULT_SUMMARIZE_BATCH,
    llm_fn: Callable[[str], str] | None = None,
    importance: float = 6.0,
) -> str | None:
    """Summarize the ``n`` most recent session summaries into one memory.

    Commits the super-summary as ``memory_type='session_summary'`` and
    returns the new ``memory_id``. Returns ``None`` if fewer than ``n``
    summaries are available or the LLM yields nothing.
    """
    rows = _load_recent_session_summaries(conn, project_id, n)
    if len(rows) < n:
        return None

    prompt = _summaries_prompt(rows)
    runner = llm_fn or _default_llm_fn
    text = (runner(prompt) or "").strip()
    if not text:
        return None

    evidence = [{"session_id": r["session_id"]} for r in rows]
    mid = memory_mod.propose(
        conn,
        project_id=project_id,
        scope="project",
        memory_type="session_summary",
        text=text,
        importance=importance,
        confidence=0.6,
        evidence=evidence,
        tags=["session_summary"],
    )
    memory_mod.commit_pending(conn, [mid])
    return mid
