"""Regression: POST /memory/operations/{id}/validate must return a non-empty
payload.

The bug: ``ValidationResult`` is a ``dict`` subclass, so ``result.__dict__``
is empty. The route was serializing with ``__dict__`` and shipping
``{"data": {}}`` to the caller, masking static/unit/sample errors. After the
fix the response must carry the actual ``ok`` / ``stage`` / ``error`` fields.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from iris.projects import (
    create_project,
    delete_project,
    set_active_project,
)

PROJECT_NAME = "test_validate_response"


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Isolate the repo active-project pointer so tests don't clobber dev state.
    # ``resolve_active_project`` reads ``.iris/active_project`` relative to
    # the IRIS repo root; we can't easily redirect that without touching the
    # filesystem, so we create a real project, flip the pointer, then restore.
    from iris.projects import active_project_path

    pointer = active_project_path()
    previous = pointer.read_text(encoding="utf-8") if pointer.exists() else None

    # Clean up any stale project from a prior aborted run.
    try:
        delete_project(PROJECT_NAME)
    except Exception:
        pass

    create_project(PROJECT_NAME)
    set_active_project(PROJECT_NAME)

    from iris.daemon.app import app

    tc = TestClient(app)
    try:
        yield tc
    finally:
        if previous is not None:
            pointer.write_text(previous, encoding="utf-8")
        elif pointer.exists():
            pointer.unlink()
        try:
            delete_project(PROJECT_NAME)
        except Exception:
            pass


def _propose(client: TestClient, name: str, code: str) -> str:
    res = client.post(
        "/api/memory/operations/propose",
        json={
            "name": name,
            "version": "0.1.0",
            "description": f"{name} trivial op",
            "code": code,
            "signature_json": {"input": "number", "output": "number"},
        },
    )
    assert res.status_code == 200, res.text
    op_id = res.json()["data"]["op_id"]
    assert isinstance(op_id, str) and op_id
    return op_id


def test_validate_good_op_returns_non_empty_payload(client: TestClient) -> None:
    op_id = _propose(client, "good_validator", "def run(x):\n    return x + 1\n")

    res = client.post(
        f"/api/memory/operations/{op_id}/validate",
        json={"sample_input": {"x": 3}},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    payload = body.get("data")
    # Regression guard: the response body must NOT be an empty dict.
    assert isinstance(payload, dict)
    assert payload, f"expected non-empty validation payload, got {body!r}"
    assert payload.get("ok") is True
    assert payload.get("stage") == "done"
    assert "error" in payload
    assert payload.get("error") is None

    # DB row should show validated status.
    row = client.get(f"/api/memory/operations/{op_id}").json()["data"]
    assert row["validation_status"] == "validated"


def test_validate_broken_op_returns_error_details(client: TestClient) -> None:
    # Syntax error: `retur` instead of `return`.
    op_id = _propose(client, "broken_validator", "def run(x):\n    retur x + 1\n")

    res = client.post(
        f"/api/memory/operations/{op_id}/validate",
        json={},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    payload = body.get("data")
    assert isinstance(payload, dict)
    assert payload, f"expected non-empty validation payload, got {body!r}"
    assert payload.get("ok") is False
    assert payload.get("stage") == "static"
    assert isinstance(payload.get("error"), str)
    assert "SyntaxError" in payload["error"]

    row = client.get(f"/api/memory/operations/{op_id}").json()["data"]
    assert row["validation_status"] == "rejected"
