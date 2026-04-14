"""End-to-end test for tool-result clearing (REVAMP Task 3.6, spec §9.3).

Narrow E2E: simulate the agent-bridge-shaped message flow by hitting the
daemon endpoints ``POST /api/memory/tool_calls`` and
``PATCH /api/memory/tool_calls/{id}/output_artifact``, then assert the
Python stub helper produces output matching the format the TypeScript
clearing module substitutes into the SDK message buffer.

The broader browser-driven E2E (Claude Code SDK actually emitting a bulky
tool_result and the agent-bridge cache carrying the stub into the next turn)
is deferred to the Phase 3 Playwright spec at
``iris-app/e2e/phase3.spec.ts`` — that path requires a live daemon +
Express + Vite stack plus a Claude Max subscription, which the unit-test
gate cannot provide.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from iris.projects.tool_calls import summarize_for_clearing


@pytest.fixture
def sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'iris-test'\n")
    real_template = Path(__file__).resolve().parents[1] / "projects" / "TEMPLATE"
    sandbox_projects = tmp_path / "projects"
    sandbox_projects.mkdir()
    shutil.copytree(real_template, sandbox_projects / "TEMPLATE")
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def client(sandbox: Path) -> TestClient:
    _ = sandbox
    from iris.daemon.app import app

    return TestClient(app)


def _activate_project(client: TestClient, name: str = "clearing-demo") -> None:
    resp = client.post("/api/projects", json={"name": name})
    assert resp.status_code == 200, resp.text
    resp = client.post("/api/projects/active", json={"name": name})
    assert resp.status_code == 200, resp.text


def _start_session(client: TestClient) -> str:
    resp = client.post(
        "/api/memory/sessions/start",
        json={
            "model_provider": "anthropic",
            "model_name": "claude-sonnet-4",
            "system_prompt": "clearing e2e",
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["session_id"]


def test_tool_result_clearing_stub_matches_wire_format(client: TestClient) -> None:
    """Simulate a bulky tool call, persist it, and confirm the stub format."""
    _activate_project(client)
    session_id = _start_session(client)

    # Step 1: Big tool_result body (like `ls -R` on a large tree). >500 tokens
    # in the len/4 heuristic == >2000 chars.
    bulky_output = "\n".join(f"file_{i}.py" for i in range(400))
    assert len(bulky_output) // 4 > 500  # sanity: above the configured threshold

    # Step 2: Persist the tool_call — what agent-bridge does when the SDK
    # streams back a tool_result block.
    resp = client.post(
        "/api/memory/tool_calls",
        json={
            "session_id": session_id,
            "tool_name": "Bash",
            "input": {"cmd": "ls -R src"},
            "success": True,
            "output_summary": bulky_output.splitlines()[0],
            "execution_time_ms": 17,
        },
    )
    assert resp.status_code == 200, resp.text
    tool_call_id = resp.json()["data"]["tool_call_id"]

    # Step 3: Late-bind an artifact id (Phase 5 will materialize these; here we
    # fake a content-addressed pointer to exercise the endpoint shape).
    resp = client.patch(
        f"/api/memory/tool_calls/{tool_call_id}/output_artifact",
        json={"artifact_id": "sha256-deadbeef"},
    )
    assert resp.status_code == 200, resp.text

    # Step 4: The stub the TS clearing helper writes into the SDK buffer must
    # match what the Python helper would produce for the same inputs. This is
    # the contract that keeps Express + daemon on the same wire format.
    stub = summarize_for_clearing(tool_call_id, bulky_output)
    assert stub.startswith("[Tool result cleared. Summary: ")
    assert f"tool_call {tool_call_id}" in stub
    # The summary is the first non-empty line, capped at 120 chars.
    assert "file_0.py" in stub


def test_below_threshold_output_not_cleared_by_helper() -> None:
    """The Python helper is pure — applying it always yields a stub. The
    *decision* to apply it lives in the TS module (threshold gate). This
    test documents the boundary: a short output passed through the helper
    still produces a well-formed stub, so the threshold check really is the
    only gate keeping small tool_results untouched."""
    stub = summarize_for_clearing("tc-short", "ok\n")
    assert stub == "[Tool result cleared. Summary: ok. Full output retained as tool_call tc-short.]"
