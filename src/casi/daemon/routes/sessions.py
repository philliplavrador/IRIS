"""Session listing routes for the CASI daemon."""
from __future__ import annotations

from fastapi import APIRouter

from casi.daemon.app import get_casi_root

router = APIRouter(tags=["sessions"])


@router.get("/sessions")
async def list_sessions():
    """List analysis sessions for the active project."""
    from casi.sessions import list_sessions
    try:
        sessions = list_sessions(str(get_casi_root()))
        return sessions
    except Exception:
        return []
