"""7-segment LLM context assembly (spec §9.1, §9.2).

Pure assembly function: given a project + session, pull each context
segment (in spec §9.1 order) and render it within its token budget.
The stable-prefix ordering (system prompt, core memory, dataset
context) lands first so prompt caching pays off.

Each segment is loaded defensively — a missing table or import failure
in one segment yields an empty string for that segment and does not
abort the rest of the assembly. This keeps early-phase projects (no
runs, no datasets, no ops) callable without special-casing at the
daemon boundary.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Final

__all__ = [
    "DEFAULT_BUDGETS",
    "SEGMENT_NAMES",
    "approximate_tokens",
    "build_slice",
]

DEFAULT_BUDGETS: Final[dict[str, int]] = {
    "system_prompt": 500,
    "core_memory": 1500,
    "dataset_context": 500,
    "retrieved_memories": 2000,
    "prior_analyses": 1000,
    "operations": 1000,
    "conversation_window": 3000,
}

SEGMENT_NAMES: Final[tuple[str, ...]] = (
    "system_prompt",
    "core_memory",
    "dataset_context",
    "retrieved_memories",
    "prior_analyses",
    "operations",
    "conversation_window",
)

_TRUNCATION_MARKER: Final[str] = "...[truncated]"


def approximate_tokens(text: str) -> int:
    return len(text) // 4


def _truncate(text: str, budget_tokens: int) -> str:
    if approximate_tokens(text) <= budget_tokens:
        return text
    marker_tokens = approximate_tokens(_TRUNCATION_MARKER)
    if budget_tokens <= marker_tokens + 1:
        return text[: max(0, budget_tokens * 4)]
    target_chars = max(0, (budget_tokens - marker_tokens - 1) * 4)
    return text[:target_chars].rstrip() + _TRUNCATION_MARKER


# -- segment loaders (each returns either a rendered string or "") ---------


def _load_dials() -> dict[str, Any]:
    try:
        from iris import config as iris_config

        cfg = iris_config.load_configs()
        agent = cfg.agent or {}
        dials = agent.get("dials") or {}
        return dials if isinstance(dials, dict) else {}
    except Exception:
        return {}


def _render_system_prompt(dials: dict[str, Any]) -> str:
    lines = [
        "You are IRIS, a local AI-powered data-analysis research partner.",
        "You help users explore datasets, run signal-processing operations,",
        "generate plots, and build reports. Prefer small, citable answers",
        "grounded in prior findings and the project's datasets.",
        "",
        "Output format: markdown. Cite memory entries by memory_id when used.",
    ]
    if dials:
        lines.append("")
        lines.append("Agent dials (from config.toml [agent.dials]):")
        for key in sorted(dials):
            lines.append(f"- {key}: {dials[key]!r}")
    return "\n".join(lines)


def _render_core_memory(conn: sqlite3.Connection, project_id: str) -> str:
    try:
        from iris.projects import memory_entries as me_mod

        rows = me_mod.query(
            conn,
            project_id=project_id,
            status="active",
            limit=50,
            order_by="importance DESC",
        )
    except Exception:
        return ""
    rows = [r for r in rows if (r.get("importance") or 0.0) >= 8.0]
    if not rows:
        return ""
    lines = ["# Core memory (high-importance active entries)"]
    for r in rows:
        lines.append(
            f"- [{r.get('memory_type', '?')} · importance={r.get('importance', 0)} · "
            f"{r.get('memory_id', '')}] {r.get('text', '')}"
        )
    return "\n".join(lines)


def _render_dataset_context(conn: sqlite3.Connection, project_id: str) -> str:
    try:
        from iris.projects import datasets as ds_mod

        rows = ds_mod.list_datasets(conn, project_id=project_id)
    except Exception:
        return ""
    if not rows:
        return ""
    ds = dict(rows[0])
    lines = ["# Active dataset"]
    lines.append(f"- name: {ds.get('name', '?')}")
    lines.append(f"- dataset_id: {ds.get('dataset_id', '?')}")
    if ds.get("original_filename"):
        lines.append(f"- original_filename: {ds['original_filename']}")
    version_row = None
    try:
        version_row = conn.execute(
            "SELECT schema_json, row_count, description "
            "FROM dataset_versions WHERE dataset_id = ? "
            "ORDER BY created_at DESC LIMIT 1",
            (ds["dataset_id"],),
        ).fetchone()
    except sqlite3.Error:
        pass
    if version_row is not None:
        schema_json, row_count, description = version_row[0], version_row[1], version_row[2]
        if row_count is not None:
            lines.append(f"- row_count: {row_count}")
        if schema_json:
            try:
                parsed = json.loads(schema_json) if isinstance(schema_json, str) else schema_json
                lines.append(f"- schema: {json.dumps(parsed, separators=(',', ':'))}")
            except (json.JSONDecodeError, TypeError):
                lines.append(f"- schema: {schema_json}")
        if description:
            lines.append(f"- description: {description}")
    return "\n".join(lines)


def _render_retrieved(conn: sqlite3.Connection, project_id: str, query: str) -> str:
    try:
        from iris.projects import retrieval as retrieval_mod

        hits = retrieval_mod.recall(conn, project_id=project_id, query=query, limit=10)
    except Exception:
        return ""
    if not hits:
        return ""
    lines = ["# Retrieved memories (relevance-ranked)"]
    for h in hits:
        score = h.get("score", 0.0)
        lines.append(
            f"- [{h.get('memory_type', '?')} · score={score:.3f} · "
            f"{h.get('memory_id', '')}] {h.get('text', '')}"
        )
    return "\n".join(lines)


def _should_retrieve(query: str | None) -> bool:
    if not query:
        return False
    try:
        from iris.projects import retrieval as retrieval_mod

        return bool(retrieval_mod.should_retrieve(query))
    except Exception:
        return False


def _render_prior_analyses(conn: sqlite3.Connection, project_id: str) -> str:
    try:
        from iris.projects import runs as runs_mod

        rows = runs_mod.list_runs(conn, project_id=project_id, limit=10)
    except Exception:
        return ""
    if not rows:
        return ""
    lines = ["# Recent runs (prior analyses)"]
    for r in rows:
        lines.append(
            f"- [{r.get('operation_type', '?')} · {r.get('status', '?')} · "
            f"{r.get('run_id', '')}] {r.get('findings_text') or '(no findings)'}"
        )
    return "\n".join(lines)


def _render_operations(conn: sqlite3.Connection, project_id: str) -> str:
    try:
        from iris.projects import operations_store as ops_mod

        rows = ops_mod.list(conn, project_id=project_id, status="active", limit=20)
        if not rows:
            rows = ops_mod.list(conn, project_id=None, status="active", limit=20)
    except Exception:
        return ""
    if not rows:
        return ""
    lines = ["# Operations catalog (active)"]
    for op in rows:
        rate = op.get("success_rate")
        rate_str = f" · success={rate:.2f}" if rate is not None else ""
        lines.append(
            f"- {op.get('name', '?')}@{op.get('version', '?')}{rate_str}: "
            f"{op.get('description') or ''}"
        )
    return "\n".join(lines)


def _render_conversation_window(conn: sqlite3.Connection, session_id: str, limit: int = 50) -> str:
    try:
        rows = conn.execute(
            "SELECT role, content FROM messages WHERE session_id = ? "
            "ORDER BY ts DESC, rowid DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()
    except sqlite3.Error:
        return ""
    if not rows:
        return ""
    rows = list(reversed(rows))  # chronological for the LLM
    lines = ["# Conversation window"]
    for r in rows:
        lines.append(f"[{r[0]}] {r[1]}")
    return "\n".join(lines)


# -- main entry -------------------------------------------------------------


def build_slice(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    session_id: str,
    current_query: str | None = None,
    budgets: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Assemble the 7-segment LLM context slice.

    Returns ``{"segments": [...], "total_tokens": int,
    "retrieval_skipped": bool}``. Segments are in spec §9.1 order;
    segment 4 (retrieved_memories) is only populated when
    ``should_retrieve(current_query)`` returns True.
    """
    merged = dict(DEFAULT_BUDGETS)
    if budgets:
        merged.update(budgets)

    dials = _load_dials()
    retrieval_skipped = not _should_retrieve(current_query)
    if retrieval_skipped or current_query is None:
        retrieved = ""
    else:
        retrieved = _render_retrieved(conn, project_id, current_query)

    raw = {
        "system_prompt": _render_system_prompt(dials),
        "core_memory": _render_core_memory(conn, project_id),
        "dataset_context": _render_dataset_context(conn, project_id),
        "retrieved_memories": retrieved,
        "prior_analyses": _render_prior_analyses(conn, project_id),
        "operations": _render_operations(conn, project_id),
        "conversation_window": _render_conversation_window(conn, session_id),
    }

    segments: list[dict[str, Any]] = []
    total = 0
    for name in SEGMENT_NAMES:
        content = _truncate(raw[name], merged[name])
        tokens = approximate_tokens(content)
        segments.append({"name": name, "content": content, "token_count": tokens})
        total += tokens

    return {
        "segments": segments,
        "total_tokens": total,
        "retrieval_skipped": retrieval_skipped,
    }
