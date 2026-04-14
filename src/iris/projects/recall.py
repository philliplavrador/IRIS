"""Hybrid BM25 + vector + recency-boost retrieval — the single primitive
the agent uses to find past context. See docs/iris-behavior.md §3.5.

Index scope:
- L2 digest entries (decisions, surprises, open_questions, next_steps, focus)
- L3 decisions, learned_facts
- ``claude_references/`` reference stubs (title + summary)

Scoring (per §14.3):
    score = 0.6 * similarity + 0.3 * recency_decay + 0.1 * log(1 + ref_count)

``similarity`` = vector cosine if provider is enabled, else BM25 normalized to [0,1].

Recency halflife is configurable per project (``recall_recency_halflife_days``).
When no embedding provider is configured, recall degrades to BM25 + recency —
still useful for exact and near-exact matches, just less paraphrase-robust.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from . import digest as _digest
from . import embeddings as _emb
from . import knowledge as _knowledge

DEFAULT_K = 5
DEFAULT_HALFLIFE_DAYS = 30.0

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


# -- BM25 -------------------------------------------------------------------


@dataclass
class _BM25Index:
    docs: list[list[str]] = field(default_factory=list)
    df: dict[str, int] = field(default_factory=dict)
    avgdl: float = 0.0
    k1: float = 1.5
    b: float = 0.75

    def build(self, tokenized_docs: list[list[str]]) -> None:
        self.docs = tokenized_docs
        self.df = {}
        for doc in tokenized_docs:
            for term in set(doc):
                self.df[term] = self.df.get(term, 0) + 1
        if tokenized_docs:
            self.avgdl = sum(len(d) for d in tokenized_docs) / len(tokenized_docs)

    def score(self, query_terms: list[str], idx: int) -> float:
        if not self.docs:
            return 0.0
        doc = self.docs[idx]
        if not doc:
            return 0.0
        dl = len(doc)
        from collections import Counter

        tf = Counter(doc)
        n = len(self.docs)
        score = 0.0
        for term in query_terms:
            if term not in tf:
                continue
            df = self.df.get(term, 0)
            if df == 0:
                continue
            idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
            numer = tf[term] * (self.k1 + 1)
            denom = tf[term] + self.k1 * (1 - self.b + self.b * dl / (self.avgdl or 1))
            score += idf * numer / denom
        return max(0.0, score)


def _normalize_bm25(scores: list[float]) -> list[float]:
    if not scores:
        return []
    mx = max(scores)
    if mx <= 0:
        return [0.0] * len(scores)
    return [s / mx for s in scores]


# -- recency ----------------------------------------------------------------


def _parse_ts(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        s = s.replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _recency_decay(ts: Optional[str], halflife_days: float, now: datetime) -> float:
    t = _parse_ts(ts)
    if t is None:
        return 0.5  # unknown → neutral
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    age_days = max(0.0, (now - t).total_seconds() / 86400.0)
    return 0.5 ** (age_days / max(0.0001, halflife_days))


# -- candidate corpus -------------------------------------------------------


@dataclass
class Candidate:
    source: str
    row_id: Optional[int]
    session: Optional[str]
    text: str
    timestamp: Optional[str]
    reference_count: int = 0
    citation: str = ""


def _load_corpus(project_path: Path) -> list[Candidate]:
    cands: list[Candidate] = []

    # L3 decisions (all, even superseded — they're auditable history).
    with _knowledge.open_knowledge(project_path) as conn:
        for r in conn.execute("SELECT * FROM decisions"):
            d = dict(r)
            cands.append(
                Candidate(
                    source="decision",
                    row_id=d["id"],
                    session=d.get("created_session"),
                    text=f"{d['text']}\n{d.get('rationale') or ''}".strip(),
                    timestamp=d.get("last_referenced_at") or d.get("created_at"),
                    citation=f"decision#{d['id']}",
                )
            )
        for r in conn.execute("SELECT * FROM learned_facts"):
            f = dict(r)
            cands.append(
                Candidate(
                    source="fact",
                    row_id=f["id"],
                    session=f.get("source_session"),
                    text=f"{f['key']}: {f['value']}",
                    timestamp=f.get("last_referenced_at") or f.get("created_at"),
                    citation=f"fact#{f['id']}",
                )
            )

    # L2 finalized digests
    for dp in _digest.list_finals(project_path):
        try:
            d = _digest.load(dp)
        except Exception:
            continue
        session = d.get("session_id", dp.stem)
        ts = d.get("updated_at") or d.get("created_at")
        if d.get("focus"):
            cands.append(
                Candidate(
                    source="digest.focus",
                    row_id=None,
                    session=session,
                    text=d["focus"],
                    timestamp=ts,
                    citation=f"digest[{session}].focus",
                )
            )
        for k in ("decisions", "surprises", "open_questions", "next_steps"):
            for entry in d.get(k, []):
                cands.append(
                    Candidate(
                        source=f"digest.{k}",
                        row_id=None,
                        session=session,
                        text=entry["text"],
                        timestamp=ts,
                        citation=f"digest[{session}].{k}#{entry['id']}",
                    )
                )

    # References
    refs_dir = Path(project_path) / "claude_references"
    if refs_dir.is_dir():
        for md in sorted(refs_dir.glob("*.md")):
            try:
                text = md.read_text(encoding="utf-8")
            except OSError:
                continue
            cands.append(
                Candidate(
                    source="reference",
                    row_id=None,
                    session=None,
                    text=text[:2000],
                    timestamp=None,
                    citation=f"ref:{md.name}",
                )
            )

    return cands


# -- public API -------------------------------------------------------------


@dataclass
class Hit:
    id: str            # stable citation-key (e.g. "decision#42")
    source: str
    session: Optional[str]
    text: str
    score: float
    citation: str
    timestamp: Optional[str]


def recall(
    project_path: Path,
    query: str,
    k: int = DEFAULT_K,
    filters: Optional[dict] = None,
    halflife_days: float = DEFAULT_HALFLIFE_DAYS,
    *,
    use_vector: bool = True,
    _now: Optional[datetime] = None,
) -> list[Hit]:
    """Return top-k hits for ``query`` across L2/L3/refs.

    ``filters`` supports ``{"source": <source>}`` to scope to one store
    (e.g. ``{"source": "decision"}``). Missing or empty query returns [].
    """
    filters = filters or {}
    if not query or not query.strip():
        return []

    cands = _load_corpus(project_path)
    if filters.get("source"):
        cands = [c for c in cands if c.source.startswith(filters["source"])]
    if not cands:
        return []

    tokenized = [_tokenize(c.text) for c in cands]
    query_terms = _tokenize(query)

    # BM25
    idx = _BM25Index()
    idx.build(tokenized)
    bm25_raw = [idx.score(query_terms, i) for i in range(len(cands))]
    bm25 = _normalize_bm25(bm25_raw)

    # Vector (optional)
    sim_vec: list[float] = [0.0] * len(cands)
    provider = _emb.get_provider() if use_vector else _emb.DisabledProvider()
    if provider.enabled:
        try:
            vecs = provider.embed([c.text for c in cands])
            qv = provider.embed([query])[0]
            if qv is not None:
                for i, v in enumerate(vecs):
                    if v is None:
                        continue
                    sim_vec[i] = _cosine(qv, v)
        except Exception:
            # Degrade silently to BM25-only if the provider breaks mid-query.
            sim_vec = [0.0] * len(cands)

    sim = [max(b, v) for b, v in zip(bm25, sim_vec)]

    # Recency + reference-count
    now = _now or datetime.now(timezone.utc)
    recency = [_recency_decay(c.timestamp, halflife_days, now) for c in cands]
    refcount = [math.log(1 + c.reference_count) for c in cands]

    final = [
        0.6 * sim[i] + 0.3 * recency[i] + 0.1 * refcount[i] for i in range(len(cands))
    ]

    ranked = sorted(range(len(cands)), key=lambda i: final[i], reverse=True)
    out: list[Hit] = []
    for i in ranked[:k]:
        if final[i] <= 0:
            continue
        c = cands[i]
        out.append(
            Hit(
                id=c.citation,
                source=c.source,
                session=c.session,
                text=c.text,
                score=float(final[i]),
                citation=c.citation,
                timestamp=c.timestamp,
            )
        )
    return out


def _cosine(a: Iterable[float], b: Iterable[float]) -> float:
    a = list(a)
    b = list(b)
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)
