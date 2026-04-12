"""Project CRUD routes for the IRIS daemon."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from iris.daemon.app import get_iris_root

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
    from iris.projects import list_projects as _list
    projects = _list(str(get_iris_root()))
    return projects


@router.post("/projects/create")
async def create_project(req: CreateProjectRequest):
    """Create a new project."""
    from iris.projects import create_project
    try:
        create_project(req.name, str(get_iris_root()), description=req.description)
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/projects/open")
async def open_project(req: CreateProjectRequest):
    """Open (activate) a project."""
    from iris.projects import open_project
    try:
        open_project(req.name, str(get_iris_root()))
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/projects/close")
async def close_project():
    """Close the active project."""
    from iris.projects import close_project
    close_project(str(get_iris_root()))
    return {"ok": True}


@router.get("/projects/info")
async def project_info(name: str | None = None):
    """Get project metadata."""
    from iris.projects import project_info
    try:
        info = project_info(name, str(get_iris_root()))
        return {"info": info}
    except Exception as e:
        return {"info": None, "error": str(e)}


@router.post("/projects/rename")
async def rename_project(req: RenameProjectRequest):
    """Rename a project directory."""
    import shutil
    root = get_iris_root() / "projects"
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
    project_dir = get_iris_root() / "projects" / req.name
    if not project_dir.exists():
        raise HTTPException(status_code=404, detail=f"Project '{req.name}' not found")
    shutil.rmtree(project_dir)
    return {"ok": True}


class HistoryAddRequest(BaseModel):
    section: str
    bullets: list[str]
    project: str | None = None


class FindPlotRequest(BaseModel):
    dsl: str
    window: str = "full"


@router.post("/projects/history/add")
async def add_history(req: HistoryAddRequest):
    """Append bullets to a section of the project's claude_history.md."""
    from iris.projects import append_history, resolve_active_project

    if req.project:
        project_path = get_iris_root() / "projects" / req.project
        if not project_path.is_dir():
            raise HTTPException(status_code=404, detail=f"Project '{req.project}' not found")
    else:
        project_path = resolve_active_project()
        if project_path is None:
            raise HTTPException(status_code=400, detail="No active project.")

    try:
        append_history(project_path, req.section, req.bullets)
        return {"ok": True}
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/projects/find-plot")
async def find_plot(dsl: str, window: str = "full"):
    """Search for cached plots matching a DSL + window in the active project."""
    from iris.daemon.app import _config
    from iris.projects import find_cached_plots, resolve_active_project

    project_path = resolve_active_project()
    if project_path is None:
        raise HTTPException(status_code=400, detail="No active project.")

    # Parse window
    if window == "full":
        window_ms = "full"
    else:
        try:
            parts = [float(x.strip()) for x in window.split(",")]
            if len(parts) != 2:
                raise ValueError
            window_ms = parts
        except (ValueError, AttributeError):
            raise HTTPException(status_code=400, detail=f"Invalid window: '{window}'")

    paths_cfg = _config.get("paths", {}) if _config else {}
    matches = find_cached_plots(project_path, dsl, paths_cfg, window_ms)
    return [
        {"plot_path": str(m.plot_path), "sidecar_path": str(m.sidecar_path)}
        for m in matches
    ]
