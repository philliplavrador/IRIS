"""Session routes for the CASI daemon."""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(tags=["sessions"])


class CreateSessionRequest(BaseModel):
    label: str | None = None


@router.get("/sessions")
async def list_sessions():
    """List analysis sessions for the active project."""
    from casi.projects import project_output_dir, resolve_active_project
    from casi.sessions import list_sessions as _list_sessions

    project_path = resolve_active_project()
    if project_path is None:
        return []

    try:
        output_dir = project_output_dir(project_path)
        sessions = _list_sessions(output_root=output_dir)
        return [{"name": s.name, "path": str(s)} for s in sessions]
    except Exception:
        return []


@router.post("/sessions/create")
async def create_session(req: CreateSessionRequest):
    """Create a new analysis session in the active project."""
    from casi.projects import project_output_dir, resolve_active_project
    from casi.sessions import new_session

    project_path = resolve_active_project()
    if project_path is None:
        raise HTTPException(
            status_code=400,
            detail="No active project. Open a project first."
        )

    output_dir = project_output_dir(project_path)
    session_dir = new_session(label=req.label, output_root=output_dir)
    return {"ok": True, "session_name": session_dir.name, "path": str(session_dir)}


@router.get("/sessions/{name}")
async def get_session(name: str):
    """Get session details including manifest."""
    from casi.projects import project_output_dir, resolve_active_project

    project_path = resolve_active_project()
    if project_path is None:
        raise HTTPException(status_code=400, detail="No active project.")

    output_dir = project_output_dir(project_path)
    session_dir = output_dir / name
    if not session_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"Session '{name}' not found")

    manifest_path = session_dir / "manifest.json"
    manifest = None
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    # List plot files in session
    plots = sorted(
        [f.name for f in session_dir.iterdir() if f.suffix in (".png", ".pdf", ".svg")],
    )

    return {
        "name": name,
        "path": str(session_dir),
        "manifest": manifest,
        "plots": plots,
    }
