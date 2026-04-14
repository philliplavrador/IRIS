"""
IRIS Daemon — persistent FastAPI server that replaces CLI subprocess spawning.

Instead of spawning `uv run iris ...` for every request (2-5s overhead),
the daemon starts once, pre-loads configs and the op registry, and serves
requests via HTTP. The Node.js Express server calls this daemon's endpoints.
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")  # Non-interactive backend — daemon never needs GUI windows

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

logger = logging.getLogger("iris.daemon")

_HARDCODED_OP_VERSION = "1.0.0"

# Module-level state — populated on startup
_config = None
_registry = None
_source_loaders = None
_iris_root: Path | None = None


def get_config():
    assert _config is not None, "Daemon not initialized"
    return _config


def get_iris_root() -> Path:
    if _iris_root is not None:
        return _iris_root
    return Path(os.environ.get("IRIS_ROOT", Path(__file__).resolve().parents[3]))


def catalog_hardcoded_ops(project_path: Path) -> int:
    """Register the 17 hardcoded ops into ``<project>/iris.sqlite``.

    Idempotent on ``(name, version)``: every op is pre-looked-up via
    :func:`operations_store.find` and skipped if already catalogued. Returns
    the number of ops *newly* registered on this call.

    Registrations are global (``project_id=None``) so the same catalog row
    serves every project that shares this SQLite file, matches the REVAMP
    spec, and sidesteps the ``projects`` FK (no project row is inserted by
    ``create_project`` today).
    """
    if _registry is None:
        return 0

    from iris.engine.type_system import TYPE_TRANSITIONS
    from iris.projects import db as projects_db
    from iris.projects import operations_store

    conn = projects_db.connect(project_path)
    try:
        projects_db.init_schema(conn)
        newly = 0
        for name in sorted(_registry._handlers.keys()):
            existing = operations_store.find(
                conn,
                project_id=None,
                name=name,
                version=_HARDCODED_OP_VERSION,
            )
            if existing is not None:
                continue
            handler = _registry._handlers[name]
            transitions = TYPE_TRANSITIONS.get(name, {})
            signature = {
                "kind": "hardcoded",
                "transitions": [
                    {"input": in_t.__name__, "output": out_t.__name__}
                    for in_t, out_t in transitions.items()
                ],
            }
            docstring = (handler.__doc__ or "").strip() or f"Hardcoded op '{name}'."
            operations_store.register(
                conn,
                project_id=None,
                name=name,
                version=_HARDCODED_OP_VERSION,
                kind="hardcoded",
                signature_json=signature,
                docstring=docstring,
                source_code=None,
            )
            logger.info("cataloged hardcoded op %s@%s", name, _HARDCODED_OP_VERSION)
            newly += 1
        return newly
    finally:
        conn.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _config, _registry, _source_loaders, _iris_root

    _iris_root = Path(os.environ.get("IRIS_ROOT", Path(__file__).resolve().parents[3]))

    from iris.config import load_configs

    _config = load_configs(str(_iris_root / "configs"))

    from iris.engine import create_registry

    plot_backend = _config.globals.get("plot_backend", "matplotlib")
    _registry, _source_loaders = create_registry(plot_backend=plot_backend)

    print(f"[iris-daemon] Config loaded from {_iris_root / 'configs'}")
    print(f"[iris-daemon] Registry ready, plot_backend={plot_backend}")

    # Start the markdown watcher for the active project (if any). Failures
    # must not block daemon startup — we log and continue.
    app.state.markdown_observer = None
    try:
        from iris.daemon.services.markdown_watcher import start_watcher
        from iris.projects import resolve_active_project

        active = resolve_active_project()
        if active is not None:
            app.state.markdown_observer = start_watcher(active)
            try:
                catalog_hardcoded_ops(active)
            except Exception as e:  # pragma: no cover — defensive
                print(f"[iris-daemon] catalog_hardcoded_ops failed: {e}")
    except Exception as e:  # pragma: no cover — defensive
        print(f"[iris-daemon] markdown_watcher startup failed: {e}")

    yield

    # Cleanup
    try:
        from iris.daemon.services.markdown_watcher import stop_watcher

        stop_watcher(getattr(app.state, "markdown_observer", None))
    except Exception as e:  # pragma: no cover
        print(f"[iris-daemon] markdown_watcher shutdown failed: {e}")
    _config = None
    _registry = None
    _source_loaders = None


app = FastAPI(title="IRIS Daemon", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register route modules
from iris.daemon.routes.config import router as config_router  # noqa: E402
from iris.daemon.routes.memory import router as memory_router  # noqa: E402
from iris.daemon.routes.ops import router as ops_router  # noqa: E402
from iris.daemon.routes.pipeline import router as pipeline_router  # noqa: E402
from iris.daemon.routes.projects import router as projects_router  # noqa: E402
from iris.daemon.routes.sessions import router as sessions_router  # noqa: E402

app.include_router(projects_router, prefix="/api")
app.include_router(config_router, prefix="/api")
app.include_router(ops_router, prefix="/api")
app.include_router(sessions_router, prefix="/api")
app.include_router(pipeline_router, prefix="/api")
app.include_router(memory_router, prefix="/api")


@app.get("/health")
async def health():
    return {"status": "ok", "config_loaded": _config is not None}


def run():
    """Entry point for `iris-daemon` CLI command."""
    import uvicorn

    port = int(os.environ.get("IRIS_DAEMON_PORT", "4002"))
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")


if __name__ == "__main__":
    run()
