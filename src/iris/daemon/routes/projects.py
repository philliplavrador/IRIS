"""Project lifecycle routes for the IRIS daemon.

Canonical endpoint shape (REVAMP Task 1.9):

- ``GET  /projects``              — list all projects.
- ``POST /projects``              — create (body ``{"name": "...", ...}``).
- ``GET  /projects/active``       — return the active project (or ``null``).
- ``POST /projects/active``       — set the active project (body ``{"name": "..."}``).
- ``GET  /projects/{name}``       — open/activate and return metadata.
- ``DELETE /projects/{name}``     — delete a project workspace.

Supporting endpoints kept in place until later REVAMP tasks replace their
callers:

- ``GET  /projects/find-plot``    — plot dedup lookup (engine/pipeline flow).
- ``POST /projects/rename``       — rename (retained for CLI/frontend parity).

All handlers delegate to the rebuilt :mod:`iris.projects` package; nothing
here owns domain logic.
"""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(tags=["projects"])


# -- request bodies ---------------------------------------------------------


class CreateProjectRequest(BaseModel):
    name: str
    description: str | None = None


class SetActiveRequest(BaseModel):
    name: str


class RenameProjectRequest(BaseModel):
    old_name: str
    new_name: str


# -- helpers ----------------------------------------------------------------


def _project_info_dict(name: str) -> dict:
    """Return the describe-project payload for ``name``.

    Raises ``HTTPException(404)`` if the project does not exist.
    """
    from iris.projects import _describe_project, get_project_config, project_root

    path = project_root() / name
    if not path.is_dir():
        raise HTTPException(status_code=404, detail=f"Project '{name}' not found")
    info = asdict(_describe_project(path))
    cfg = get_project_config(name)
    if cfg.get("agent_notes"):
        info["agent_notes"] = cfg["agent_notes"]
    return info


# -- canonical endpoints ----------------------------------------------------


@router.get("/projects")
async def list_projects():
    """List all projects (TEMPLATE excluded)."""
    from iris.projects import list_projects as _list

    return [asdict(info) for info in _list()]


@router.post("/projects")
async def create_project(req: CreateProjectRequest):
    """Create a new project workspace from TEMPLATE."""
    from iris.projects import create_project as _create

    try:
        _create(req.name, description=req.description)
    except FileExistsError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return _project_info_dict(req.name)


@router.get("/projects/active")
async def get_active_project():
    """Return the active project metadata, or ``{"active": null}`` if none."""
    from iris.projects import resolve_active_project

    active = resolve_active_project()
    if active is None:
        return {"active": None}
    return {"active": _project_info_dict(active.name)}


@router.post("/projects/active")
async def set_active_project(req: SetActiveRequest):
    """Mark ``name`` as the active project."""
    from iris.projects import set_active_project as _set

    try:
        path = _set(req.name)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    # Lazy-catalog the 17 hardcoded ops into this project's iris.sqlite on
    # first activation (Task 8.2). Idempotent via (name, version) dedupe.
    try:
        from iris.daemon.app import catalog_hardcoded_ops

        catalog_hardcoded_ops(path)
    except Exception as e:  # pragma: no cover — defensive
        print(f"[iris-daemon] catalog_hardcoded_ops failed: {e}")
    return {"active": _project_info_dict(req.name)}


# Non-canonical supporting endpoints. Declared before ``/projects/{name}``
# so FastAPI's path matcher doesn't route e.g. ``/projects/find-plot`` to the
# dynamic-segment handler.


@router.get("/projects/find-plot")
async def find_plot(dsl: str, window: str = "full"):
    """Search for cached plots matching a DSL + window in the active project."""
    from iris.daemon.app import _config
    from iris.projects import find_cached_plots, resolve_active_project

    project_path = resolve_active_project()
    if project_path is None:
        raise HTTPException(status_code=400, detail="No active project.")

    if window == "full":
        window_ms: str | list[float] = "full"
    else:
        try:
            parts = [float(x.strip()) for x in window.split(",")]
            if len(parts) != 2:
                raise ValueError
            window_ms = parts
        except (ValueError, AttributeError) as e:
            raise HTTPException(status_code=400, detail=f"Invalid window: '{window}'") from e

    paths_cfg = _config.get("paths", {}) if _config else {}
    matches = find_cached_plots(project_path, dsl, paths_cfg, window_ms)
    return [{"plot_path": str(m.plot_path), "sidecar_path": str(m.sidecar_path)} for m in matches]


@router.post("/projects/rename")
async def rename_project(req: RenameProjectRequest):
    """Rename a project directory.

    Retained for CLI/frontend parity; not part of the canonical six. Uses the
    FS directly because the rebuilt :mod:`iris.projects` does not (yet)
    expose a rename helper.
    """
    from iris.projects import project_root

    root = project_root()
    old = root / req.old_name
    new = root / req.new_name
    if not old.exists():
        raise HTTPException(status_code=404, detail=f"Project '{req.old_name}' not found")
    if new.exists():
        raise HTTPException(status_code=409, detail=f"Project '{req.new_name}' already exists")
    old.rename(new)
    return {"ok": True}


# Dynamic-segment endpoints last so they don't shadow the static routes above.


@router.get("/projects/{name}")
async def open_project(name: str):
    """Open (activate) a project and return its metadata."""
    from iris.projects import open_project as _open

    try:
        _open(name)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return _project_info_dict(name)


@router.delete("/projects/{name}")
async def delete_project(name: str):
    """Delete a project and all its data."""
    from iris.projects import delete_project as _delete

    try:
        _delete(name)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"ok": True, "name": name}
