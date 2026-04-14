"""Three-stage memory retrieval (spec §8, §11.5).

V1 pipeline for pulling the most relevant active memory entries for a
user query, using only SQLite + FTS5 BM25 + simple math — no embeddings,
no external deps.

Pipeline
--------
1. **Gate** — :func:`should_retrieve` decides whether recall is worth the
   latency. Cheap heuristic on the raw query string (spec §11.5: avoid
   over-retrieving for trivial turns like "thanks" or "ok").
2. **Structured filter** — SQL narrows to rows matching
   ``project_id`` + ``status='active'`` (+ optional ``memory_type`` list).
3. **FTS5 BM25** — the filtered candidate set is intersected with
   ``memory_entries_fts MATCH query`` and ranked by BM25.
4. **Triple-weighted rerank** — combine normalized BM25 relevance,
   importance, and recency into a single score per spec §8:

       score = α·bm25_norm + β·importance_norm + γ·recency

   with ``α=0.5, β=0.3, γ=0.2`` by default.

Side effect: :func:`memory_entries.touch` is called on each returned row
so ``access_count`` / ``last_accessed_at`` stay fresh for future ranking
and for the Phase 17 retrieval-metrics sweep.

Public API
----------
- :func:`should_retrieve`
- :func:`recall`
"""

from __future__ import annotations

import math
import re
import sqlite3
from datetime import UTC, datetime
from typing import Any, Final

from iris.projects import memory_entries as memory_entries_mod

__all__ = [
    "ALPHA_BM25",
    "BETA_IMPORTANCE",
    "GAMMA_RECENCY",
    "RECALL_KEYWORDS",
    "RECENCY_HALF_LIFE_DAYS",
    "TOKEN_GATE_THRESHOLD",
    "recall",
    "should_retrieve",
]

# -- gate tunables ----------------------------------------------------------

# Tokenized query length at or above which we always retrieve, regardless
# of keyword content. Short greetings ("thanks", "ok", "got it") fall
# below this and skip the DB round-trip.
TOKEN_GATE_THRESHOLD: Final[int] = 8

# Recall-ish phrases that force retrieval even on short queries. Matched
# case-insensitively as substrings so "What did we decide?" hits on
# "what did". Tuned conservatively — adding phrases is cheap, but every
# entry here widens the over-retrieval surface (spec §11.5).
RECALL_KEYWORDS: Final[tuple[str, ...]] = (
    "remember",
    "earlier",
    "before",
    "last time",
    "what did",
    "recall",
    "previously",
    "we found",
    "we decided",
    "we concluded",
)

_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"\w+")

# -- scoring tunables -------------------------------------------------------

# Triple-weighted rerank coefficients from spec §8. Sum to 1.0 by
# convention so the final score stays in roughly [0, 1]; callers that
# need a different mix can read these and compose their own call to
# :func:`_rerank` (not public today).
ALPHA_BM25: Final[float] = 0.5
BETA_IMPORTANCE: Final[float] = 0.3
GAMMA_RECENCY: Final[float] = 0.2

# Half-life for the recency component. Memories older than this lose half
# their recency weight; after ~3 half-lives the recency term is noise.
# Project config can override this at the call site in Phase 9.2.
RECENCY_HALF_LIFE_DAYS: Final[float] = 30.0

# Importance is stored on a 0–10 scale (see schema.sql CHECK on
# ``memory_entries.importance``). Dividing by 10 normalizes to [0, 1].
_IMPORTANCE_MAX: Final[float] = 10.0


# -- gate -------------------------------------------------------------------


def should_retrieve(query: str) -> bool:
    """Return True if ``query`` is worth a memory-retrieval round-trip.

    Two cheap rules:

    1. Token count >= :data:`TOKEN_GATE_THRESHOLD` — a long-enough
       question is almost always worth grounding in prior memory.
    2. Query contains any phrase in :data:`RECALL_KEYWORDS` — explicit
       recall-ish intent trumps length.

    The gate is intentionally lossy on the false-negative side (spec
    §11.5): we'd rather skip retrieval for a borderline one-liner than
    ground every "thanks" in retrieved memories.
    """
    if not query:
        return False
    tokens = _TOKEN_RE.findall(query)
    if len(tokens) >= TOKEN_GATE_THRESHOLD:
        return True
    lowered = query.lower()
    return any(kw in lowered for kw in RECALL_KEYWORDS)


# -- helpers ----------------------------------------------------------------


def _parse_iso(ts: str | None) -> datetime | None:
    """Parse an ISO-8601 ``Z``-suffixed timestamp into an aware datetime."""
    if not ts:
        return None
    # memory_entries writes ``...Z`` via strftime; swap for ``+00:00`` so
    # ``fromisoformat`` accepts it on Python < 3.11 behavior baselines.
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _recency_weight(created_at: str | None, *, now: datetime) -> float:
    """Exponential-decay recency weight in ``[0, 1]``.

    ``exp(-Δdays / half_life)`` — a freshly-created memory scores 1.0; a
    memory one half-life old scores 0.5; older rows asymptote to 0.
    """
    ts = _parse_iso(created_at)
    if ts is None:
        return 0.0
    delta_days = max(0.0, (now - ts).total_seconds() / 86_400.0)
    return math.exp(-delta_days / RECENCY_HALF_LIFE_DAYS)


def _normalize_bm25(bm25_scores: list[float]) -> list[float]:
    """Map FTS5 BM25 scores (lower = better, negative) onto ``[0, 1]``.

    FTS5's ``bm25()`` returns negative log-probabilities where smaller
    numbers mean better matches. We flip the sign and min-max normalize
    within the candidate set so the best hit is 1.0 and the worst is 0.0.
    """
    if not bm25_scores:
        return []
    flipped = [-s for s in bm25_scores]
    lo = min(flipped)
    hi = max(flipped)
    span = hi - lo
    if span <= 0.0:
        # All scores tied — return a uniform 1.0 so the rerank falls
        # back cleanly to importance + recency.
        return [1.0] * len(flipped)
    return [(v - lo) / span for v in flipped]


# -- recall -----------------------------------------------------------------


def recall(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    query: str,
    limit: int = 10,
    types: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Three-stage retrieval: SQL filter → FTS5 BM25 → triple-weighted rerank.

    Parameters
    ----------
    conn
        Project ``iris.sqlite`` connection.
    project_id
        Scopes both the structured filter and (via join) the FTS hits.
    query
        Raw FTS5 query. Callers should sanitize user input; this function
        does not quote-wrap so FTS5 operators stay usable.
    limit
        Maximum rows to return after rerank.
    types
        Optional allow-list of ``memory_type`` values. ``None`` = no
        filter. Unknown types raise :class:`ValueError` to catch typos
        early.

    Returns
    -------
    list of dicts — each the standard memory-entry shape from
    :mod:`memory_entries`, plus four extra keys exposing the score
    breakdown: ``bm25_raw``, ``bm25_norm``, ``recency``, and ``score``.
    Ordered by descending ``score``.

    Side effects
    ------------
    Calls :func:`memory_entries.touch` on every returned memory so
    ``access_count`` and ``last_accessed_at`` stay current for future
    ranking passes.
    """
    if types is not None:
        unknown = [t for t in types if t not in memory_entries_mod.MEMORY_TYPES]
        if unknown:
            raise ValueError(
                f"unknown memory_type(s) {unknown!r}; "
                f"expected subset of {sorted(memory_entries_mod.MEMORY_TYPES)}"
            )

    # Stage 1+2 in a single SQL statement: FTS5 MATCH joined to the base
    # table with the structured filters inlined. Over-fetch (limit * 5,
    # capped) so stage 3's rerank has enough signal to reorder.
    fetch_cap = max(limit * 5, 20)

    clauses = ["me.project_id = ?", "me.status = 'active'"]
    params: list[Any] = [project_id]
    if types:
        placeholders = ",".join("?" for _ in types)
        clauses.append(f"me.memory_type IN ({placeholders})")
        params.extend(types)

    sql = (
        "SELECT me.memory_id, me.project_id, me.scope, me.dataset_id, "
        "me.memory_type, me.text, me.importance, me.confidence, me.status, "
        "me.created_at, me.last_validated_at, me.last_accessed_at, "
        "me.access_count, me.evidence_json, me.tags, me.superseded_by, "
        "bm25(memory_entries_fts) AS bm25_score "
        "FROM memory_entries_fts "
        "JOIN memory_entries me ON me.rowid = memory_entries_fts.rowid "
        f"WHERE memory_entries_fts MATCH ? AND {' AND '.join(clauses)} "
        "ORDER BY bm25_score ASC "
        "LIMIT ?"
    )
    rows = conn.execute(sql, (query, *params, fetch_cap)).fetchall()

    if not rows:
        return []

    # Stage 3: triple-weighted rerank. Build parallel arrays of raw BM25
    # scores and recency weights, normalize BM25 across the candidate
    # set, then combine with importance/10.
    now = datetime.now(UTC)
    bm25_raw = [float(r[16]) for r in rows]
    bm25_norm = _normalize_bm25(bm25_raw)

    scored: list[dict[str, Any]] = []
    for idx, r in enumerate(rows):
        base = memory_entries_mod._row_to_dict(r[:16])  # noqa: SLF001
        importance = float(r[6] or 0.0)
        created_at = r[9]
        imp_norm = max(0.0, min(1.0, importance / _IMPORTANCE_MAX))
        rec = _recency_weight(created_at, now=now)
        score = ALPHA_BM25 * bm25_norm[idx] + BETA_IMPORTANCE * imp_norm + GAMMA_RECENCY * rec
        base["bm25_raw"] = bm25_raw[idx]
        base["bm25_norm"] = bm25_norm[idx]
        base["recency"] = rec
        base["score"] = score
        scored.append(base)

    scored.sort(key=lambda d: d["score"], reverse=True)
    top = scored[:limit]

    # Side-effect: touch each returned memory. Keep it outside the
    # candidate loop so the ordering/scoring logic stays pure.
    for entry in top:
        memory_entries_mod.touch(conn, entry["memory_id"])

    return top
