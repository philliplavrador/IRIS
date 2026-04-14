"""Tests for ``iris.projects.tool_calls`` — append, attach artifact, clearing stub."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from iris.projects.db import connect, init_schema
from iris.projects.sessions import start_session
from iris.projects.tool_calls import (
    append_tool_call,
    attach_output_artifact,
    summarize_for_clearing,
)


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


def _new_session(conn: sqlite3.Connection) -> str:
    return start_session(
        conn,
        project_id="p1",
        model_provider="anthropic",
        model_name="claude-sonnet-4",
        system_prompt="prompt",
    )


def test_append_tool_call_stores_canonical_input_json(
    project_conn: sqlite3.Connection,
) -> None:
    sid = _new_session(project_conn)
    tcid = append_tool_call(
        project_conn,
        session_id=sid,
        tool_name="Bash",
        # Keys deliberately reversed so we can assert canonical sort_keys output.
        input={"timeout": 30, "cmd": "ls"},
        success=True,
        output_summary="listed 3 files",
        execution_time_ms=42,
    )
    row = project_conn.execute(
        "SELECT tool_name, input_json, success, output_summary, "
        "execution_time_ms, output_artifact_id, error_text "
        "FROM tool_calls WHERE tool_call_id = ?",
        (tcid,),
    ).fetchone()
    assert row["tool_name"] == "Bash"
    assert row["success"] == 1
    assert row["output_summary"] == "listed 3 files"
    assert row["execution_time_ms"] == 42
    assert row["output_artifact_id"] is None
    assert row["error_text"] is None
    # Canonical JSON = sorted keys, no whitespace.
    assert row["input_json"] == json.dumps(
        {"cmd": "ls", "timeout": 30},
        sort_keys=True,
        separators=(",", ":"),
    )


def test_attach_output_artifact_updates_row(project_conn: sqlite3.Connection) -> None:
    sid = _new_session(project_conn)
    tcid = append_tool_call(
        project_conn,
        session_id=sid,
        tool_name="iris.run",
        input={"pipeline": "x"},
        success=True,
    )
    attach_output_artifact(project_conn, tcid, "sha256-deadbeef")
    (aid,) = project_conn.execute(
        "SELECT output_artifact_id FROM tool_calls WHERE tool_call_id = ?",
        (tcid,),
    ).fetchone()
    assert aid == "sha256-deadbeef"


def test_attach_output_artifact_raises_on_missing_row(
    project_conn: sqlite3.Connection,
) -> None:
    with pytest.raises(LookupError, match="tool_call"):
        attach_output_artifact(project_conn, "nope", "sha256-x")


def test_summarize_for_clearing_uses_first_nonempty_line() -> None:
    stub = summarize_for_clearing("tc1", "\n\nfirst real line\nsecond line\n")
    assert stub == (
        "[Tool result cleared. Summary: first real line. Full output retained as tool_call tc1.]"
    )


def test_summarize_for_clearing_truncates_long_lines() -> None:
    long = "x" * 200
    stub = summarize_for_clearing("tc2", long)
    # Look for the summary payload specifically — the stub itself is longer.
    assert "tc2" in stub
    assert "\u2026" in stub  # ellipsis marks truncation
    # The summary portion should be capped to 120 chars.
    prefix = "[Tool result cleared. Summary: "
    suffix_start = stub.index(". Full output retained")
    summary = stub[len(prefix) : suffix_start]
    assert len(summary) == 120


def test_summarize_for_clearing_handles_empty_output() -> None:
    assert "<empty output>" in summarize_for_clearing("tc3", "")
    assert "<empty output>" in summarize_for_clearing("tc4", "   \n\t\n")
