"""Session-end LLM extraction of semantic memories.

Spec refs: `IRIS Memory Restructure.md` §10.1 (passive extraction — session-end
pathway) and §11.4 (importance threshold of 4/10).

This module reads all messages recorded for a memory session, asks Claude to
emit a structured list of candidate memories (findings, assumptions, caveats,
open questions, decisions, failure reflections — each scored 1-10 for
importance), filters to importance >= 4, and proposes each kept candidate as a
``status='draft'`` row in ``memory_entries`` via :func:`memory_entries.propose`.

V1 scope is session-end only. Phase 12 will add a per-turn ``extract_turn``
following Mem0's continuous-extraction pattern.

Public API
----------
- :func:`extract_session`
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
from typing import Any, Final

from . import memory_entries as memory_entries_mod

__all__ = ["extract_session", "extract_turn"]

_LOG = logging.getLogger(__name__)

# Importance cutoff per spec §11.4 ("low-signal accumulation" defense).
_IMPORTANCE_THRESHOLD: Final[float] = 4.0

# Default Claude model; overridable via env for smoke tests / cheaper runs.
_DEFAULT_MODEL: Final[str] = "claude-sonnet-4-5"
_MODEL_ENV_VAR: Final[str] = "IRIS_EXTRACTION_MODEL"
_API_KEY_ENV_VAR: Final[str] = "ANTHROPIC_API_KEY"

# Category -> memory_type enum value in the schema. These names match the
# enum documented in ``schema.sql`` and the ``MEMORY_TYPES`` frozenset in
# :mod:`memory_entries`.
_CATEGORY_TO_MEMORY_TYPE: Final[dict[str, str]] = {
    "findings": "finding",
    "assumptions": "assumption",
    "caveats": "caveat",
    "open_questions": "open_question",
    "decisions": "decision",
    "failure_reflections": "failure_reflection",
}

_SYSTEM_PROMPT = (
    "You extract durable research memories from an analyst's chat transcript. "
    "Return STRICT JSON matching exactly this schema:\n"
    "{\n"
    '  "findings": [{"text": str, "importance": int}],\n'
    '  "assumptions": [{"text": str, "importance": int}],\n'
    '  "caveats": [{"text": str, "importance": int}],\n'
    '  "open_questions": [{"text": str, "importance": int}],\n'
    '  "decisions": [{"text": str, "importance": int}],\n'
    '  "failure_reflections": [{"text": str, "importance": int}]\n'
    "}\n"
    "Each array may be empty. `importance` is an integer 1-10 where "
    "1 = trivial bookkeeping and 10 = project-defining insight. Emit "
    "importance >= 4 only for items a future session should actually recall. "
    "Keep `text` a single self-contained sentence (no pronouns with unclear "
    "referents). Do NOT wrap the JSON in prose, code fences, or commentary."
)

_USER_PROMPT_TEMPLATE = (
    "Transcript of the session (each line is one message):\n"
    "----- BEGIN TRANSCRIPT -----\n"
    "{transcript}\n"
    "----- END TRANSCRIPT -----\n\n"
    "Extract memories now."
)


# -- public API -------------------------------------------------------------


def extract_session(conn: sqlite3.Connection, session_id: str) -> list[str]:
    """Run session-end extraction and return proposed memory IDs.

    Reads all messages for ``session_id`` (ordered by rowid ASC), asks Claude
    for a structured extraction, filters each candidate to importance >= 4,
    and calls :func:`memory_entries.propose` for the survivors with
    ``scope='session'`` mapped down to the valid ``scope='project'`` enum
    value (sessions are project-scoped; the originating session is recorded
    via ``session_id`` on the event).

    Parameters
    ----------
    conn:
        Open connection to the project's ``iris.sqlite``.
    session_id:
        The session whose transcript to extract.

    Returns
    -------
    list[str]
        Memory IDs of every proposed draft (status='draft'). Empty list if
        the session has no messages or the model returns no candidates.

    Raises
    ------
    ValueError
        If ``session_id`` does not exist.
    RuntimeError
        If the Anthropic SDK is unavailable, the API key is missing, the
        network call fails, or the model returns unparseable JSON. The
        message is actionable (tells the caller what to fix).
    """
    project_id = _resolve_project_id(conn, session_id)
    transcript = _build_transcript(conn, session_id)
    if not transcript:
        _LOG.info("extract_session: no messages for session %s", session_id)
        return []

    raw = _call_anthropic(transcript)
    payload = _parse_extraction_json(raw)

    proposed: list[str] = []
    for category, memory_type in _CATEGORY_TO_MEMORY_TYPE.items():
        items = payload.get(category) or []
        if not isinstance(items, list):
            _LOG.warning(
                "extract_session: category %r was %s, not list; skipping",
                category,
                type(items).__name__,
            )
            continue
        for item in items:
            parsed = _coerce_item(item)
            if parsed is None:
                continue
            text, importance = parsed
            if importance < _IMPORTANCE_THRESHOLD:
                continue
            memory_id = memory_entries_mod.propose(
                conn,
                project_id=project_id,
                scope="project",
                memory_type=memory_type,
                text=text,
                importance=float(importance),
                confidence=0.5,
                session_id=session_id,
            )
            proposed.append(memory_id)

    _LOG.info(
        "extract_session %s: proposed %d drafts (threshold >= %s)",
        session_id,
        len(proposed),
        _IMPORTANCE_THRESHOLD,
    )
    return proposed


# -- internals --------------------------------------------------------------


def extract_turn(
    conn: sqlite3.Connection,
    *,
    message_id: str,
    llm_fn: Any = None,
    dedup_threshold: float = 0.85,
) -> list[str]:
    """Per-turn extraction (Mem0-style, spec §10.1, REVAMP Task 12.1).

    Reads the assistant ``message_id`` plus the preceding user message
    (if any), asks the LLM for candidate memories, filters by importance,
    and dedups each candidate against existing active memories via an
    FTS5 BM25 lookup. Candidates whose best match's normalized BM25
    score exceeds ``dedup_threshold`` are dropped as duplicates.

    ``llm_fn`` takes ``(system_prompt, user_prompt) -> str``. ``None``
    uses the Anthropic SDK via :func:`_call_anthropic`.
    """
    row = conn.execute(
        "SELECT session_id, role, content FROM messages WHERE message_id = ?",
        (message_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"unknown message_id {message_id!r}")
    session_id, role, content = row[0], row[1], row[2]
    if role != "assistant" or not content:
        return []
    project_id = _resolve_project_id(conn, session_id)

    prior = conn.execute(
        "SELECT role, content FROM messages "
        "WHERE session_id = ? AND rowid < (SELECT rowid FROM messages WHERE message_id = ?) "
        "ORDER BY rowid DESC LIMIT 1",
        (session_id, message_id),
    ).fetchone()
    lines = []
    if prior is not None:
        lines.append(f"[{prior[0]}] {str(prior[1]).replace(chr(10), ' ')}")
    lines.append(f"[assistant] {str(content).replace(chr(10), ' ')}")
    transcript = "\n".join(lines)

    if llm_fn is None:
        raw = _call_anthropic(transcript)
    else:
        raw = llm_fn(_SYSTEM_PROMPT, _USER_PROMPT_TEMPLATE.format(transcript=transcript))
    payload = _parse_extraction_json(raw)

    proposed: list[str] = []
    for category, memory_type in _CATEGORY_TO_MEMORY_TYPE.items():
        items = payload.get(category) or []
        if not isinstance(items, list):
            continue
        for item in items:
            parsed = _coerce_item(item)
            if parsed is None:
                continue
            text, importance = parsed
            if importance < _IMPORTANCE_THRESHOLD:
                continue
            if _is_duplicate(conn, project_id, text, memory_type, dedup_threshold):
                continue
            mid = memory_entries_mod.propose(
                conn,
                project_id=project_id,
                scope="project",
                memory_type=memory_type,
                text=text,
                importance=float(importance),
                confidence=0.5,
                session_id=session_id,
            )
            proposed.append(mid)
    return proposed


def _is_duplicate(
    conn: sqlite3.Connection,
    project_id: str,
    text: str,
    memory_type: str,
    threshold: float,
) -> bool:
    """Token-overlap dedup against active same-type memories.

    Jaccard similarity on the lowercased alphanumeric token sets, gated at
    ``threshold``. Cheap, deterministic, and doesn't need a working FTS5
    match — which can fail on short queries or stop-word-heavy phrases.
    """
    new_tokens = set(re.findall(r"\w+", text.lower()))
    if not new_tokens:
        return False
    rows = conn.execute(
        "SELECT text FROM memory_entries "
        "WHERE project_id = ? AND memory_type = ? AND status = 'active'",
        (project_id, memory_type),
    ).fetchall()
    for (existing_text,) in rows:
        existing_tokens = set(re.findall(r"\w+", (existing_text or "").lower()))
        if not existing_tokens:
            continue
        overlap = len(new_tokens & existing_tokens)
        union = len(new_tokens | existing_tokens)
        jaccard = overlap / union if union else 0.0
        if jaccard >= threshold:
            return True
    return False


def _resolve_project_id(conn: sqlite3.Connection, session_id: str) -> str:
    row = conn.execute(
        "SELECT project_id FROM sessions WHERE session_id = ?", (session_id,)
    ).fetchone()
    if row is None:
        raise ValueError(f"unknown session_id {session_id!r}")
    return str(row[0])


def _build_transcript(conn: sqlite3.Connection, session_id: str) -> str:
    rows = conn.execute(
        "SELECT role, content FROM messages WHERE session_id = ? ORDER BY rowid ASC",
        (session_id,),
    ).fetchall()
    if not rows:
        return ""
    lines: list[str] = []
    for role, content in rows:
        role_s = str(role) if role is not None else "unknown"
        content_s = str(content) if content is not None else ""
        # Compress multi-line messages onto one line so the LLM sees an
        # unambiguous "one message per line" structure. Long messages are
        # still fine — Sonnet's context is generous.
        flattened = content_s.replace("\r", " ").replace("\n", " ")
        lines.append(f"[{role_s}] {flattened}")
    return "\n".join(lines)


def _call_anthropic(transcript: str) -> str:
    try:
        from anthropic import Anthropic  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - env-dependent
        raise RuntimeError(
            "anthropic SDK not installed; run `uv add anthropic` or install it "
            "into the project venv before calling extract_session"
        ) from exc

    api_key = os.environ.get(_API_KEY_ENV_VAR)
    if not api_key:
        raise RuntimeError(
            f"{_API_KEY_ENV_VAR} is not set; export your Anthropic API key "
            "before running extraction (this is a passive call — no key, no "
            "extraction)"
        )

    model = os.environ.get(_MODEL_ENV_VAR, _DEFAULT_MODEL)
    user_prompt = _USER_PROMPT_TEMPLATE.format(transcript=transcript)

    try:
        client = Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model,
            max_tokens=4096,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
    except Exception as exc:  # network, auth, rate-limit, etc.
        raise RuntimeError(
            f"Anthropic extraction call failed ({type(exc).__name__}): {exc}. "
            "Check ANTHROPIC_API_KEY validity, network connectivity, and that "
            f"the model id {model!r} is available on your account."
        ) from exc

    # Claude's response is a list of content blocks. For a JSON-only prompt
    # the first text block is what we want.
    try:
        parts = [
            getattr(block, "text", "")
            for block in response.content
            if getattr(block, "type", None) == "text"
        ]
    except Exception as exc:
        raise RuntimeError(f"Anthropic response had unexpected shape: {exc}") from exc
    return "".join(parts).strip()


def _parse_extraction_json(raw: str) -> dict[str, Any]:
    if not raw:
        raise RuntimeError("Anthropic returned empty content for extraction")
    # Defense in depth: some models wrap JSON in ```json fences despite the
    # instruction. Strip a trailing/leading fence if present.
    stripped = raw.strip()
    if stripped.startswith("```"):
        # remove opening fence line and closing fence
        stripped = re.sub(r"^```[a-zA-Z0-9_]*\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Anthropic extraction response was not valid JSON. First 200 chars: {raw[:200]!r}"
        ) from exc
    if not isinstance(parsed, dict):
        raise RuntimeError(
            f"Anthropic extraction response was {type(parsed).__name__}, "
            "expected object; check the system prompt contract"
        )
    return parsed


def _coerce_item(item: Any) -> tuple[str, float] | None:
    """Best-effort coerce one ``{text, importance}`` object.

    Returns ``None`` for malformed items rather than raising; a single rogue
    item should not poison the whole batch.
    """
    if not isinstance(item, dict):
        return None
    text = item.get("text")
    importance = item.get("importance")
    if not isinstance(text, str) or not text.strip():
        return None
    if importance is None:
        return None
    try:
        importance_f = float(importance)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    # Clamp to the documented 1-10 band; anything outside is almost certainly
    # a model hallucination about the scale.
    if importance_f < 1.0 or importance_f > 10.0:
        return None
    return text.strip(), importance_f
