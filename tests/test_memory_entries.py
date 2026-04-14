"""Tests for ``iris.projects.memory_entries`` — draft lifecycle + query filters."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from iris.projects import events as events_mod
from iris.projects import memory_entries as me
from iris.projects.db import connect, init_schema
from iris.projects.sessions import start_session


def _make_project(conn: sqlite3.Connection, project_id: str = "p1") -> str:
    conn.execute(
        "INSERT INTO projects (project_id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (project_id, "demo", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
    )
    return project_id


@pytest.fixture
def project_conn(tmp_path: Path):
    conn = connect(tmp_path)
    init_schema(conn)
    _make_project(conn)
    try:
        yield conn
    finally:
        conn.close()


def _new_session(conn: sqlite3.Connection, project_id: str = "p1") -> str:
    return start_session(
        conn,
        project_id=project_id,
        model_provider="anthropic",
        model_name="claude-sonnet-4",
        system_prompt="You are IRIS.",
    )


def _propose_simple(
    conn: sqlite3.Connection,
    *,
    memory_type: str = "finding",
    scope: str = "project",
    text: str = "spike rate stable across blocks",
    importance: float = 5.0,
    dataset_id: str | None = None,
    session_id: str | None = None,
) -> str:
    return me.propose(
        conn,
        project_id="p1",
        scope=scope,
        memory_type=memory_type,
        text=text,
        importance=importance,
        dataset_id=dataset_id,
        session_id=session_id,
    )


# -- propose ----------------------------------------------------------------


def test_propose_returns_id_and_writes_memory_write_event(
    project_conn: sqlite3.Connection,
) -> None:
    sid = _new_session(project_conn)
    mid = _propose_simple(project_conn, session_id=sid, text="channel 3 is noisy")
    assert isinstance(mid, str) and len(mid) == 32

    row = project_conn.execute(
        "SELECT status, memory_type, text, importance FROM memory_entries WHERE memory_id = ?",
        (mid,),
    ).fetchone()
    assert row["status"] == "draft"
    assert row["memory_type"] == "finding"
    assert row["text"] == "channel 3 is noisy"

    # FTS shadow mirrors the row.
    (fts_count,) = project_conn.execute(
        "SELECT count(*) FROM memory_entries_fts WHERE memory_entries_fts MATCH 'noisy'",
    ).fetchone()
    assert fts_count == 1

    # memory_write event was emitted with the correct payload.
    events = project_conn.execute(
        "SELECT type, payload_json FROM events WHERE type = ? ORDER BY rowid ASC",
        (events_mod.EVT_MEMORY_WRITE,),
    ).fetchall()
    assert len(events) == 1
    import json

    payload = json.loads(events[0]["payload_json"])
    assert payload["memory_id"] == mid
    assert payload["status"] == "draft"
    assert payload["memory_type"] == "finding"


def test_propose_rejects_unknown_scope(project_conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError, match="unknown scope"):
        me.propose(
            project_conn,
            project_id="p1",
            scope="galaxy",
            memory_type="finding",
            text="x",
        )


def test_propose_rejects_unknown_memory_type(project_conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError, match="unknown memory_type"):
        me.propose(
            project_conn,
            project_id="p1",
            scope="project",
            memory_type="folklore",
            text="x",
        )


def test_propose_dataset_scope_requires_dataset_id(
    project_conn: sqlite3.Connection,
) -> None:
    with pytest.raises(ValueError, match="dataset_id"):
        me.propose(
            project_conn,
            project_id="p1",
            scope="dataset",
            memory_type="finding",
            text="x",
        )


# -- commit_pending ---------------------------------------------------------


def test_commit_pending_flips_status_and_emits_update_event(
    project_conn: sqlite3.Connection,
) -> None:
    mid1 = _propose_simple(project_conn, text="a")
    mid2 = _propose_simple(project_conn, text="b")
    me.commit_pending(project_conn, [mid1, mid2])

    statuses = {
        row["memory_id"]: row["status"]
        for row in project_conn.execute("SELECT memory_id, status FROM memory_entries").fetchall()
    }
    assert statuses[mid1] == "active"
    assert statuses[mid2] == "active"

    update_events = project_conn.execute(
        "SELECT count(*) FROM events WHERE type = ?",
        (events_mod.EVT_MEMORY_UPDATE,),
    ).fetchone()[0]
    assert update_events == 2


def test_commit_pending_skips_non_drafts(project_conn: sqlite3.Connection) -> None:
    mid = _propose_simple(project_conn)
    me.commit_pending(project_conn, [mid])
    # Second commit is a no-op.
    me.commit_pending(project_conn, [mid, "does-not-exist"])
    update_events = project_conn.execute(
        "SELECT count(*) FROM events WHERE type = ?",
        (events_mod.EVT_MEMORY_UPDATE,),
    ).fetchone()[0]
    assert update_events == 1


# -- discard_pending --------------------------------------------------------


def test_discard_pending_removes_draft_rows_and_fts(
    project_conn: sqlite3.Connection,
) -> None:
    mid = _propose_simple(project_conn, text="ephemeral hunch")
    me.discard_pending(project_conn, [mid])
    assert (
        project_conn.execute(
            "SELECT count(*) FROM memory_entries WHERE memory_id = ?", (mid,)
        ).fetchone()[0]
        == 0
    )
    (fts_count,) = project_conn.execute(
        "SELECT count(*) FROM memory_entries_fts WHERE memory_entries_fts MATCH 'ephemeral'",
    ).fetchone()
    assert fts_count == 0
    # No event is written for discards (spec §10.4).
    (ev_count,) = project_conn.execute(
        "SELECT count(*) FROM events WHERE type IN (?, ?)",
        (events_mod.EVT_MEMORY_UPDATE, events_mod.EVT_MEMORY_DELETE),
    ).fetchone()
    assert ev_count == 0


def test_discard_pending_leaves_active_rows_alone(
    project_conn: sqlite3.Connection,
) -> None:
    mid = _propose_simple(project_conn)
    me.commit_pending(project_conn, [mid])
    me.discard_pending(project_conn, [mid])
    (count,) = project_conn.execute(
        "SELECT count(*) FROM memory_entries WHERE memory_id = ?",
        (mid,),
    ).fetchone()
    assert count == 1


# -- supersede --------------------------------------------------------------


def test_supersede_links_old_to_new_and_flips_status(
    project_conn: sqlite3.Connection,
) -> None:
    old = _propose_simple(project_conn, text="theta peak at 7Hz")
    new = _propose_simple(project_conn, text="theta peak at 8Hz (revised)")
    me.commit_pending(project_conn, [old, new])
    me.supersede(project_conn, old_id=old, new_id=new)

    row = project_conn.execute(
        "SELECT status, superseded_by FROM memory_entries WHERE memory_id = ?",
        (old,),
    ).fetchone()
    assert row["status"] == "superseded"
    assert row["superseded_by"] == new

    # memory_update event emitted for the old id.
    import json

    evs = project_conn.execute(
        "SELECT payload_json FROM events WHERE type = ? ORDER BY rowid DESC LIMIT 1",
        (events_mod.EVT_MEMORY_UPDATE,),
    ).fetchone()
    payload = json.loads(evs["payload_json"])
    assert payload["memory_id"] == old
    assert payload["status"] == "superseded"
    assert payload["superseded_by"] == new


def test_supersede_raises_for_missing_ids(project_conn: sqlite3.Connection) -> None:
    mid = _propose_simple(project_conn)
    with pytest.raises(ValueError, match="does not exist"):
        me.supersede(project_conn, old_id="ghost", new_id=mid)
    with pytest.raises(ValueError, match="does not exist"):
        me.supersede(project_conn, old_id=mid, new_id="ghost")


# -- soft_delete ------------------------------------------------------------


def test_soft_delete_archives_row_and_writes_event(
    project_conn: sqlite3.Connection,
) -> None:
    mid = _propose_simple(project_conn)
    me.commit_pending(project_conn, [mid])
    me.soft_delete(project_conn, mid)

    (status,) = project_conn.execute(
        "SELECT status FROM memory_entries WHERE memory_id = ?", (mid,)
    ).fetchone()
    assert status == "archived"

    (del_events,) = project_conn.execute(
        "SELECT count(*) FROM events WHERE type = ?",
        (events_mod.EVT_MEMORY_DELETE,),
    ).fetchone()
    assert del_events == 1


def test_soft_delete_idempotent(project_conn: sqlite3.Connection) -> None:
    mid = _propose_simple(project_conn)
    me.soft_delete(project_conn, mid)
    me.soft_delete(project_conn, mid)  # no-op second time
    (del_events,) = project_conn.execute(
        "SELECT count(*) FROM events WHERE type = ?",
        (events_mod.EVT_MEMORY_DELETE,),
    ).fetchone()
    assert del_events == 1


# -- query ------------------------------------------------------------------


def test_query_filters_by_memory_type_status_scope_dataset(
    project_conn: sqlite3.Connection,
) -> None:
    # Seed datasets row so FK on memory_entries.dataset_id is satisfied.
    project_conn.execute(
        "INSERT INTO datasets (dataset_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
        ("ds1", "p1", "demo-dataset", "2026-01-01T00:00:00Z"),
    )

    mf = _propose_simple(project_conn, memory_type="finding", text="f1")
    mc = _propose_simple(project_conn, memory_type="caveat", text="c1")
    md_ = _propose_simple(
        project_conn,
        memory_type="finding",
        scope="dataset",
        dataset_id="ds1",
        text="d-finding",
    )
    me.commit_pending(project_conn, [mf, mc, md_])

    # also a draft that should NOT appear in status='active' queries
    mdraft = _propose_simple(project_conn, memory_type="finding", text="draft")

    # by memory_type
    findings = me.query(project_conn, project_id="p1", memory_type="finding")
    finding_ids = {r["memory_id"] for r in findings}
    assert mf in finding_ids and md_ in finding_ids
    assert mc not in finding_ids
    assert mdraft not in finding_ids  # status filter defaults to 'active'

    # by scope
    dataset_scoped = me.query(project_conn, project_id="p1", scope="dataset")
    assert {r["memory_id"] for r in dataset_scoped} == {md_}

    # by dataset_id
    ds_only = me.query(project_conn, project_id="p1", dataset_id="ds1")
    assert {r["memory_id"] for r in ds_only} == {md_}

    # status=None returns everything for the project
    everything = me.query(project_conn, project_id="p1", status=None)
    ids = {r["memory_id"] for r in everything}
    assert {mf, mc, md_, mdraft} <= ids

    # status='draft' isolates drafts
    drafts = me.query(project_conn, project_id="p1", status="draft")
    assert {r["memory_id"] for r in drafts} == {mdraft}


def test_query_rejects_arbitrary_order_by(project_conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError, match="unsupported order_by"):
        me.query(project_conn, project_id="p1", order_by="text; DROP TABLE x")


# -- touch ------------------------------------------------------------------


def test_touch_bumps_last_accessed_and_access_count(
    project_conn: sqlite3.Connection,
) -> None:
    mid = _propose_simple(project_conn)
    me.touch(project_conn, mid)
    me.touch(project_conn, mid)
    row = project_conn.execute(
        "SELECT last_accessed_at, access_count FROM memory_entries WHERE memory_id = ?",
        (mid,),
    ).fetchone()
    assert row["access_count"] == 2
    assert row["last_accessed_at"] is not None


def test_touch_missing_is_noop(project_conn: sqlite3.Connection) -> None:
    me.touch(project_conn, "nope")  # must not raise


# -- set_status -------------------------------------------------------------


def test_set_status_transition_emits_update_event(
    project_conn: sqlite3.Connection,
) -> None:
    mid = _propose_simple(project_conn)
    me.commit_pending(project_conn, [mid])
    me.set_status(project_conn, mid, "stale")
    (status,) = project_conn.execute(
        "SELECT status FROM memory_entries WHERE memory_id = ?", (mid,)
    ).fetchone()
    assert status == "stale"


def test_set_status_rejects_unknown_status(project_conn: sqlite3.Connection) -> None:
    mid = _propose_simple(project_conn)
    with pytest.raises(ValueError, match="unknown status"):
        me.set_status(project_conn, mid, "bogus")


def test_set_status_raises_for_missing_id(project_conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError, match="does not exist"):
        me.set_status(project_conn, "ghost", "archived")
