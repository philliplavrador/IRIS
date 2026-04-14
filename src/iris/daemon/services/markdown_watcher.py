"""Filesystem watcher that ingests user edits to ``memory/*.md`` back into SQLite.

Task 4.6 (REVAMP Phase 4). Pairs with
:mod:`iris.projects.markdown_sync`: when the DB mutates, the memory-layer
writes call ``regenerate_markdown``; when the **user** edits the Markdown by
hand, this watcher notices and calls ``ingest_markdown`` to turn those edits
into *draft* memory proposals. The curation UI is still the only path from
draft → ``status='active'``.

Design notes
------------
* We use :mod:`watchdog` because it already ships cross-platform observers and
  event debouncing hooks; vendoring our own poll loop was rejected in the
  Phase 4 design doc.
* A single observer per project path is enough — ``ingest_markdown`` rescans
  the whole ``memory/`` tree every call, so fine-grained per-file event
  dispatch would just duplicate work.
* Debouncing: editors (VS Code, vim, obsidian) routinely emit several events
  per save (temp-file swap, rename, final write). We collapse bursts with a
  ``threading.Timer`` that fires ~2 s after the last event, on a background
  thread.
* Failures in ``ingest_markdown`` must not kill the observer thread — we log
  and continue. The observer outlives every sync attempt.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from iris.projects import db as _db
from iris.projects import markdown_sync as _markdown_sync

if TYPE_CHECKING:
    from watchdog.events import FileSystemEvent
    from watchdog.observers.api import BaseObserver

logger = logging.getLogger(__name__)

_DEBOUNCE_SECONDS = 2.0


class _MarkdownChangeHandler(FileSystemEventHandler):
    """Debounced handler that funnels every change into ``ingest_markdown``."""

    def __init__(self, project_path: Path) -> None:
        super().__init__()
        self._project_path = project_path
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()

    # All four on_* hooks route through the same debounced scheduler; we don't
    # care which file changed — ingest_markdown walks memory/ in full anyway.
    def on_any_event(self, event: FileSystemEvent) -> None:  # type: ignore[override]
        # Ignore directory events and non-.md files to keep the trigger rate sane.
        if event.is_directory:
            return
        src = str(getattr(event, "src_path", "") or "")
        dest = str(getattr(event, "dest_path", "") or "")
        if not (src.endswith(".md") or dest.endswith(".md")):
            return
        self._schedule()

    def _schedule(self) -> None:
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(_DEBOUNCE_SECONDS, self._run_sync)
            self._timer.daemon = True
            self._timer.start()

    def _run_sync(self) -> None:
        try:
            conn = _db.connect(self._project_path)
            try:
                _db.init_schema(conn)
                _markdown_sync.ingest_markdown(conn, self._project_path)
            finally:
                conn.close()
        except Exception:  # pragma: no cover — defensive, keep observer alive
            logger.exception(
                "markdown_watcher: ingest_markdown failed for %s",
                self._project_path,
            )

    def cancel_pending(self) -> None:
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None


def start_watcher(project_path: Path) -> BaseObserver:
    """Start a watchdog observer on ``<project_path>/memory/`` and return it.

    Raises ``FileNotFoundError`` if ``memory/`` does not exist — callers (the
    daemon lifespan) should catch and log rather than abort startup.
    """
    memory_dir = project_path / "memory"
    if not memory_dir.exists():
        raise FileNotFoundError(f"memory/ dir missing: {memory_dir}")
    handler = _MarkdownChangeHandler(project_path)
    observer: BaseObserver = Observer()
    observer.schedule(handler, str(memory_dir), recursive=True)
    observer.daemon = True
    observer.start()
    # Stash the handler so stop_watcher can cancel pending timers.
    observer._iris_handler = handler  # type: ignore[attr-defined]
    logger.info("markdown_watcher: watching %s", memory_dir)
    return observer


def stop_watcher(observer: BaseObserver | None) -> None:
    """Stop and join a running observer. Safe to call with ``None``."""
    if observer is None:
        return
    handler = getattr(observer, "_iris_handler", None)
    if isinstance(handler, _MarkdownChangeHandler):
        handler.cancel_pending()
    try:
        observer.stop()
        observer.join(timeout=5.0)
    except Exception:  # pragma: no cover
        logger.exception("markdown_watcher: stop failed")
