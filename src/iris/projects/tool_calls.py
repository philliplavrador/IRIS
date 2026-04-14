"""Tool-invocation records + tool-result clearing stub (spec §7.1, §9.3).

Every ``tool_use`` the agent emits (Bash, Read, Edit, iris op runs, etc.)
lands here. Each row also captures the matched ``tool_result`` once the SDK
streams it back — success/error, a short summary for retrieval, and a
pointer to the ``artifacts`` row if the output was large enough to warrant
content-addressed storage.

The *clearing* helper (:func:`summarize_for_clearing`) is used by the
agent-bridge (Task 3.6) to compact the SDK conversation buffer: after a
turn consumes a tool result, the full output is replaced by a 1-line stub
in-buffer, keeping the durable copy in ``artifacts`` + the searchable
summary in ``tool_calls.output_summary``. Spec §9.3 calls this out as the
single most impactful context-compaction rule in V1.

Public API
----------
- :func:`append_tool_call` — insert one tool-call row.
- :func:`attach_output_artifact` — late-bind the artifact id once the
  artifacts store has an address for the output.
- :func:`summarize_for_clearing` — pure helper, no DB side effects,
  formats the stub the agent-bridge substitutes in-conversation.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from typing import Any

__all__ = [
    "append_tool_call",
    "attach_output_artifact",
    "summarize_for_clearing",
]


def _now_iso() -> str:
    """Return the current time as an ISO-8601 string with ``Z`` suffix."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def append_tool_call(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    tool_name: str,
    input: Any,
    success: bool,
    event_id: str | None = None,
    output_summary: str | None = None,
    output_artifact_id: str | None = None,
    error: str | None = None,
    execution_time_ms: int | None = None,
) -> str:
    """Insert one row into ``tool_calls`` and return the new ``tool_call_id``.

    ``input`` is JSON-encoded with ``sort_keys=True`` so identical invocations
    hash the same — this is what the Phase 8 operation catalog and the
    Phase 9 retrieval scorer rely on for dedup + cache-key generation.

    Raises
    ------
    sqlite3.IntegrityError
        If ``session_id`` (or ``event_id``) violates a foreign key.
    """
    tool_call_id = uuid.uuid4().hex
    ts = _now_iso()
    input_json = json.dumps(input, sort_keys=True, separators=(",", ":"))

    conn.execute(
        "INSERT INTO tool_calls ("
        "tool_call_id, session_id, event_id, tool_name, input_json, "
        "output_artifact_id, output_summary, success, error_text, ts, "
        "execution_time_ms"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            tool_call_id,
            session_id,
            event_id,
            tool_name,
            input_json,
            output_artifact_id,
            output_summary,
            1 if success else 0,
            error,
            ts,
            execution_time_ms,
        ),
    )

    return tool_call_id


def attach_output_artifact(
    conn: sqlite3.Connection,
    tool_call_id: str,
    artifact_id: str,
) -> None:
    """Set ``output_artifact_id`` on an existing tool-call row.

    Called after Phase 5's ``artifacts.store`` has produced a SHA-addressed
    row for a tool output that was too large to inline into
    ``output_summary``. Raises :class:`LookupError` if the tool-call row
    does not exist.
    """
    cursor = conn.execute(
        "UPDATE tool_calls SET output_artifact_id = ? WHERE tool_call_id = ?",
        (artifact_id, tool_call_id),
    )
    if cursor.rowcount == 0:
        raise LookupError(f"tool_call {tool_call_id!r} not found")


def summarize_for_clearing(tool_call_id: str, output_text: str) -> str:
    """Return the in-conversation stub used to clear a bulky tool result.

    The format is spec §9.3's recommended shape: a one-line preamble plus
    the artifact pointer so the agent can still retrieve the full payload
    via ``/memory/artifacts/<id>/bytes`` if later turns need it. The
    *name* of the tool is not known inside this helper (clearing happens
    per tool_call_id), so the caller substitutes it when it builds the
    stub block — this function stays pure + name-agnostic.

    Parameters
    ----------
    tool_call_id
        Database id of the cleared call — embedded so retrieval can join
        back to the original row.
    output_text
        Raw tool output. The first non-empty line (trimmed, capped at
        120 chars) becomes the visible summary. If every line is blank we
        fall back to ``"<empty output>"`` so the stub is never malformed.
    """
    summary = _one_line_summary(output_text)
    return (
        f"[Tool result cleared. Summary: {summary}. "
        f"Full output retained as tool_call {tool_call_id}.]"
    )


def _one_line_summary(output_text: str, *, max_chars: int = 120) -> str:
    """Collapse ``output_text`` to one trimmed line, capped at ``max_chars``."""
    for line in output_text.splitlines():
        s = line.strip()
        if s:
            if len(s) > max_chars:
                return s[: max_chars - 1] + "\u2026"
            return s
    return "<empty output>"
