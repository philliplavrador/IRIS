"""Shared fixtures for tests/memory/ — builds a minimal project + session."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

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


@pytest.fixture
def session_id(project_conn: sqlite3.Connection) -> str:
    return start_session(
        project_conn,
        project_id="p1",
        model_provider="anthropic",
        model_name="claude-sonnet-4",
        system_prompt="You are IRIS.",
    )
