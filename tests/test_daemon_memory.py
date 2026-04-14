"""Daemon tests for Phase 2 memory routes (REVAMP Task 2.4).

Covers ``/api/memory/events`` + ``/api/memory/sessions/*``. Runs the
FastAPI app via ``TestClient`` inside an isolated sandbox so creating a
project and flipping the active pointer stay local to the test.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient


@pytest.fixture
def sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolated repo-like directory with a TEMPLATE clone + chdir into it."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'iris-test'\n")
    real_template = Path(__file__).resolve().parents[1] / "projects" / "TEMPLATE"
    sandbox_projects = tmp_path / "projects"
    sandbox_projects.mkdir()
    shutil.copytree(real_template, sandbox_projects / "TEMPLATE")
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def client(sandbox: Path) -> TestClient:
    from iris.daemon.app import app

    return TestClient(app)


def _new_active_project(client: TestClient, name: str = "demo") -> None:
    resp = client.post("/api/projects", json={"name": name})
    assert resp.status_code == 200, resp.text
    resp = client.post("/api/projects/active", json={"name": name})
    assert resp.status_code == 200, resp.text


def test_events_require_active_project(client: TestClient) -> None:
    resp = client.get("/api/memory/events")
    assert resp.status_code == 400


def test_events_list_and_verify_chain(client: TestClient) -> None:
    _new_active_project(client)

    # Empty project: no events yet, chain trivially valid.
    resp = client.get("/api/memory/events")
    assert resp.status_code == 200
    assert resp.json() == {"data": []}

    resp = client.post("/api/memory/events/verify_chain")
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["valid"] is True
    assert body["checked"] == 0
    assert body["first_break"] is None


def test_sessions_start_and_end_flow(client: TestClient) -> None:
    _new_active_project(client)

    resp = client.post(
        "/api/memory/sessions/start",
        json={
            "model_provider": "anthropic",
            "model_name": "claude-opus-4",
            "system_prompt": "you are a helpful research assistant",
        },
    )
    assert resp.status_code == 200, resp.text
    session = resp.json()["data"]
    session_id = session["session_id"]
    assert session["model_provider"] == "anthropic"
    assert session["ended_at"] is None
    assert session["system_prompt_hash"]  # sha256 hex string
    assert len(session["system_prompt_hash"]) == 64

    # GET returns the same row.
    resp = client.get(f"/api/memory/sessions/{session_id}")
    assert resp.status_code == 200
    assert resp.json()["data"]["session_id"] == session_id

    # Starting the session writes a session_started event.
    resp = client.get("/api/memory/events")
    events = resp.json()["data"]
    assert any(e["type"] == "session_started" for e in events)

    # End the session.
    resp = client.post(
        f"/api/memory/sessions/{session_id}/end",
        json={"summary": "smoke test"},
    )
    assert resp.status_code == 200
    ended = resp.json()["data"]
    assert ended["ended_at"] is not None
    assert ended["summary"] == "smoke test"

    # Chain still verifies after the two writes.
    resp = client.post("/api/memory/events/verify_chain")
    body = resp.json()["data"]
    assert body["valid"] is True
    assert body["checked"] >= 2


def test_get_event_by_id(client: TestClient) -> None:
    _new_active_project(client)
    client.post(
        "/api/memory/sessions/start",
        json={
            "model_provider": "anthropic",
            "model_name": "claude-opus-4",
            "system_prompt": "hi",
        },
    )
    events = client.get("/api/memory/events").json()["data"]
    assert events, "expected at least one event"
    event_id = events[0]["event_id"]

    resp = client.get(f"/api/memory/events/{event_id}")
    assert resp.status_code == 200
    assert resp.json()["data"]["event_id"] == event_id

    resp = client.get("/api/memory/events/does-not-exist")
    assert resp.status_code == 404


def test_events_filter_by_type(client: TestClient) -> None:
    _new_active_project(client)
    resp = client.post(
        "/api/memory/sessions/start",
        json={
            "model_provider": "anthropic",
            "model_name": "claude-opus-4",
            "system_prompt": "x",
        },
    )
    session_id = resp.json()["data"]["session_id"]
    client.post(f"/api/memory/sessions/{session_id}/end", json={"summary": "done"})

    resp = client.get("/api/memory/events", params={"type": "session_started"})
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body and all(e["type"] == "session_started" for e in body)

    resp = client.get("/api/memory/events", params={"type": "bogus_type"})
    assert resp.status_code == 400


def test_end_session_unknown_id_returns_404(client: TestClient) -> None:
    _new_active_project(client)
    resp = client.post(
        "/api/memory/sessions/does-not-exist/end",
        json={"summary": "nope"},
    )
    assert resp.status_code == 404
