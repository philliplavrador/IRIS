"""Tests for ``iris.projects.runs`` — lifecycle + lineage queries."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from iris.projects import events as events_mod
from iris.projects.db import connect, init_schema
from iris.projects.runs import (
    complete_run,
    fail_run,
    list_runs,
    query_lineage,
    start_run,
)
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


def _transform_events(conn: sqlite3.Connection, run_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT payload_json FROM events WHERE type = ? ORDER BY rowid ASC",
        (events_mod.EVT_TRANSFORM_RUN,),
    ).fetchall()
    payloads = [json.loads(r[0]) for r in rows]
    return [p for p in payloads if p.get("run_id") == run_id]


def test_start_run_inserts_running_row_and_emits_event(
    project_conn: sqlite3.Connection,
) -> None:
    sid = _new_session(project_conn)
    run_id = start_run(
        project_conn,
        project_id="p1",
        session_id=sid,
        operation_type="plot",
        parameters={"kind": "butter_bandpass"},
        input_versions=["dv1"],
    )
    assert isinstance(run_id, str) and len(run_id) == 32

    row = project_conn.execute(
        "SELECT status, operation_type, session_id, parameters_json, input_versions_json "
        "FROM runs WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    assert row["status"] == "running"
    assert row["operation_type"] == "plot"
    assert row["session_id"] == sid
    assert json.loads(row["parameters_json"]) == {"kind": "butter_bandpass"}
    assert json.loads(row["input_versions_json"]) == ["dv1"]

    evs = _transform_events(project_conn, run_id)
    assert len(evs) == 1
    assert evs[0]["phase"] == "start"
    assert evs[0]["operation_type"] == "plot"


def test_complete_run_marks_completed_and_emits_event(
    project_conn: sqlite3.Connection,
) -> None:
    sid = _new_session(project_conn)
    run_id = start_run(
        project_conn,
        project_id="p1",
        session_id=sid,
        operation_type="plot",
    )
    complete_run(
        project_conn,
        run_id,
        output_artifact_ids=["a1", "a2"],
        findings_text="Looks clean.",
        execution_time_ms=42,
    )

    row = project_conn.execute(
        "SELECT status, findings_text, output_artifact_ids, execution_time_ms "
        "FROM runs WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    assert row["status"] == "completed"
    assert row["findings_text"] == "Looks clean."
    assert json.loads(row["output_artifact_ids"]) == ["a1", "a2"]
    assert row["execution_time_ms"] == 42

    evs = _transform_events(project_conn, run_id)
    phases = [e["phase"] for e in evs]
    assert phases == ["start", "complete"]
    assert evs[1]["output_artifact_ids"] == ["a1", "a2"]
    assert evs[1]["execution_time_ms"] == 42


def test_fail_run_writes_error_text_and_failure_event(
    project_conn: sqlite3.Connection,
) -> None:
    sid = _new_session(project_conn)
    run_id = start_run(
        project_conn,
        project_id="p1",
        session_id=sid,
        operation_type="correlation_analysis",
    )
    fail_run(
        project_conn,
        run_id,
        error_text="divide by zero",
        failure_reflection="input series was empty",
    )

    row = project_conn.execute(
        "SELECT status, error_text, failure_reflection FROM runs WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    assert row["status"] == "failed"
    assert row["error_text"] == "divide by zero"
    assert row["failure_reflection"] == "input series was empty"

    evs = _transform_events(project_conn, run_id)
    phases = [e["phase"] for e in evs]
    assert phases == ["start", "fail"]
    assert evs[1]["error_text"] == "divide by zero"


def test_list_runs_filters_by_session_and_status(
    project_conn: sqlite3.Connection,
) -> None:
    sid_a = _new_session(project_conn)
    sid_b = _new_session(project_conn)

    # In session A: one completed + one failed.
    r_a_ok = start_run(project_conn, project_id="p1", session_id=sid_a, operation_type="plot")
    complete_run(project_conn, r_a_ok, execution_time_ms=1)
    r_a_bad = start_run(project_conn, project_id="p1", session_id=sid_a, operation_type="plot")
    fail_run(project_conn, r_a_bad, error_text="boom")

    # In session B: one running.
    r_b_run = start_run(project_conn, project_id="p1", session_id=sid_b, operation_type="plot")

    only_a = list_runs(project_conn, project_id="p1", session_id=sid_a)
    assert {r["run_id"] for r in only_a} == {r_a_ok, r_a_bad}

    only_b_running = list_runs(project_conn, project_id="p1", session_id=sid_b, status="running")
    assert [r["run_id"] for r in only_b_running] == [r_b_run]

    all_failed = list_runs(project_conn, project_id="p1", status="failed")
    assert [r["run_id"] for r in all_failed] == [r_a_bad]

    with pytest.raises(ValueError, match="unknown status"):
        list_runs(project_conn, project_id="p1", status="weird")


def test_query_lineage_walks_ancestors_and_descendants(
    project_conn: sqlite3.Connection,
) -> None:
    sid = _new_session(project_conn)
    # Chain: r1 <- r2 <- r3
    r1 = start_run(project_conn, project_id="p1", session_id=sid, operation_type="plot")
    r2 = start_run(
        project_conn,
        project_id="p1",
        session_id=sid,
        operation_type="plot",
        parent_run_id=r1,
    )
    r3 = start_run(
        project_conn,
        project_id="p1",
        session_id=sid,
        operation_type="plot",
        parent_run_id=r2,
    )

    mid = query_lineage(project_conn, r2)
    assert [a["run_id"] for a in mid["ancestors"]] == [r1]
    assert [d["run_id"] for d in mid["descendants"]] == [r3]

    top = query_lineage(project_conn, r1)
    assert top["ancestors"] == []
    assert {d["run_id"] for d in top["descendants"]} == {r2, r3}

    bottom = query_lineage(project_conn, r3)
    assert {a["run_id"] for a in bottom["ancestors"]} == {r1, r2}
    assert bottom["descendants"] == []

    # Unknown run -> empty lists, no raise.
    empty = query_lineage(project_conn, "deadbeef")
    assert empty == {"ancestors": [], "descendants": []}
