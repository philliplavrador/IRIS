"""Stub memory routes — Phase 0 of the memory layer rewrite.

The legacy memory modules (knowledge, ledger, recall, digest, conversation,
profile, embeddings, slice_builder, views, tools, archive) have been deleted
as part of the REVAMP.md migration. This module keeps the daemon runnable by
exposing every historical memory endpoint as a 503 stub that points callers
at REVAMP.md. The real endpoints come back online in Phases 1-10.

See ``REVAMP.md`` and ``IRIS Memory Restructure.md`` for the rebuild plan.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter(tags=["memory"])

_STUB_MESSAGE = "memory layer rebuilding — see REVAMP.md"
_STUB_BODY = {"error": _STUB_MESSAGE}


def _stub() -> JSONResponse:
    return JSONResponse(status_code=503, content=_STUB_BODY)


# -- retrieval --------------------------------------------------------------


@router.post("/memory/recall")
async def recall() -> JSONResponse:
    return _stub()


@router.post("/memory/get")
async def memory_get() -> JSONResponse:
    return _stub()


@router.post("/memory/read_conversation")
async def read_conversation() -> JSONResponse:
    return _stub()


@router.post("/memory/append_turn")
async def append_turn() -> JSONResponse:
    return _stub()


@router.post("/memory/read_ledger")
async def read_ledger() -> JSONResponse:
    return _stub()


# -- proposals --------------------------------------------------------------


@router.post("/memory/propose_decision")
async def propose_decision() -> JSONResponse:
    return _stub()


@router.post("/memory/propose_goal")
async def propose_goal() -> JSONResponse:
    return _stub()


@router.post("/memory/propose_fact")
async def propose_fact() -> JSONResponse:
    return _stub()


@router.post("/memory/propose_declined")
async def propose_declined() -> JSONResponse:
    return _stub()


@router.post("/memory/propose_profile_annotation")
async def propose_profile_annotation() -> JSONResponse:
    return _stub()


@router.post("/memory/propose_digest_edit")
async def propose_digest_edit() -> JSONResponse:
    return _stub()


# -- commit -----------------------------------------------------------------


@router.post("/memory/commit_session_writes")
async def commit_session_writes() -> JSONResponse:
    return _stub()


# -- draft digest inspection ------------------------------------------------


@router.get("/memory/draft_digest")
async def get_draft_digest() -> JSONResponse:
    return _stub()


@router.get("/memory/pending")
async def list_pending() -> JSONResponse:
    return _stub()


# -- pinned slice (system-prompt assembly) ----------------------------------


@router.post("/memory/build_slice")
async def build_slice() -> JSONResponse:
    return _stub()


# -- archive / views regeneration -------------------------------------------


@router.post("/memory/rollover")
async def rollover() -> JSONResponse:
    return _stub()


@router.post("/memory/regenerate_views")
async def regenerate_views() -> JSONResponse:
    return _stub()


# -- inspector (L3 listing + mutation) --------------------------------------


@router.get("/memory/list_knowledge")
async def list_knowledge() -> JSONResponse:
    return _stub()


@router.post("/memory/set_status")
async def set_status() -> JSONResponse:
    return _stub()


@router.post("/memory/delete_row")
async def delete_row() -> JSONResponse:
    return _stub()


@router.post("/memory/supersede_fact")
async def supersede_fact() -> JSONResponse:
    return _stub()


@router.post("/memory/discard_pending")
async def discard_pending() -> JSONResponse:
    return _stub()


# -- digest listing ---------------------------------------------------------


@router.get("/memory/list_digests")
async def list_digests() -> JSONResponse:
    return _stub()


@router.post("/memory/replace_draft")
async def replace_draft() -> JSONResponse:
    return _stub()


# -- profile ----------------------------------------------------------------


@router.post("/memory/profile_data")
async def profile_data() -> JSONResponse:
    return _stub()
