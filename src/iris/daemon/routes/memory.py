"""Daemon endpoints for the IRIS memory tool surface (Phase 3).

Exposes the tools listed in docs/iris-behavior.md §12 as HTTP endpoints so
the Express backend (or any HTTP client) can drive them. All endpoints
resolve a project path via the ``?project=<name>`` query param, falling
back to the active project.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from iris.daemon.app import get_iris_root
from iris.projects import tools as _tools

router = APIRouter(tags=["memory"])


def _resolve(project: Optional[str]) -> Path:
    if project:
        p = get_iris_root() / "projects" / project
        if not p.is_dir():
            raise HTTPException(404, f"Project '{project}' not found")
        return p
    from iris.projects import resolve_active_project

    p = resolve_active_project()
    if p is None:
        raise HTTPException(400, "No active project and no `project` param.")
    return p


# -- retrieval --------------------------------------------------------------


class RecallRequest(BaseModel):
    query: str
    k: int = 5
    filters: dict | None = None
    halflife_days: float = 30.0
    project: str | None = None


@router.post("/memory/recall")
async def recall(req: RecallRequest):
    path = _resolve(req.project)
    hits = _tools.recall(
        path, req.query, k=req.k, filters=req.filters, halflife_days=req.halflife_days
    )
    return {"hits": hits}


class GetRequest(BaseModel):
    source: str
    id: int
    project: str | None = None


@router.post("/memory/get")
async def memory_get(req: GetRequest):
    path = _resolve(req.project)
    try:
        row = _tools.get(path, req.source, req.id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"row": row}


class ReadConversationRequest(BaseModel):
    session_id: str
    turn_range: str | None = None
    project: str | None = None


@router.post("/memory/read_conversation")
async def read_conversation(req: ReadConversationRequest):
    path = _resolve(req.project)
    return {"turns": _tools.read_conversation(path, req.session_id, req.turn_range)}


class AppendTurnRequest(BaseModel):
    session_id: str
    role: str
    text: str
    tool_calls: list | None = None
    tool_results: list | None = None
    timestamp: str | None = None
    project: str | None = None


@router.post("/memory/append_turn")
async def append_turn(req: AppendTurnRequest):
    """L0 append — never gated. Called per-turn by the agent bridge (§3.1)."""
    path = _resolve(req.project)
    try:
        idx = _tools.record_turn(
            path,
            req.session_id,
            req.role,
            req.text,
            tool_calls=req.tool_calls,
            tool_results=req.tool_results,
            timestamp=req.timestamp,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"turn_index": idx}


class ReadLedgerRequest(BaseModel):
    table: str
    filters: dict | None = None
    limit: int = 100
    project: str | None = None


@router.post("/memory/read_ledger")
async def read_ledger(req: ReadLedgerRequest):
    path = _resolve(req.project)
    try:
        rows = _tools.read_ledger(path, req.table, req.filters, req.limit)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"rows": rows}


# -- proposals --------------------------------------------------------------


class ProposeDecisionRequest(BaseModel):
    session_id: str
    text: str
    rationale: str | None = None
    supersedes: int | None = None
    tags: list[str] | None = None
    project: str | None = None


@router.post("/memory/propose_decision")
async def propose_decision(req: ProposeDecisionRequest):
    path = _resolve(req.project)
    pid = _tools.propose_decision(
        path,
        req.session_id,
        req.text,
        rationale=req.rationale,
        supersedes=req.supersedes,
        tags=req.tags,
    )
    return {"pending_id": pid}


class ProposeGoalRequest(BaseModel):
    session_id: str
    text: str
    project: str | None = None


@router.post("/memory/propose_goal")
async def propose_goal(req: ProposeGoalRequest):
    path = _resolve(req.project)
    return {"pending_id": _tools.propose_goal(path, req.session_id, req.text)}


class ProposeFactRequest(BaseModel):
    session_id: str
    key: str
    value: str
    confidence: float | None = None
    project: str | None = None


@router.post("/memory/propose_fact")
async def propose_fact(req: ProposeFactRequest):
    path = _resolve(req.project)
    return {
        "pending_id": _tools.propose_fact(
            path, req.session_id, req.key, req.value, confidence=req.confidence
        )
    }


class ProposeDeclinedRequest(BaseModel):
    session_id: str
    text: str
    project: str | None = None


@router.post("/memory/propose_declined")
async def propose_declined(req: ProposeDeclinedRequest):
    path = _resolve(req.project)
    return {"pending_id": _tools.propose_declined(path, req.session_id, req.text)}


class ProposeAnnotationRequest(BaseModel):
    session_id: str
    field_path: str
    annotation: str
    project: str | None = None


@router.post("/memory/propose_profile_annotation")
async def propose_profile_annotation(req: ProposeAnnotationRequest):
    path = _resolve(req.project)
    return {
        "pending_id": _tools.propose_profile_annotation(
            path, req.session_id, req.field_path, req.annotation
        )
    }


class ProposeDigestEditRequest(BaseModel):
    session_id: str
    patch: dict
    project: str | None = None


@router.post("/memory/propose_digest_edit")
async def propose_digest_edit(req: ProposeDigestEditRequest):
    path = _resolve(req.project)
    try:
        state = _tools.propose_digest_edit(path, req.session_id, req.patch)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"digest": state}


# -- commit -----------------------------------------------------------------


class CommitRequest(BaseModel):
    session_id: str
    approve_ids: list[int] | None = None
    finalize_digest: bool = True
    regenerate_views: bool = True
    project: str | None = None


@router.post("/memory/commit_session_writes")
async def commit_session_writes(req: CommitRequest):
    path = _resolve(req.project)
    return _tools.commit_session_writes(
        path,
        req.session_id,
        approve_ids=req.approve_ids,
        finalize_digest=req.finalize_digest,
        regenerate_views=req.regenerate_views,
    )


# -- draft digest inspection ------------------------------------------------


@router.get("/memory/draft_digest")
async def get_draft_digest(session_id: str, project: str | None = None):
    path = _resolve(project)
    return _tools.draft_digest(path, session_id)


@router.get("/memory/pending")
async def list_pending(session_id: str | None = None, project: str | None = None):
    from iris.projects import knowledge as _knowledge

    path = _resolve(project)
    return {"pending": _knowledge.list_pending(path, session_id)}


# -- pinned slice (system-prompt assembly) ----------------------------------


class BuildSliceRequest(BaseModel):
    budget_tokens: int | None = None
    goals_max: int | None = None
    project: str | None = None


@router.post("/memory/build_slice")
async def build_slice(req: BuildSliceRequest):
    from iris.projects import slice_builder as _sb

    path = _resolve(req.project)
    # Defaults from the project's claude_config.yaml memory block.
    from iris.projects import get_project_config

    cfg = get_project_config(path).get("memory") or {}
    budget = req.budget_tokens or cfg.get("pin_budget_tokens", _sb.DEFAULT_BUDGET_TOKENS)
    goals = req.goals_max or cfg.get("goals_active_max", _sb.DEFAULT_GOALS_MAX)
    sl, rendered = _sb.build_and_cache(
        path, budget_tokens=budget, goals_max=goals
    )
    return {
        "rendered": rendered,
        "used_tokens": sl.used_tokens,
        "budget": sl.budget,
        "dropped_sections": sl.dropped_sections,
        "entries": len(sl.entries),
    }


# -- archive / views regeneration -------------------------------------------


class RolloverRequest(BaseModel):
    retention_days: int = 90
    project: str | None = None


@router.post("/memory/rollover")
async def rollover(req: RolloverRequest):
    from iris.projects import archive as _archive

    path = _resolve(req.project)
    return _archive.rollup_old_digests(path, retention_days=req.retention_days)


@router.post("/memory/regenerate_views")
async def regenerate_views(project: str | None = None):
    from iris.projects import views as _views

    path = _resolve(project)
    paths = _views.regenerate_all(path)
    return {"views": [str(p) for p in paths]}


# -- inspector (L3 listing + mutation) --------------------------------------


@router.get("/memory/list_knowledge")
async def list_knowledge(
    table: str,
    status: str | None = None,
    limit: int = 200,
    project: str | None = None,
):
    from iris.projects import knowledge as _knowledge

    path = _resolve(project)
    try:
        rows = _knowledge.list_table(path, table, status=status, limit=limit)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"rows": rows}


class SetStatusRequest(BaseModel):
    table: str  # goals | decisions
    id: int
    status: str  # active | done | superseded | abandoned
    project: str | None = None


@router.post("/memory/set_status")
async def set_status(req: SetStatusRequest):
    from iris.projects import knowledge as _knowledge

    path = _resolve(req.project)
    try:
        _knowledge.set_status(path, req.table, req.id, req.status)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


class DeleteRowRequest(BaseModel):
    table: str  # learned_facts | declined_suggestions | data_profile_fields
    id: int
    project: str | None = None


@router.post("/memory/delete_row")
async def delete_row(req: DeleteRowRequest):
    from iris.projects import knowledge as _knowledge

    path = _resolve(req.project)
    try:
        n = _knowledge.delete_row(path, req.table, req.id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"deleted": n}


class SupersedeFactRequest(BaseModel):
    old_id: int
    key: str
    value: str
    session_id: str
    project: str | None = None


@router.post("/memory/supersede_fact")
async def supersede_fact(req: SupersedeFactRequest):
    from iris.projects import knowledge as _knowledge

    path = _resolve(req.project)
    new_id = _knowledge.supersede_fact(
        path, req.old_id, req.key, req.value, req.session_id
    )
    return {"new_id": new_id}


class DiscardPendingRequest(BaseModel):
    ids: list[int]
    project: str | None = None


@router.post("/memory/discard_pending")
async def discard_pending(req: DiscardPendingRequest):
    from iris.projects import knowledge as _knowledge

    path = _resolve(req.project)
    return {"deleted": _knowledge.discard_pending(path, req.ids)}


# -- digest listing ---------------------------------------------------------


@router.get("/memory/list_digests")
async def list_digests(project: str | None = None):
    from iris.projects import digest as _digest

    path = _resolve(project)
    drafts = [p.name.replace(_digest.DRAFT_SUFFIX, "") for p in _digest.list_drafts(path)]
    finals = [p.name.replace(_digest.FINAL_SUFFIX, "") for p in _digest.list_finals(path)]
    return {"drafts": drafts, "finals": finals}


class ReplaceDraftRequest(BaseModel):
    session_id: str
    digest: dict
    project: str | None = None


@router.post("/memory/replace_draft")
async def replace_draft(req: ReplaceDraftRequest):
    from iris.projects import digest as _digest

    path = _resolve(req.project)
    try:
        state = _digest.replace_draft(path, req.session_id, req.digest)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"digest": state}


# -- profile ----------------------------------------------------------------


class ProfileRequest(BaseModel):
    file_path: str
    project: str | None = None


@router.post("/memory/profile_data")
async def profile_data(req: ProfileRequest):
    """Domain-agnostic profile of an uploaded file. Stages unconfirmed
    annotations in ``data_profile_fields``; UI turns them into
    user-confirmed proposals."""
    from iris.projects import profile as _profile

    path = _resolve(req.project)
    try:
        result = _profile.profile_data(req.file_path, project_path=path)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    return {"profile": result}
