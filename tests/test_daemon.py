"""FastAPI daemon endpoint tests."""

from __future__ import annotations

import pytest

# These tests require the daemon optional deps (fastapi, uvicorn)
pytest.importorskip("fastapi")

from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Create a TestClient for the daemon app."""
    from iris.daemon.app import app

    return TestClient(app)


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"


def test_list_ops(client):
    resp = client.get("/api/ops")
    assert resp.status_code == 200
    ops = resp.json()
    assert isinstance(ops, list)
    assert len(ops) > 0
    # Every entry should have name, input_type, output_type
    for op in ops:
        assert "name" in op
        assert "input_type" in op
        assert "output_type" in op


def test_get_op_valid(client):
    resp = client.get("/api/ops/butter_bandpass")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "butter_bandpass"
    assert isinstance(data["transitions"], list)
    assert len(data["transitions"]) > 0


def test_get_op_invalid(client):
    resp = client.get("/api/ops/nonexistent_op")
    assert resp.status_code == 404


def test_list_sources(client):
    resp = client.get("/api/sources")
    assert resp.status_code == 200
    sources = resp.json()
    assert len(sources) == 3
    names = {s["name"] for s in sources}
    assert names == {"mea_trace", "ca_trace", "rtsort"}


def test_list_projects(client):
    resp = client.get("/api/projects")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_list_sessions_no_project(client):
    """Sessions endpoint returns empty list when no project is active."""
    resp = client.get("/api/sessions")
    assert resp.status_code == 200
    assert resp.json() == []


def test_run_pipeline_no_project(client):
    """Pipeline run should fail with 400 when no project is active."""
    resp = client.post("/api/run", json={"dsl": "mea_trace(0).butter_bandpass"})
    # Should be 400 (no active project) or 503 (not initialized)
    assert resp.status_code in (400, 503)


@pytest.mark.skip(reason="phase 0 stub")
def test_append_turn_writes_l0_jsonl(client, tmp_path, monkeypatch):
    """POST /api/memory/append_turn writes a line to conversations/<sid>.jsonl."""
    import json as _json
    from iris.daemon import app as _app
    from iris.projects import conversation as conv

    # Point the daemon at a tmp IRIS root with a project directory.
    proj_root = tmp_path / "projects" / "demo"
    proj_root.mkdir(parents=True)
    monkeypatch.setattr(_app, "_iris_root", tmp_path)

    resp = client.post(
        "/api/memory/append_turn",
        json={
            "project": "demo",
            "session_id": "s1",
            "role": "user",
            "text": "what's in the data",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["turn_index"] == 0

    resp = client.post(
        "/api/memory/append_turn",
        json={
            "project": "demo",
            "session_id": "s1",
            "role": "assistant",
            "text": "let me look",
            "tool_calls": [{"id": "t1", "name": "Read", "input": {"p": "x"}}],
        },
    )
    assert resp.status_code == 200
    assert resp.json()["turn_index"] == 1

    turns = conv.read_conversation(proj_root, "s1")
    assert len(turns) == 2
    assert turns[0]["role"] == "user"
    assert turns[1]["tool_calls"][0]["name"] == "Read"


@pytest.mark.skip(reason="phase 0 stub")
def test_append_turn_rejects_bad_role(client, tmp_path, monkeypatch):
    from iris.daemon import app as _app

    (tmp_path / "projects" / "demo").mkdir(parents=True)
    monkeypatch.setattr(_app, "_iris_root", tmp_path)
    resp = client.post(
        "/api/memory/append_turn",
        json={
            "project": "demo",
            "session_id": "s1",
            "role": "nobody",
            "text": "x",
        },
    )
    assert resp.status_code == 400
