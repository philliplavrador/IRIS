"""Agent tool layer — the functions IRIS calls during a session.

Thin dispatch surface over L0/L1/L2/L3/L4. All functions take a
``project_path`` explicitly so the tool layer is testable in isolation
from the active-project pointer.

Mapping to the plan §12 tool surface:

Retrieval:
  recall          — hybrid BM25+vector+recency retrieval
  get             — direct fetch by table+id
  read_conversation — L0 access
  read_ledger     — L1 structured query

Proposals (queue into pending_writes, flushed at session-end):
  propose_decision, propose_goal, propose_fact, propose_declined,
  propose_profile_annotation, propose_digest_edit

Commit:
  commit_session_writes — atomic flush of pending + finalize digest
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from . import conversation as _conv
from . import digest as _digest
from . import knowledge as _knowledge
from . import ledger as _ledger
from . import recall as _recall
from . import views as _views


# -- retrieval --------------------------------------------------------------


def recall(
    project_path: Path,
    query: str,
    k: int = 5,
    filters: Optional[dict] = None,
    halflife_days: float = 30.0,
) -> list[dict]:
    hits = _recall.recall(
        project_path, query, k=k, filters=filters, halflife_days=halflife_days
    )
    return [hit.__dict__ for hit in hits]


def get(project_path: Path, source: str, row_id: int) -> Optional[dict]:
    """Resolve a citation back to its row. ``source`` ∈ {goal, decision, fact,
    declined_suggestion, data_profile_field}."""
    table_map = {
        "goal": "goals",
        "decision": "decisions",
        "fact": "learned_facts",
        "declined_suggestion": "declined_suggestions",
        "data_profile_field": "data_profile_fields",
    }
    if source not in table_map:
        raise ValueError(f"unknown citation source {source!r}")
    return _knowledge.get(project_path, table_map[source], row_id)


def read_conversation(
    project_path: Path,
    session_id: str,
    turn_range: Optional[str] = None,
) -> list[dict]:
    return _conv.read_conversation(project_path, session_id, turn_range)


def read_ledger(
    project_path: Path,
    table: str,
    filters: Optional[dict] = None,
    limit: int = 100,
) -> list[dict]:
    return _ledger.read_ledger(project_path, table, filters, limit)


# -- proposals --------------------------------------------------------------


def propose_decision(
    project_path: Path,
    session_id: str,
    text: str,
    *,
    rationale: Optional[str] = None,
    supersedes: Optional[int] = None,
    tags: Optional[list] = None,
) -> int:
    return _knowledge.propose(
        project_path,
        "decision",
        {
            "text": text,
            "rationale": rationale,
            "supersedes": supersedes,
            "tags": list(tags) if tags else [],
        },
        session_id,
    )


def propose_goal(project_path: Path, session_id: str, text: str) -> int:
    return _knowledge.propose(project_path, "goal", {"text": text}, session_id)


def propose_fact(
    project_path: Path,
    session_id: str,
    key: str,
    value: str,
    *,
    confidence: Optional[float] = None,
) -> int:
    return _knowledge.propose(
        project_path,
        "fact",
        {"key": key, "value": value, "confidence": confidence},
        session_id,
    )


def propose_declined(project_path: Path, session_id: str, text: str) -> int:
    return _knowledge.propose(
        project_path, "declined", {"text": text}, session_id
    )


def propose_profile_annotation(
    project_path: Path,
    session_id: str,
    field_path: str,
    annotation: str,
) -> int:
    return _knowledge.propose(
        project_path,
        "profile_annotation",
        {"field_path": field_path, "annotation": annotation},
        session_id,
    )


def propose_digest_edit(
    project_path: Path, session_id: str, patch: dict
) -> dict:
    """Apply a patch to the session's draft digest. Returns the new state."""
    return _digest.update_draft(project_path, session_id, patch)


# -- commit -----------------------------------------------------------------


def commit_session_writes(
    project_path: Path,
    session_id: str,
    *,
    approve_ids: Optional[list[int]] = None,
    finalize_digest: bool = True,
    regenerate_views: bool = True,
) -> dict:
    """Atomic session-end flush.

    Steps: commit pending L3 rows → (optionally) promote draft digest to
    final → (optionally) regenerate markdown views → return report.

    The knowledge commit is SQLite-atomic internally. Digest finalization
    is file-atomic. A failure in views regeneration does not roll back.
    """
    report = _knowledge.commit_pending(
        project_path, session_id, approve_ids=approve_ids
    )
    finalized: Optional[str] = None
    if finalize_digest:
        draft = _digest.draft_path(project_path, session_id)
        if draft.is_file():
            finalized = str(_digest.finalize(project_path, session_id))
    views_out: list[str] = []
    if regenerate_views:
        for p in _views.regenerate_all(project_path):
            views_out.append(str(p))
    return {
        "committed": report["committed"],
        "by_kind": report["by_kind"],
        "finalized_digest": finalized,
        "views": views_out,
    }


# -- session bookkeeping ----------------------------------------------------


def draft_digest(project_path: Path, session_id: str) -> dict:
    return _digest.get_or_create_draft(project_path, session_id)


def record_turn(
    project_path: Path,
    session_id: str,
    role: str,
    text: str,
    **kwargs,
) -> int:
    """L0 append — called automatically on every turn by the agent bridge."""
    return _conv.append_turn(project_path, session_id, role, text, **kwargs)
