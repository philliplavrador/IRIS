"""
IRIS Daemon — persistent FastAPI server that replaces CLI subprocess spawning.

Instead of spawning `uv run iris ...` for every request (2-5s overhead),
the daemon starts once, pre-loads configs and the op registry, and serves
requests via HTTP. The Node.js Express server calls this daemon's endpoints.
"""
from __future__ import annotations

import matplotlib
matplotlib.use("Agg")  # Non-interactive backend — daemon never needs GUI windows

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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

    yield

    # Cleanup
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
from iris.daemon.routes.projects import router as projects_router  # noqa: E402
from iris.daemon.routes.config import router as config_router  # noqa: E402
from iris.daemon.routes.ops import router as ops_router  # noqa: E402
from iris.daemon.routes.sessions import router as sessions_router  # noqa: E402
from iris.daemon.routes.pipeline import router as pipeline_router  # noqa: E402
from iris.daemon.routes.memory import router as memory_router  # noqa: E402

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
