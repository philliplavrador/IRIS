"""Phase 2-4 tests: slice_builder, recall, archive, views, profile, tools."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from iris.projects import (
    archive,
    digest,
    knowledge,
    ledger,
    profile,
    recall,
    slice_builder,
    tools,
    views,
)
from iris.projects import conversation as conv


@pytest.fixture
def project(tmp_path: Path) -> Path:
    knowledge.init_knowledge(tmp_path)
    ledger.init_ledger(tmp_path)
    digest.digests_dir(tmp_path)
    return tmp_path


# -- slice_builder ----------------------------------------------------------


def test_empty_slice_is_empty(project: Path):
    s = slice_builder.build_slice(project)
    assert s.entries == []
    assert s.used_tokens == 0
    assert s.render() == "(pinned slice is empty)"


def test_slice_respects_budget(project: Path):
    knowledge.propose(project, "goal", {"text": "goal one"}, "s1")
    knowledge.propose(project, "goal", {"text": "goal two"}, "s1")
    knowledge.commit_pending(project, "s1")
    # Absurdly small budget forces all entries to be dropped.
    s = slice_builder.build_slice(project, budget_tokens=1)
    assert s.used_tokens == 0
    assert "Active Goals" in s.dropped_sections


def test_slice_includes_goals_and_digest(project: Path):
    knowledge.propose(project, "goal", {"text": "compare models"}, "s1")
    knowledge.commit_pending(project, "s1")
    digest.get_or_create_draft(project, "s1")
    digest.update_draft(
        project,
        "s1",
        {"focus": "initial sweep", "next_steps": [{"text": "plot residuals"}]},
    )
    digest.finalize(project, "s1")

    s, rendered = slice_builder.build_and_cache(project, budget_tokens=500)
    assert "compare models" in rendered
    assert "initial sweep" in rendered
    assert (project / slice_builder.CACHE_REL).is_file()


# -- recall -----------------------------------------------------------------


def test_recall_empty_project(project: Path):
    assert recall.recall(project, "anything") == []


def test_recall_finds_planted_decision(project: Path):
    knowledge.propose(
        project,
        "decision",
        {"text": "use the robust estimator for outliers", "rationale": "Huber"},
        "s1",
    )
    knowledge.commit_pending(project, "s1")
    hits = recall.recall(project, "robust estimator outliers", k=3, use_vector=False)
    assert hits, "expected at least one hit"
    top = hits[0]
    assert "robust estimator" in top.text.lower()
    assert top.citation.startswith("decision#")


def test_recall_filters_by_source(project: Path):
    knowledge.propose(project, "decision", {"text": "alpha"}, "s1")
    knowledge.propose(project, "fact", {"key": "k", "value": "alpha"}, "s1")
    knowledge.commit_pending(project, "s1")
    hits = recall.recall(
        project, "alpha", k=5, filters={"source": "fact"}, use_vector=False
    )
    assert all(h.source == "fact" for h in hits)


def test_recall_empty_query_returns_empty(project: Path):
    assert recall.recall(project, "") == []
    assert recall.recall(project, "   ") == []


# -- archive ----------------------------------------------------------------


def test_archive_rolls_old_digests(project: Path):
    from datetime import datetime, timedelta, timezone

    old_ts = (datetime.now(timezone.utc) - timedelta(days=200)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    digest.get_or_create_draft(project, "old_sess")
    digest.update_draft(project, "old_sess", {"focus": "ancient work"})
    digest.finalize(project, "old_sess")
    # Backdate the final after finalization (finalize() bumps updated_at).
    final = digest.final_path(project, "old_sess")
    d = digest.load(final)
    d["updated_at"] = old_ts
    d["created_at"] = old_ts
    digest.save(final, d)

    # Also plant a fresh digest that must NOT be rolled.
    digest.get_or_create_draft(project, "fresh_sess")
    digest.update_draft(project, "fresh_sess", {"focus": "recent"})
    digest.finalize(project, "fresh_sess")

    report = archive.rollup_old_digests(project, retention_days=90)
    assert report["rolled"] == 1
    assert report["months"]
    rollup = json.loads(
        (project / "digests" / "monthly_rollups" / f"{report['months'][0]}.json").read_text()
    )
    assert rollup[0]["focus"] == "ancient work"
    # Fresh still in digests/ (not archive/)
    assert (project / "digests" / "fresh_sess.json").is_file()
    assert (project / "digests" / "archive" / "old_sess.json").is_file()


# -- views ------------------------------------------------------------------


def test_views_regenerate_empty(project: Path):
    paths = views.regenerate_all(project)
    for p in paths:
        assert p.is_file()
        content = p.read_text()
        assert "# " in content


def test_views_reflect_committed_rows(project: Path):
    knowledge.propose(project, "goal", {"text": "ship the redesign"}, "s1")
    knowledge.propose(
        project,
        "decision",
        {"text": "pick SQLite over JSONL", "rationale": "queryability"},
        "s1",
    )
    knowledge.commit_pending(project, "s1")
    hist = views.regenerate_history(project)
    text = hist.read_text()
    assert "ship the redesign" in text
    assert "pick SQLite over JSONL" in text
    assert "queryability" in text


# -- conversation (L0) ------------------------------------------------------


def test_l0_append_and_read(project: Path):
    conv.append_turn(project, "s1", "user", "hello there")
    conv.append_turn(project, "s1", "assistant", "hi!")
    turns = conv.read_conversation(project, "s1")
    assert len(turns) == 2
    assert turns[0]["role"] == "user" and turns[0]["text"] == "hello there"
    assert turns[1]["role"] == "assistant"

    sliced = conv.read_conversation(project, "s1", turn_range="1:")
    assert len(sliced) == 1 and sliced[0]["role"] == "assistant"


def test_l0_rejects_bad_role(project: Path):
    with pytest.raises(ValueError):
        conv.append_turn(project, "s1", "nobody", "x")


# -- profile ----------------------------------------------------------------


def test_profile_csv_extracts_columns(tmp_path: Path, project: Path):
    pd = pytest.importorskip("pandas")
    f = tmp_path / "sample.csv"
    pd.DataFrame({"t": [0, 1, 2], "v": [10.0, 11.5, 9.2], "g": ["a", "b", "a"]}).to_csv(
        f, index=False
    )
    result = profile.profile_data(f, project_path=project)
    assert result["kind"] == "csv"
    assert result["shape"] == [3, 3]
    col_names = {c["name"] for c in result["columns"]}
    assert col_names == {"t", "v", "g"}

    # Rows staged as unconfirmed.
    rows = knowledge.confirmed_profile_annotations(project)
    assert rows == []  # none confirmed yet
    with knowledge.open_knowledge(project) as c:
        all_rows = c.execute("SELECT * FROM data_profile_fields").fetchall()
    assert len(all_rows) >= 4  # _file + t + v + g


def test_profile_unknown_format(tmp_path: Path):
    f = tmp_path / "weird.xyz"
    f.write_text("some text content\n")
    result = profile.profile_data(f)
    assert result["kind"] == "text"
    assert "sample_head" in result


def test_profile_nonexistent_file_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        profile.profile_data(tmp_path / "nope.csv")


# -- tools (Phase 3) --------------------------------------------------------


def test_tools_commit_flow(project: Path):
    sess = "s1"
    tools.record_turn(project, sess, "user", "let's try the robust estimator")
    pid1 = tools.propose_decision(project, sess, "robust estimator", rationale="outliers")
    pid2 = tools.propose_goal(project, sess, "publish writeup")
    tools.propose_digest_edit(
        project, sess, {"focus": "outlier handling", "next_steps": [{"text": "residual plot"}]}
    )

    # Partial approve: only pid1.
    report = tools.commit_session_writes(project, sess, approve_ids=[pid1])
    assert report["committed"] == 1
    assert report["by_kind"] == {"decision": 1}

    # Goal remained pending.
    pending = knowledge.list_pending(project, sess)
    assert any(p["id"] == pid2 for p in pending)

    # Digest finalized, views regenerated.
    assert report["finalized_digest"] is not None
    assert len(report["views"]) == 2


def test_tools_recall_via_wrapper(project: Path):
    knowledge.propose(project, "decision", {"text": "prefer k-fold=5"}, "s1")
    knowledge.commit_pending(project, "s1")
    hits = tools.recall(project, "k-fold")
    assert isinstance(hits, list)
    if hits:
        assert "citation" in hits[0]


def test_tools_get_bad_source_raises(project: Path):
    with pytest.raises(ValueError):
        tools.get(project, "no-such-source", 1)
