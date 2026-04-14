"""Token-budgeted pinned-slice assembly.

The pinned slice is a *derivation* produced per turn. It is NOT a file on
disk and has no separate source-of-truth. See docs/iris-behavior.md §3.6.

Composition priority (high → low):
1. Active goals (cap at ``goals_active_max``)
2. Last session's digest focus + top-2 next_steps
3. Top decisions (status='active', recency × reference_count)
4. Top learned_facts
5. Confirmed data-profile annotations (never raw stats)
6. User-scoped preferences (if ``use_user_memory``)

The assembler tokenizes each candidate, fills until the budget is reached,
and degrades by dropping the lowest-priority slot first — never by slicing
mid-entry.

A cache copy is written to ``.iris/pinned_slice.cache.md`` per project for
fast reload and human inspection. This is a cache only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from . import digest as _digest
from . import knowledge as _knowledge

DEFAULT_BUDGET_TOKENS = 2000
DEFAULT_GOALS_MAX = 5
CACHE_REL = Path(".iris") / "pinned_slice.cache.md"


# Rough token estimator: ~4 chars/token. Swapped for tiktoken if available.
def _default_tokenizer(text: str) -> int:
    try:
        import tiktoken  # type: ignore

        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:
        return max(1, (len(text) + 3) // 4)


@dataclass
class SliceEntry:
    section: str
    priority: int  # 1 is highest
    text: str
    tokens: int = 0


@dataclass
class PinnedSlice:
    entries: list[SliceEntry] = field(default_factory=list)
    budget: int = DEFAULT_BUDGET_TOKENS
    used_tokens: int = 0
    dropped_sections: list[str] = field(default_factory=list)

    def render(self) -> str:
        """Render to the system-prompt string form."""
        if not self.entries:
            return "(pinned slice is empty)"
        sections: dict[str, list[str]] = {}
        order: list[str] = []
        for e in self.entries:
            if e.section not in sections:
                sections[e.section] = []
                order.append(e.section)
            sections[e.section].append(e.text)
        chunks: list[str] = []
        for name in order:
            header = f"## {name}"
            body = "\n".join(sections[name])
            chunks.append(f"{header}\n{body}")
        return "\n\n".join(chunks)


# -- candidate builders -----------------------------------------------------


def _goal_line(g: dict) -> str:
    return f"- [goal#{g['id']}] {g['text']}"


def _decision_line(d: dict) -> str:
    tag = f" (supersedes #{d['supersedes']})" if d.get("supersedes") else ""
    return f"- [decision#{d['id']}{tag}] {d['text']}"


def _fact_line(f: dict) -> str:
    conf = f" (conf={f['confidence']:.2f})" if f.get("confidence") is not None else ""
    return f"- [fact#{f['id']}] {f['key']}: {f['value']}{conf}"


def _annotation_line(a: dict) -> str:
    return f"- {a['field_path']}: {a.get('annotation') or '(unannotated)'}"


def _digest_lines(d: dict) -> list[str]:
    out = [f"**Focus:** {d.get('focus', '(none)')}"]
    for i, step in enumerate(d.get("next_steps", [])[:2]):
        out.append(f"- [next_step#{step['id']}] {step['text']}")
    return out


# -- main assembler ---------------------------------------------------------


def build_slice(
    project_path: Path,
    *,
    budget_tokens: int = DEFAULT_BUDGET_TOKENS,
    goals_max: int = DEFAULT_GOALS_MAX,
    include_user_memory: bool = False,
    user_memory_text: Optional[str] = None,
    tokenizer: Optional[Callable[[str], int]] = None,
) -> PinnedSlice:
    """Assemble the pinned slice for ``project_path``.

    Priority-ordered fill; if budget is exceeded, drops entries from the
    lowest-priority section onward. Never splits individual entries — an
    over-budget entry is skipped (and its section reported in
    ``dropped_sections``) rather than truncated.
    """
    tok = tokenizer or _default_tokenizer
    slice_ = PinnedSlice(budget=budget_tokens)

    candidates: list[SliceEntry] = []

    # 1. Active goals
    for g in _knowledge.active_goals(project_path, limit=goals_max):
        candidates.append(SliceEntry("Active Goals", 1, _goal_line(g)))

    # 2. Last digest
    latest = _digest.latest_final(project_path)
    if latest:
        for line in _digest_lines(latest):
            candidates.append(SliceEntry("Last Session", 2, line))

    # 3. Active decisions (top 5 by recency)
    for d in _knowledge.active_decisions(project_path, limit=5):
        candidates.append(SliceEntry("Decisions", 3, _decision_line(d)))

    # 4. Recent facts (top 5)
    for f in _knowledge.recent_facts(project_path, limit=5):
        candidates.append(SliceEntry("Facts", 4, _fact_line(f)))

    # 5. Confirmed profile annotations
    for a in _knowledge.confirmed_profile_annotations(project_path):
        candidates.append(SliceEntry("Data Profile", 5, _annotation_line(a)))

    # 6. User preferences (optional)
    if include_user_memory and user_memory_text:
        candidates.append(
            SliceEntry("User Preferences", 6, user_memory_text.strip())
        )

    # Fill under budget, greedy by priority then original order.
    candidates.sort(key=lambda e: e.priority)
    for e in candidates:
        e.tokens = tok(e.text)
        # Account for a small per-entry header overhead (newline joins).
        overhead = 2
        if slice_.used_tokens + e.tokens + overhead > budget_tokens:
            if e.section not in slice_.dropped_sections:
                slice_.dropped_sections.append(e.section)
            continue
        slice_.entries.append(e)
        slice_.used_tokens += e.tokens + overhead

    return slice_


def write_cache(project_path: Path, rendered: str) -> Path:
    """Persist the rendered slice to ``.iris/pinned_slice.cache.md``."""
    cache = Path(project_path) / CACHE_REL
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(rendered, encoding="utf-8")
    return cache


def build_and_cache(project_path: Path, **kwargs) -> tuple[PinnedSlice, str]:
    s = build_slice(project_path, **kwargs)
    rendered = s.render()
    write_cache(project_path, rendered)
    return s, rendered
