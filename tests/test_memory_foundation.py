"""Phase 1 foundation tests: L1 ledger, L2 digest, L3 knowledge.

Covers schema init, basic CRUD, supersession, digest draft→final lifecycle,
and the pending→commit flow.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from iris.projects import digest, knowledge, ledger

# -- L1 ledger --------------------------------------------------------------


def test_ledger_init_idempotent(tmp_path: Path):
    p = ledger.init_ledger(tmp_path)
    assert p.is_file()
    # Second call must not raise or corrupt state.
    ledger.init_ledger(tmp_path)
    assert p.is_file()


def test_ledger_records_ops_and_plots(tmp_path: Path):
    ledger.init_ledger(tmp_path)
    op_id = ledger.record_op_run(
        tmp_path,
        op_name="butter_bandpass",
        input_content_hashes=["h1"],
        params_hash="p1",
        session_id="s1",
        runtime_ms=120,
    )
    plot_id = ledger.record_plot(
        tmp_path,
        op_name="spectrogram",
        input_content_hashes=["h1"],
        params_hash="p2",
        plot_path="out/plot.png",
        session_id="s1",
    )
    assert op_id > 0 and plot_id > 0

    rows = ledger.read_ledger(tmp_path, "ops_runs", {"session_id": "s1"})
    assert len(rows) == 1
    assert rows[0]["op_name"] == "butter_bandpass"
    assert rows[0]["runtime_ms"] == 120


def test_ledger_bad_table_raises(tmp_path: Path):
    ledger.init_ledger(tmp_path)
    with pytest.raises(ValueError):
        ledger.read_ledger(tmp_path, "nope")


def test_cache_upsert_bumps_hit_count(tmp_path: Path):
    ledger.init_ledger(tmp_path)
    args = dict(
        op_name="op1",
        input_content_hashes=["h"],
        params_hash="p",
        output_path="out/a.png",
    )
    ledger.upsert_cache_entry(tmp_path, **args)
    ledger.upsert_cache_entry(tmp_path, **args)
    ledger.upsert_cache_entry(tmp_path, **args)
    hit = ledger.lookup_cache(tmp_path, op_name="op1", input_content_hashes=["h"], params_hash="p")
    assert hit is not None
    assert hit["hit_count"] == 2  # starts at 0, bumped twice on re-inserts


# -- L3 knowledge -----------------------------------------------------------


def test_knowledge_init_and_empty_reads(tmp_path: Path):
    knowledge.init_knowledge(tmp_path)
    assert knowledge.active_goals(tmp_path) == []
    assert knowledge.active_decisions(tmp_path) == []
    assert knowledge.recent_facts(tmp_path) == []


def test_propose_and_commit_goal_and_decision(tmp_path: Path):
    knowledge.init_knowledge(tmp_path)
    knowledge.propose(tmp_path, "goal", {"text": "compare two models"}, "s1")
    knowledge.propose(
        tmp_path,
        "decision",
        {"text": "use robust estimator", "rationale": "outliers"},
        "s1",
    )
    pending = knowledge.list_pending(tmp_path, "s1")
    assert len(pending) == 2

    report = knowledge.commit_pending(tmp_path, "s1")
    assert report["committed"] == 2
    assert report["by_kind"] == {"goal": 1, "decision": 1}
    assert knowledge.list_pending(tmp_path, "s1") == []

    goals = knowledge.active_goals(tmp_path)
    decisions = knowledge.active_decisions(tmp_path)
    assert goals[0]["text"] == "compare two models"
    assert decisions[0]["text"] == "use robust estimator"
    assert decisions[0]["rationale"] == "outliers"


def test_decision_supersession(tmp_path: Path):
    knowledge.init_knowledge(tmp_path)
    knowledge.propose(tmp_path, "decision", {"text": "old"}, "s1")
    knowledge.commit_pending(tmp_path, "s1")
    old = knowledge.active_decisions(tmp_path)[0]

    knowledge.propose(
        tmp_path,
        "decision",
        {"text": "new", "supersedes": old["id"]},
        "s2",
    )
    knowledge.commit_pending(tmp_path, "s2")

    active = knowledge.active_decisions(tmp_path)
    assert [d["text"] for d in active] == ["new"]
    # Old row still exists but is status='superseded'.
    row = knowledge.get(tmp_path, "decisions", old["id"])
    assert row is not None and row["status"] == "superseded"


def test_partial_approval_leaves_others_pending(tmp_path: Path):
    knowledge.init_knowledge(tmp_path)
    a = knowledge.propose(tmp_path, "goal", {"text": "a"}, "s1")
    _b = knowledge.propose(tmp_path, "goal", {"text": "b"}, "s1")
    report = knowledge.commit_pending(tmp_path, "s1", approve_ids=[a])
    assert report["committed"] == 1
    remaining = knowledge.list_pending(tmp_path, "s1")
    assert len(remaining) == 1 and remaining[0]["payload"]["text"] == "b"


def test_profile_annotation_upsert(tmp_path: Path):
    knowledge.init_knowledge(tmp_path)
    knowledge.propose(
        tmp_path,
        "profile_annotation",
        {"field_path": "file.csv::t", "annotation": "time (s)"},
        "s1",
    )
    knowledge.commit_pending(tmp_path, "s1")

    # Re-annotate same field — must upsert, not duplicate.
    knowledge.propose(
        tmp_path,
        "profile_annotation",
        {"field_path": "file.csv::t", "annotation": "time (ms)"},
        "s2",
    )
    knowledge.commit_pending(tmp_path, "s2")

    confirmed = knowledge.confirmed_profile_annotations(tmp_path)
    assert len(confirmed) == 1
    assert confirmed[0]["annotation"] == "time (ms)"


def test_bump_referenced_and_set_status(tmp_path: Path):
    knowledge.init_knowledge(tmp_path)
    knowledge.propose(tmp_path, "goal", {"text": "g"}, "s1")
    knowledge.commit_pending(tmp_path, "s1")
    g = knowledge.active_goals(tmp_path)[0]
    before = g["last_referenced_at"]
    knowledge.bump_referenced(tmp_path, "goals", g["id"])
    g2 = knowledge.get(tmp_path, "goals", g["id"])
    assert g2["last_referenced_at"] >= before

    knowledge.set_status(tmp_path, "goals", g["id"], "done")
    assert knowledge.active_goals(tmp_path) == []


def test_unknown_proposal_kind_raises(tmp_path: Path):
    knowledge.init_knowledge(tmp_path)
    with pytest.raises(ValueError):
        knowledge.propose(tmp_path, "nonsense", {}, "s1")


# -- L2 digest --------------------------------------------------------------


def test_digest_draft_lifecycle(tmp_path: Path):
    sess = "abc123"
    d = digest.get_or_create_draft(tmp_path, sess)
    assert d["session_id"] == sess
    assert digest.draft_path(tmp_path, sess).is_file()

    digest.update_draft(
        tmp_path,
        sess,
        {
            "focus": "compare models",
            "next_steps": [{"text": "plot residuals"}, {"text": "write summary"}],
            "decisions": [{"text": "use k=5 cv", "tags": ["methodology"]}],
        },
    )
    d2 = digest.load(digest.draft_path(tmp_path, sess))
    assert d2["focus"] == "compare models"
    assert [n["text"] for n in d2["next_steps"]] == ["plot residuals", "write summary"]
    # Each entry gets an auto-id.
    assert all(n["id"] for n in d2["next_steps"])


def test_digest_finalize_promotes_and_removes_draft(tmp_path: Path):
    sess = "s1"
    digest.get_or_create_draft(tmp_path, sess)
    digest.update_draft(tmp_path, sess, {"focus": "x"})

    final = digest.finalize(tmp_path, sess)
    assert final.is_file()
    assert not digest.draft_path(tmp_path, sess).is_file()
    assert digest.load(final)["focus"] == "x"

    # Idempotent on re-call (returns existing final, no draft present).
    final2 = digest.finalize(tmp_path, sess)
    assert final2 == final


def test_digest_finalize_without_draft_or_final_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        digest.finalize(tmp_path, "never-existed")


def test_digest_validates_patch_shape(tmp_path: Path):
    sess = "s1"
    digest.get_or_create_draft(tmp_path, sess)
    with pytest.raises(ValueError):
        digest.update_draft(tmp_path, sess, {"next_steps": "not a list"})
    with pytest.raises(ValueError):
        digest.update_draft(tmp_path, sess, {"decisions": [{"no_text": 1}]})


def test_latest_final(tmp_path: Path):
    for sess in ("a", "b", "c"):
        digest.get_or_create_draft(tmp_path, sess)
        digest.update_draft(tmp_path, sess, {"focus": f"focus-{sess}"})
        digest.finalize(tmp_path, sess)
    latest = digest.latest_final(tmp_path)
    assert latest is not None
    assert latest["focus"] in {"focus-a", "focus-b", "focus-c"}


# -- create_project integration --------------------------------------------


def test_create_project_initializes_memory_stores(tmp_path: Path, monkeypatch):
    """A freshly-created project must ship with initialized L1/L3 stores
    and an empty digests directory."""
    # Redirect the IRIS repo root to tmp_path so we don't touch real projects/.
    from iris import config as iris_config
    from iris import projects as iris_projects

    monkeypatch.setattr(iris_config, "find_project_root", lambda: tmp_path)
    monkeypatch.setattr(iris_projects, "find_project_root", lambda: tmp_path)

    # Stand up a minimal TEMPLATE the creator can copy.
    template = tmp_path / "projects" / "TEMPLATE"
    template.mkdir(parents=True)
    (template / "claude_config.yaml").write_text("name: null\n")

    path = iris_projects.create_project("proj-phase1", description="test")
    assert path.is_dir()
    assert (path / ledger.LEDGER_FILENAME).is_file()
    assert (path / knowledge.KNOWLEDGE_FILENAME).is_file()
    assert (path / digest.DIGESTS_DIRNAME).is_dir()

    # Stores are queryable and empty.
    assert ledger.read_ledger(path, "ops_runs") == []
    assert knowledge.active_goals(path) == []
    assert digest.latest_final(path) is None
