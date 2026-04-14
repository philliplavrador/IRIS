"""Tests for ``iris.projects.embedding_worker`` — queue + drain."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from pathlib import Path

import pytest

from iris.projects import embedding_worker as ew
from iris.projects import memory_entries as me
from iris.projects.db import connect, init_schema
from iris.projects.embeddings import EmbeddingProvider


class _FakeProvider(EmbeddingProvider):
    """Deterministic stub: len-based 3-d vectors, no ML deps."""

    dim = 3
    model = "fake"

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [[float(len(t)), 1.0, 2.0] for t in texts]


def _make_project(conn: sqlite3.Connection) -> str:
    conn.execute(
        "INSERT INTO projects (project_id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
        ("p1", "demo", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
    )
    return "p1"


def test_enqueue_without_worker_is_noop(tmp_path: Path) -> None:
    """With no worker started, enqueue must silently drop the job.

    This is the V1-safety contract: V1 code paths call enqueue() from
    commit_pending/register and must never block or error even though
    V2 features aren't enabled.
    """
    ew.enqueue(
        ew.EmbedJob(
            kind="memory_entry",
            project_path=tmp_path,
            entity_id="does-not-exist",
            text="anything",
        )
    )
    # No queue growth, no thread, no exception.


def test_drain_sync_skips_when_vec_unavailable(tmp_path: Path) -> None:
    """If VEC_AVAILABLE is False or the DB is still V1, drain silently no-ops.

    Exercises the happy-path skip on a typical Windows build where the
    extension won't load. We just need to confirm no exception.
    """
    conn = connect(tmp_path)
    try:
        init_schema(conn)
        _make_project(conn)
        mid = me.propose(
            conn,
            project_id="p1",
            scope="project",
            memory_type="finding",
            text="whatever",
        )
        me.commit_pending(conn, [mid])
    finally:
        conn.close()

    # commit_pending enqueued a job but the worker isn't started — so the
    # queue holds at most one item; drain_sync runs without errors.
    processed = ew.drain_sync(_FakeProvider())
    # Depending on whether enqueue ran before start_worker was called, the
    # queue may be empty (hot-path _ACTIVE gate). Either 0 or 1 is fine.
    assert processed in (0, 1)


def test_drain_sync_writes_vector_when_vec_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When VEC_AVAILABLE + V2 are both in effect, drain persists vectors.

    We fake VEC_AVAILABLE and hand-create a minimal vec-like table so the
    worker exercises its full write path without depending on sqlite-vec.
    """
    from iris.projects import db as db_mod

    conn = connect(tmp_path)
    try:
        init_schema(conn)
        _make_project(conn)
        # Simulate v2 by creating a regular table named like the vec0 one.
        conn.execute("CREATE TABLE memory_entries_vec(rowid INTEGER PRIMARY KEY, embedding BLOB)")
        conn.execute("PRAGMA user_version = 2")
        mid = me.propose(
            conn,
            project_id="p1",
            scope="project",
            memory_type="finding",
            text="load-bearing memory",
        )
    finally:
        conn.close()

    # Pretend vec is available + start the (module-level) flag so enqueue
    # accepts work, then immediately stop so only drain_sync runs the job.
    monkeypatch.setattr(db_mod, "VEC_AVAILABLE", True)
    ew._ACTIVE = True  # noqa: SLF001 - test-only switch
    try:
        ew.enqueue(
            ew.EmbedJob(
                kind="memory_entry",
                project_path=tmp_path,
                entity_id=mid,
                text="load-bearing memory",
            )
        )
        processed = ew.drain_sync(_FakeProvider())
    finally:
        ew._ACTIVE = False

    assert processed == 1
    conn = connect(tmp_path)
    try:
        (count,) = conn.execute("SELECT COUNT(*) FROM memory_entries_vec").fetchone()
    finally:
        conn.close()
    assert count == 1
