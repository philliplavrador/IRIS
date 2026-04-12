"""Project CRUD routes for the CASI daemon."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from casi.daemon.app import get_casi_root

router = APIRouter(tags=["projects"])


class CreateProjectRequest(BaseModel):
    name: str
    description: str | None = None


class RenameProjectRequest(BaseModel):
    old_name: str
    new_name: str


@router.get("/projects")
async def list_projects():
    """List all projects with metadata."""
    from casi.projects import list_projects as _list
    projects = _list(str(get_casi_root()))
    return projects


@router.post("/projects/create")
async def create_project(req: CreateProjectRequest):
    """Create a new project."""
    from casi.projects import create_project
    try:
        create_project(req.name, str(get_casi_root()), description=req.description)
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/projects/open")
async def open_project(req: CreateProjectRequest):
    """Open (activate) a project."""
    from casi.projects import open_project
    try:
        open_project(req.name, str(get_casi_root()))
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/projects/close")
async def close_project():
    """Close the active project."""
    from casi.projects import close_project
    close_project(str(get_casi_root()))
    return {"ok": True}


@router.get("/projects/info")
async def project_info(name: str | None = None):
    """Get project metadata."""
    from casi.projects import project_info
    try:
        info = project_info(name, str(get_casi_root()))
        return {"info": info}
    except Exception as e:
        return {"info": None, "error": str(e)}


@router.post("/projects/rename")
async def rename_project(req: RenameProjectRequest):
    """Rename a project directory."""
    import shutil
    root = get_casi_root() / "projects"
    old = root / req.old_name
    new = root / req.new_name
    if not old.exists():
        raise HTTPException(status_code=404, detail=f"Project '{req.old_name}' not found")
    if new.exists():
        raise HTTPException(status_code=409, detail=f"Project '{req.new_name}' already exists")
    old.rename(new)
    return {"ok": True}


@router.post("/projects/delete")
async def delete_project(req: CreateProjectRequest):
    """Delete a project and all its data."""
    import shutil
    project_dir = get_casi_root() / "projects" / req.name
    if not project_dir.exists():
        raise HTTPException(status_code=404, detail=f"Project '{req.name}' not found")
    shutil.rmtree(project_dir)
    return {"ok": True}
