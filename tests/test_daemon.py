"""FastAPI daemon endpoint tests."""
from __future__ import annotations

import pytest

# These tests require the daemon optional deps (fastapi, uvicorn)
pytest.importorskip("fastapi")

from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Create a TestClient for the daemon app."""
    from casi.daemon.app import app
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
