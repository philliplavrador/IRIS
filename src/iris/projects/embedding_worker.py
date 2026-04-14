"""Background embedding worker (REVAMP Task 11.4, spec §14.2).

Drains a simple in-process queue of ``(kind, project_path, entity_id,
text)`` jobs, computes embeddings with a pluggable
:class:`iris.projects.embeddings.EmbeddingProvider`, and writes the
resulting vectors into the V2 ``memory_entries_vec`` or
``operations_vec`` virtual tables.

Design
------
The worker runs in a daemon thread; the main process doesn't wait on it
at shutdown — the queue is drained best-effort. This keeps the memory
hot path (``memory_entries.commit_pending`` / ``operations.register``)
fast and failure-tolerant: if no worker is started, :func:`enqueue` is a
no-op, so V1 code paths that call into ``memory_entries`` keep working
with zero behavioral change.

Public API
----------
- :func:`enqueue` — called from memory_entries/operations_store when a
  row lands. No-op if no worker is active.
- :func:`start_worker` — spin up the thread. Safe to call multiple times
  (later calls no-op).
- :func:`stop_worker` — signal drain + join (used by tests).
- :func:`drain_sync` — single-threaded drain for tests/CLIs.
"""

from __future__ import annotations

import logging
import queue
import sqlite3
import struct
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from iris.projects import db as db_mod
from iris.projects.embeddings import EmbeddingProvider

__all__ = [
    "EmbedJob",
    "JobKind",
    "drain_sync",
    "enqueue",
    "start_worker",
    "stop_worker",
]

_log = logging.getLogger(__name__)

JobKind = Literal["memory_entry", "operation"]


@dataclass(frozen=True)
class EmbedJob:
    """A single work item. ``entity_id`` is ``memory_id`` or ``op_id``."""

    kind: JobKind
    project_path: Path
    entity_id: str
    text: str


_QUEUE: Final[queue.Queue[EmbedJob | None]] = queue.Queue()
_WORKER_LOCK: Final[threading.Lock] = threading.Lock()
_WORKER_THREAD: threading.Thread | None = None
_PROVIDER: EmbeddingProvider | None = None
_ACTIVE: bool = False


def enqueue(job: EmbedJob) -> None:
    """Best-effort append. Silent no-op if no worker is running.

    This keeps the memory hot path zero-risk: callers can always invoke
    ``enqueue(...)`` without first checking whether V2 is in effect.
    """
    if not _ACTIVE:
        return
    _QUEUE.put(job)


def _pack_vector(vec: list[float]) -> bytes:
    """Pack a float vector into sqlite-vec's little-endian float32 blob."""
    return struct.pack(f"<{len(vec)}f", *vec)


def _apply_vector(
    conn: sqlite3.Connection, kind: JobKind, entity_id: str, vec: list[float]
) -> None:
    """Upsert a vector row for one entity in the appropriate vec0 table.

    vec0 uses integer rowids; we key on the base-table rowid so the vec
    row stays in lock-step with the logical entity. Idempotent via
    DELETE + INSERT so re-embedding the same row is safe.
    """
    if kind == "memory_entry":
        base = conn.execute(
            "SELECT rowid FROM memory_entries WHERE memory_id = ?", (entity_id,)
        ).fetchone()
        vec_table = "memory_entries_vec"
    elif kind == "operation":
        base = conn.execute("SELECT rowid FROM operations WHERE op_id = ?", (entity_id,)).fetchone()
        vec_table = "operations_vec"
    else:
        raise ValueError(f"unknown JobKind {kind!r}")

    if base is None:
        return

    rowid = int(base[0])
    blob = _pack_vector(vec)
    conn.execute(f"DELETE FROM {vec_table} WHERE rowid = ?", (rowid,))
    conn.execute(f"INSERT INTO {vec_table}(rowid, embedding) VALUES (?, ?)", (rowid, blob))


def _process_job(job: EmbedJob, provider: EmbeddingProvider) -> None:
    """Compute an embedding for ``job`` and apply it to its project DB."""
    if not job.text:
        return
    vec = provider.embed_one(job.text)
    conn = db_mod.connect(job.project_path)
    try:
        if not db_mod.VEC_AVAILABLE or db_mod.current_version(conn) < 2:
            # Nothing to write into — V2 migration hasn't run on this DB.
            return
        _apply_vector(conn, job.kind, job.entity_id, vec)
    finally:
        conn.close()


def _run_loop() -> None:
    """Drain the queue until ``stop_worker`` is called.

    Individual job failures are logged and swallowed — one bad row must
    not kill the worker.
    """
    assert _PROVIDER is not None
    while True:
        job = _QUEUE.get()
        if job is None:
            _QUEUE.task_done()
            return
        try:
            _process_job(job, _PROVIDER)
        except Exception:  # noqa: BLE001
            _log.exception("embedding job failed: %r", job)
        finally:
            _QUEUE.task_done()


def start_worker(provider: EmbeddingProvider) -> None:
    """Start the worker thread. Idempotent."""
    global _WORKER_THREAD, _PROVIDER, _ACTIVE
    with _WORKER_LOCK:
        if _WORKER_THREAD is not None and _WORKER_THREAD.is_alive():
            return
        _PROVIDER = provider
        _ACTIVE = True
        t = threading.Thread(target=_run_loop, name="iris-embed-worker", daemon=True)
        t.start()
        _WORKER_THREAD = t


def stop_worker(timeout: float | None = 5.0) -> None:
    """Signal the worker to drain + exit. Safe if none is running."""
    global _WORKER_THREAD, _PROVIDER, _ACTIVE
    with _WORKER_LOCK:
        t = _WORKER_THREAD
        if t is None:
            _ACTIVE = False
            return
        _ACTIVE = False
        _QUEUE.put(None)
    t.join(timeout=timeout)
    with _WORKER_LOCK:
        _WORKER_THREAD = None
        _PROVIDER = None


def drain_sync(provider: EmbeddingProvider) -> int:
    """Single-threaded drain of every queued job. Returns number processed.

    For tests + batch CLIs where the threaded worker's non-determinism is
    a nuisance. Does not start the background thread.
    """
    processed = 0
    while True:
        try:
            job = _QUEUE.get_nowait()
        except queue.Empty:
            return processed
        if job is None:
            continue
        try:
            _process_job(job, provider)
            processed += 1
        except Exception:  # noqa: BLE001
            _log.exception("embedding job failed: %r", job)
        finally:
            _QUEUE.task_done()
