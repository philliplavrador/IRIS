"""Scale simulation for the §13.8 memory verification walkthrough.

Generates N synthetic sessions against an isolated project tree (tmp_path,
domain-agnostic content) and asserts three invariants:

1. The pinned slice built by :mod:`iris.projects.slice_builder` never
   exceeds ``pin_budget_tokens`` on any turn (default 2000).
2. :func:`iris.projects.recall.recall` returns the planted decision in the
   top-k for paraphrased queries with at least 90% success over ~20 planted
   decisions.
3. :func:`iris.projects.slice_builder.build_slice` p95 latency is
   under 150 ms over 200 calls after the corpus is fully populated.

The smoke variant (20 sessions) runs in the default suite with BM25-only
retrieval (no embeddings). The full variant (200 sessions) is gated by
``@pytest.mark.slow`` and optionally exercises the configured embedding
provider.
"""

from __future__ import annotations

import os
import random
import statistics
import time
from pathlib import Path

import pytest

from iris.projects import (
    conversation as conv,
)
from iris.projects import (
    digest,
    embeddings,
    knowledge,
    ledger,
    recall,
    slice_builder,
)

# -- content pools (domain-agnostic) ---------------------------------------

TOPIC_POOL = [
    "tabular summary sweep",
    "model comparison on held-out split",
    "outlier inspection across segments",
    "imputation strategy for missing values",
    "feature selection via permutation importance",
    "residual diagnostics after regression",
    "segment-level variance audit",
    "categorical encoding review",
    "bootstrap confidence intervals",
    "time-window aggregation",
    "rolling-metric trend check",
    "subset calibration vs holdout",
    "record linkage dedup pass",
    "schema drift review",
    "resampling cadence check",
]

OP_POOL = [
    "summary_stats",
    "pca",
    "kmeans",
    "outlier_report",
    "bootstrap_ci",
    "permutation_test",
    "rolling_mean",
    "resample",
    "fft",
    "linear_fit",
    "loess_smooth",
    "histogram",
    "cross_tab",
    "correlation_matrix",
]

NEXT_STEP_POOL = [
    "rerun with trimmed features",
    "plot residuals by segment",
    "inspect the tail of the distribution",
    "re-weight the minority class",
    "add a holdout fold for stability",
    "draft the summary table",
    "double-check the lag window",
    "compare against the baseline model",
]

FACT_POOL = [
    ("sample size", "roughly 12k rows after dedup"),
    ("target column", "encoded as ordinal in the intake"),
    ("null rate", "under 1% across retained columns"),
    ("time zone", "timestamps normalized to utc"),
    ("group key", "stable across sessions"),
]

# 20 planted decisions with distinctive content words so BM25 alone can
# surface them from paraphrased queries. Each `query` reuses the distinctive
# nouns but paraphrases the surrounding grammar.
PLANTED: list[tuple[str, str]] = [
    (
        "adopt the zephyr clustering heuristic for cohort partitioning",
        "use zephyr clustering to partition cohorts",
    ),
    (
        "cap outlier z-scores at 3.5 sigma using the tukey envelope rule",
        "tukey envelope capping outliers at 3.5 sigma",
    ),
    (
        "prefer spearman over pearson for the xanadu subset",
        "xanadu subset should use spearman correlation",
    ),
    (
        "use hollering bootstrap intervals instead of normal approximation",
        "hollering bootstrap replaces the normal approximation",
    ),
    (
        "drop rows with quantized bellweather timestamps before aggregation",
        "exclude bellweather quantized timestamps prior to aggregation",
    ),
    (
        "switch to the orthrus feature bundle for the ablation run",
        "orthrus feature bundle selected for ablation",
    ),
    (
        "raise the murmur threshold from 0.2 to 0.35 to cut false positives",
        "murmur threshold increased to 0.35 against false positives",
    ),
    (
        "apply the vellichor smoothing window only to the weekly series",
        "vellichor smoothing restricted to weekly aggregates",
    ),
    (
        "treat the petrichor cohort as a separate stratum in calibration",
        "petrichor cohort needs its own calibration stratum",
    ),
    (
        "use the nimbus fold assignment for reproducible cross-validation",
        "nimbus fold assignment keeps cross validation reproducible",
    ),
    (
        "log transform the chimera throughput column before regression",
        "chimera throughput takes a log transform prior to regression",
    ),
    (
        "drop the quokka indicator from the feature set due to leakage",
        "quokka indicator removed from features for leakage",
    ),
    (
        "set the sphinx decay rate to 0.9 in the temporal weight",
        "sphinx decay rate configured at 0.9 for temporal weighting",
    ),
    (
        "standardize the valkyrie score using the 2024 reference window",
        "valkyrie score uses the 2024 reference window for standardization",
    ),
    (
        "exclude the manticore batch from the training set entirely",
        "manticore batch removed from training entirely",
    ),
    (
        "anchor the bifrost baseline to the first confirmed annotation",
        "bifrost baseline anchored at the first confirmed annotation",
    ),
    (
        "treat the cerulean null token as a distinct category",
        "cerulean null token is its own category",
    ),
    (
        "keep the onyx pipeline preprocessor frozen across experiments",
        "onyx preprocessor stays frozen across experiments",
    ),
    (
        "bound the saffron imputation at the 5th and 95th percentiles",
        "saffron imputation clipped to 5th and 95th percentile bounds",
    ),
    (
        "use the jubilee splitter for time-respecting hold-out samples",
        "jubilee splitter for time respecting hold-out splits",
    ),
]

assert len(PLANTED) == 20, "planted decision set must remain at 20"


# -- session generator -----------------------------------------------------


def _init_project(project_path: Path) -> None:
    knowledge.init_knowledge(project_path)
    ledger.init_ledger(project_path)
    digest.digests_dir(project_path)


def _make_session(
    project_path: Path,
    session_id: str,
    rng: random.Random,
    planted_decision: tuple[str, str] | None,
    check_slice_budget,
    budget_tokens: int,
) -> None:
    """Populate L0/L1/L2/L3 for one synthetic session.

    ``check_slice_budget`` is invoked once per simulated "turn" to enforce
    the per-turn budget invariant from §13.8.
    """
    topic = rng.choice(TOPIC_POOL)

    # -- L0 JSONL (a handful of turns) -------------------------------------
    conv.append_turn(
        project_path,
        session_id,
        "user",
        f"let's look at {topic}",
    )
    check_slice_budget(session_id)

    op_name = rng.choice(OP_POOL)
    conv.append_turn(
        project_path,
        session_id,
        "assistant",
        f"proposing {op_name} over the relevant columns for {topic}.",
        tool_calls=[{"name": op_name}],
    )
    check_slice_budget(session_id)

    # -- L1 ledger row -----------------------------------------------------
    ledger.record_op_run(
        project_path,
        op_name=op_name,
        input_content_hashes=[f"h{rng.randrange(10_000)}"],
        params_hash=f"p{rng.randrange(10_000)}",
        session_id=session_id,
        runtime_ms=rng.randrange(5, 500),
        output_path=f"output/{session_id}/{op_name}.json",
    )

    # -- L2 digest draft + L3 proposals ------------------------------------
    digest.get_or_create_draft(project_path, session_id)
    next_steps = [{"text": rng.choice(NEXT_STEP_POOL)} for _ in range(2)]

    # Always propose a baseline decision for the session so the L3 table
    # grows at a realistic rate.
    baseline_decision_text = f"prioritize {topic} for the next pass"
    knowledge.propose(
        project_path,
        "decision",
        {"text": baseline_decision_text, "rationale": f"drove the {op_name} run"},
        session_id,
    )
    # Digest decisions mirror the proposal (cite the same text).
    digest_decisions = [{"text": baseline_decision_text}]

    # Plant the special decision in this session if assigned.
    if planted_decision is not None:
        planted_text, _paraphrase = planted_decision
        knowledge.propose(
            project_path,
            "decision",
            {"text": planted_text, "rationale": "planted for recall assertion"},
            session_id,
        )
        digest_decisions.append({"text": planted_text})

    # Occasional fact proposal to exercise that commit path too.
    if rng.random() < 0.4:
        key, value = rng.choice(FACT_POOL)
        knowledge.propose(
            project_path,
            "fact",
            {"key": key, "value": value, "confidence": 0.8},
            session_id,
        )

    # Fill out the draft digest and finalize it.
    digest.update_draft(
        project_path,
        session_id,
        {
            "focus": f"{topic} via {op_name}",
            "next_steps": next_steps,
            "decisions": digest_decisions,
            "surprises": [{"text": "distribution tail heavier than expected"}],
        },
    )
    check_slice_budget(session_id)

    # Commit pending L3 writes and promote the digest (end-of-session ritual).
    knowledge.commit_pending(project_path, session_id)
    digest.finalize(project_path, session_id)
    check_slice_budget(session_id)


def _run_scale(
    tmp_path: Path,
    n_sessions: int,
    budget_tokens: int,
    seed: int,
    *,
    use_vector: bool,
) -> None:
    """Drive the whole simulation and assert all three invariants."""
    rng = random.Random(seed)
    project_path = tmp_path
    _init_project(project_path)

    # Spread planted decisions roughly uniformly across the session range.
    planted_session_indices = set(
        rng.sample(range(n_sessions), k=len(PLANTED))
    )
    planted_order = list(PLANTED)
    rng.shuffle(planted_order)
    planted_plan: dict[int, tuple[str, str]] = {}
    for idx, session_pos in enumerate(sorted(planted_session_indices)):
        planted_plan[session_pos] = planted_order[idx]

    # Track planted mapping: session_id -> (decision_text, paraphrase_query)
    planted_by_session: dict[str, tuple[str, str]] = {}

    def _check_budget(session_id: str) -> None:
        s = slice_builder.build_slice(project_path, budget_tokens=budget_tokens)
        assert s.used_tokens <= budget_tokens, (
            f"pinned slice exceeded budget at session {session_id}: "
            f"{s.used_tokens} > {budget_tokens}"
        )

    for i in range(n_sessions):
        session_id = f"sess-{i:04d}"
        planted = planted_plan.get(i)
        if planted is not None:
            planted_by_session[session_id] = planted
        _make_session(
            project_path,
            session_id,
            rng,
            planted,
            _check_budget,
            budget_tokens,
        )

    assert len(planted_by_session) == len(PLANTED)

    # --- recall assertion -------------------------------------------------
    hits_total = len(planted_by_session)
    hits_ok = 0
    k = 5
    for session_id, (planted_text, paraphrase_query) in planted_by_session.items():
        hits = recall.recall(
            project_path, paraphrase_query, k=k, use_vector=use_vector
        )
        if any(planted_text in h.text for h in hits):
            hits_ok += 1
    recall_rate = hits_ok / hits_total
    assert recall_rate >= 0.9, (
        f"recall success rate {recall_rate:.2%} below 90% "
        f"(hits {hits_ok}/{hits_total}); sample failures indicate BM25 + "
        f"recency is not surfacing the planted rows."
    )

    # --- slice-build latency ---------------------------------------------
    # Warm-up to pay any lazy tokenizer load cost (tiktoken import, etc.)
    for _ in range(5):
        slice_builder.build_slice(project_path, budget_tokens=budget_tokens)

    timings_ms: list[float] = []
    for _ in range(200):
        t0 = time.perf_counter()
        slice_builder.build_slice(project_path, budget_tokens=budget_tokens)
        timings_ms.append((time.perf_counter() - t0) * 1000.0)
    # statistics.quantiles with n=20 gives 19 cutpoints; index 18 ≈ p95.
    p95 = statistics.quantiles(timings_ms, n=20, method="inclusive")[18]
    assert p95 < 150.0, (
        f"slice-build p95 latency {p95:.1f} ms exceeds 150 ms budget "
        f"(median={statistics.median(timings_ms):.1f} ms, "
        f"max={max(timings_ms):.1f} ms)"
    )


# -- tests -----------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_embedding_provider():
    """Each test starts with a fresh provider cache + deterministic env."""
    embeddings.reset_provider_for_tests()
    prev = os.environ.get("IRIS_EMBED_PROVIDER")
    os.environ["IRIS_EMBED_PROVIDER"] = "disabled"
    try:
        yield
    finally:
        if prev is None:
            os.environ.pop("IRIS_EMBED_PROVIDER", None)
        else:
            os.environ["IRIS_EMBED_PROVIDER"] = prev
        embeddings.reset_provider_for_tests()


def test_smoke_20_sessions(tmp_path: Path):
    """Smoke run: 20 sessions, BM25-only recall, fast default-suite check."""
    _run_scale(
        tmp_path,
        n_sessions=20,
        budget_tokens=slice_builder.DEFAULT_BUDGET_TOKENS,
        seed=20260413,
        use_vector=False,
    )


@pytest.mark.slow
def test_full_200_sessions(tmp_path: Path):
    """Full §13.8 walkthrough: 200 sessions, embeddings if configured."""
    # If sentence-transformers is available we exercise the vector path too;
    # otherwise `recall()` degrades to BM25 + recency, which is still the
    # production behavior for users who haven't opted in to embeddings.
    use_vector = False
    try:
        import sentence_transformers  # noqa: F401

        os.environ["IRIS_EMBED_PROVIDER"] = "sentence-transformers"
        embeddings.reset_provider_for_tests()
        use_vector = True
    except ImportError:
        pass

    _run_scale(
        tmp_path,
        n_sessions=200,
        budget_tokens=slice_builder.DEFAULT_BUDGET_TOKENS,
        seed=20260413,
        use_vector=use_vector,
    )
