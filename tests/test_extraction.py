"""Tests for ``iris.projects.extraction`` — session-end Claude extraction.

The production module imports ``anthropic`` lazily inside ``_call_anthropic``;
we inject a fake module via ``sys.modules`` so the tests never require the
real SDK to be installed (it is not, in the repo venv).
"""

from __future__ import annotations

import json
import sqlite3
import sys
import types
from pathlib import Path

import pytest

from iris.projects import extraction as extraction_mod
from iris.projects.db import connect, init_schema
from iris.projects.messages import append_message
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


def _seed_transcript(conn: sqlite3.Connection) -> str:
    sid = start_session(
        conn,
        project_id="p1",
        model_provider="anthropic",
        model_name="claude-sonnet-4",
        system_prompt="You are IRIS.",
    )
    append_message(conn, session_id=sid, role="user", content="look at channel 3")
    append_message(
        conn, session_id=sid, role="assistant", content="ran butter_bandpass; noise floor is low"
    )
    return sid


# -- fake anthropic SDK -----------------------------------------------------


class _FakeBlock:
    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.content = [_FakeBlock(text)]


class _FakeMessages:
    def __init__(self, canned_json: str) -> None:
        self._canned = canned_json
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeResponse(self._canned)


class _FakeAnthropic:
    def __init__(self, *, api_key: str, canned_json: str = "") -> None:
        self.api_key = api_key
        self.messages = _FakeMessages(canned_json)
        _FakeAnthropic.last_instance = self


def _install_fake_anthropic(monkeypatch: pytest.MonkeyPatch, canned_json: str) -> None:
    """Inject a stand-in ``anthropic`` module so ``from anthropic import Anthropic`` works."""

    fake_mod = types.ModuleType("anthropic")

    def _factory(*, api_key: str) -> _FakeAnthropic:
        return _FakeAnthropic(api_key=api_key, canned_json=canned_json)

    fake_mod.Anthropic = _factory  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "anthropic", fake_mod)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")


# -- tests ------------------------------------------------------------------


def test_extract_session_filters_below_threshold_and_maps_types(
    project_conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    sid = _seed_transcript(project_conn)

    canned = json.dumps(
        {
            "findings": [
                {"text": "noise floor is low on channel 3", "importance": 7},
                {"text": "trivial observation", "importance": 2},  # filtered (<4)
            ],
            "assumptions": [
                {"text": "recording rig stable for the session", "importance": 4},
            ],
            "caveats": [
                {"text": "sampling drift not yet measured", "importance": 5},
                {"text": "negligible meta-caveat", "importance": 3},  # filtered
            ],
            "open_questions": [
                {"text": "does bandpass width affect spike count?", "importance": 6},
            ],
            "decisions": [
                {"text": "use 300-3000 Hz bandpass by default", "importance": 8},
            ],
            "failure_reflections": [
                {"text": "initial notch filter config was wrong", "importance": 4},
            ],
        }
    )
    _install_fake_anthropic(monkeypatch, canned)

    proposed = extraction_mod.extract_session(project_conn, sid)
    # 8 total items in the canned response, 2 below threshold -> 6 drafts.
    assert len(proposed) == 6

    rows = project_conn.execute(
        "SELECT memory_id, memory_type, status, importance, text FROM memory_entries",
    ).fetchall()
    assert {r["status"] for r in rows} == {"draft"}

    # Ensure each category mapped to the right memory_type enum value.
    by_text = {r["text"]: r["memory_type"] for r in rows}
    assert by_text["noise floor is low on channel 3"] == "finding"
    assert by_text["recording rig stable for the session"] == "assumption"
    assert by_text["sampling drift not yet measured"] == "caveat"
    assert by_text["does bandpass width affect spike count?"] == "open_question"
    assert by_text["use 300-3000 Hz bandpass by default"] == "decision"
    assert by_text["initial notch filter config was wrong"] == "failure_reflection"

    # None of the below-threshold items slipped through.
    texts = set(by_text)
    assert "trivial observation" not in texts
    assert "negligible meta-caveat" not in texts


def test_extract_session_returns_empty_when_no_messages(
    project_conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    sid = start_session(
        project_conn,
        project_id="p1",
        model_provider="anthropic",
        model_name="claude-sonnet-4",
        system_prompt="You are IRIS.",
    )
    _install_fake_anthropic(monkeypatch, "{}")
    assert extraction_mod.extract_session(project_conn, sid) == []


def test_extract_session_raises_on_unknown_session(
    project_conn: sqlite3.Connection,
) -> None:
    with pytest.raises(ValueError, match="unknown session_id"):
        extraction_mod.extract_session(project_conn, "ghost")


def test_extract_session_strips_markdown_fences(
    project_conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    sid = _seed_transcript(project_conn)
    canned = (
        "```json\n"
        + json.dumps(
            {
                "findings": [{"text": "x is stable", "importance": 5}],
                "assumptions": [],
                "caveats": [],
                "open_questions": [],
                "decisions": [],
                "failure_reflections": [],
            }
        )
        + "\n```"
    )
    _install_fake_anthropic(monkeypatch, canned)
    proposed = extraction_mod.extract_session(project_conn, sid)
    assert len(proposed) == 1


def test_extract_session_raises_runtime_error_on_bad_json(
    project_conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    sid = _seed_transcript(project_conn)
    _install_fake_anthropic(monkeypatch, "this is not json at all")
    with pytest.raises(RuntimeError, match="not valid JSON"):
        extraction_mod.extract_session(project_conn, sid)


def test_extract_turn_returns_candidates_for_assistant_message(
    project_conn: sqlite3.Connection,
) -> None:
    sid = _seed_transcript(project_conn)
    assistant_id = project_conn.execute(
        "SELECT message_id FROM messages WHERE session_id = ? AND role = 'assistant'",
        (sid,),
    ).fetchone()[0]
    canned = json.dumps(
        {"findings": [{"text": "bandpass produced a clean noise floor at 300Hz", "importance": 7}]}
    )
    ids = extraction_mod.extract_turn(
        project_conn,
        message_id=assistant_id,
        llm_fn=lambda _s, _u: canned,
    )
    assert len(ids) == 1


def test_extract_turn_dedups_against_existing_memory(
    project_conn: sqlite3.Connection,
) -> None:
    from iris.projects import memory_entries as me

    sid = _seed_transcript(project_conn)
    # Plant an existing active memory with very similar text.
    mid = me.propose(
        project_conn,
        project_id="p1",
        scope="project",
        memory_type="finding",
        text="bandpass produced clean noise floor at 300 Hz",
        importance=7.0,
    )
    me.commit_pending(project_conn, [mid])

    assistant_id = project_conn.execute(
        "SELECT message_id FROM messages WHERE session_id = ? AND role = 'assistant'",
        (sid,),
    ).fetchone()[0]
    canned = json.dumps(
        {"findings": [{"text": "bandpass produced clean noise floor at 300 Hz", "importance": 7}]}
    )
    ids = extraction_mod.extract_turn(
        project_conn,
        message_id=assistant_id,
        llm_fn=lambda _s, _u: canned,
        dedup_threshold=0.5,
    )
    assert ids == []


def test_extract_turn_ignores_non_assistant(project_conn: sqlite3.Connection) -> None:
    sid = _seed_transcript(project_conn)
    user_id = project_conn.execute(
        "SELECT message_id FROM messages WHERE session_id = ? AND role = 'user'",
        (sid,),
    ).fetchone()[0]
    ids = extraction_mod.extract_turn(
        project_conn,
        message_id=user_id,
        llm_fn=lambda _s, _u: "{}",
    )
    assert ids == []


def test_extract_session_requires_api_key(
    project_conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    sid = _seed_transcript(project_conn)
    # Install the fake module but clear the API key.
    fake_mod = types.ModuleType("anthropic")
    fake_mod.Anthropic = lambda *, api_key: _FakeAnthropic(  # type: ignore[attr-defined]
        api_key=api_key, canned_json="{}"
    )
    monkeypatch.setitem(sys.modules, "anthropic", fake_mod)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        extraction_mod.extract_session(project_conn, sid)
