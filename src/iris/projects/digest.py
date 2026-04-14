"""L2 session digest — JSON per session, auto-drafted then user-polished.

Schema: ``{session_id, created_at, updated_at, focus, decisions[],
surprises[], open_questions[], next_steps[]}``. Each list entry has
``{id, text, tags[], refs[]}`` where ``refs`` point at L0 turns or L1
ledger rows.

Lifecycle:
- Drafts live at ``digests/<session_id>.draft.json`` and are written
  continuously throughout the session (auto-draft on each curation-eligible
  event).
- Final digests live at ``digests/<session_id>.json``, promoted from draft
  at session-end via :func:`finalize`.
- Hard-close preserves the draft; next-session-open can resume curation.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

DIGESTS_DIRNAME = "digests"
DRAFT_SUFFIX = ".draft.json"
FINAL_SUFFIX = ".json"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def digests_dir(project_path: Path) -> Path:
    d = Path(project_path) / DIGESTS_DIRNAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def draft_path(project_path: Path, session_id: str) -> Path:
    return digests_dir(project_path) / f"{session_id}{DRAFT_SUFFIX}"


def final_path(project_path: Path, session_id: str) -> Path:
    return digests_dir(project_path) / f"{session_id}{FINAL_SUFFIX}"


# -- skeleton / validation --------------------------------------------------


_LIST_FIELDS = ("decisions", "surprises", "open_questions", "next_steps")


def new_skeleton(session_id: str) -> dict:
    """Return a fresh digest dict with all required keys."""
    now = _now()
    return {
        "session_id": session_id,
        "created_at": now,
        "updated_at": now,
        "focus": "",
        "decisions": [],
        "surprises": [],
        "open_questions": [],
        "next_steps": [],
    }


def _validate(digest: dict) -> None:
    required = {"session_id", "created_at", "updated_at", "focus", *_LIST_FIELDS}
    missing = required - set(digest)
    if missing:
        raise ValueError(f"digest missing keys: {missing}")
    for k in _LIST_FIELDS:
        if not isinstance(digest[k], list):
            raise ValueError(f"digest.{k} must be a list, got {type(digest[k]).__name__}")
        for i, entry in enumerate(digest[k]):
            if not isinstance(entry, dict):
                raise ValueError(f"digest.{k}[{i}] must be a dict")
            for rk in ("id", "text"):
                if rk not in entry:
                    raise ValueError(f"digest.{k}[{i}] missing {rk!r}")


# -- read / write primitives ------------------------------------------------


def load(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    _validate(data)
    return data


def save(path: Path, digest: dict) -> None:
    _validate(digest)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(digest, f, indent=2, sort_keys=False)
    tmp.replace(path)


# -- draft operations -------------------------------------------------------


def get_or_create_draft(project_path: Path, session_id: str) -> dict:
    """Load the existing draft or create a new one."""
    p = draft_path(project_path, session_id)
    if p.is_file():
        return load(p)
    draft = new_skeleton(session_id)
    save(p, draft)
    return draft


def update_draft(project_path: Path, session_id: str, patch: dict) -> dict:
    """Apply a shallow patch to the draft and persist. Returns the new state.

    ``patch`` keys may be ``focus`` (replaces) or any of the list fields
    (appended to). List entries without an ``id`` get one assigned.
    """
    p = draft_path(project_path, session_id)
    digest = load(p) if p.is_file() else new_skeleton(session_id)

    if "focus" in patch:
        if not isinstance(patch["focus"], str):
            raise ValueError("focus must be a string")
        digest["focus"] = patch["focus"]

    for k in _LIST_FIELDS:
        if k in patch:
            entries = patch[k]
            if not isinstance(entries, list):
                raise ValueError(f"{k} patch must be a list")
            for e in entries:
                if not isinstance(e, dict) or "text" not in e:
                    raise ValueError(f"{k} entries must be dicts with 'text'")
                digest[k].append(
                    {
                        "id": e.get("id") or _new_id(),
                        "text": e["text"],
                        "tags": list(e.get("tags") or []),
                        "refs": list(e.get("refs") or []),
                    }
                )

    digest["updated_at"] = _now()
    save(p, digest)
    return digest


def replace_draft(project_path: Path, session_id: str, digest: dict) -> dict:
    """Overwrite the draft wholesale. Used by the curation-ritual UI."""
    digest = dict(digest)
    digest["session_id"] = session_id
    digest.setdefault("created_at", _now())
    digest["updated_at"] = _now()
    for k in _LIST_FIELDS:
        digest.setdefault(k, [])
        for i, e in enumerate(digest[k]):
            if isinstance(e, dict):
                e.setdefault("id", _new_id())
                e.setdefault("tags", [])
                e.setdefault("refs", [])
    digest.setdefault("focus", "")
    save(draft_path(project_path, session_id), digest)
    return digest


# -- finalization -----------------------------------------------------------


def finalize(project_path: Path, session_id: str) -> Path:
    """Promote the draft to the final digest. Returns the final path.

    Idempotent: if the final already exists and no draft is present, returns
    the existing final path. If both exist, the draft overwrites the final
    (user edited during the curation ritual).
    """
    d = draft_path(project_path, session_id)
    f = final_path(project_path, session_id)
    if d.is_file():
        digest = load(d)
        digest["updated_at"] = _now()
        save(f, digest)
        d.unlink()
        return f
    if f.is_file():
        return f
    raise FileNotFoundError(
        f"no draft or final digest for session {session_id!r} at {d.parent}"
    )


def list_finals(project_path: Path) -> list[Path]:
    d = digests_dir(project_path)
    return sorted(
        p for p in d.glob(f"*{FINAL_SUFFIX}") if not p.name.endswith(DRAFT_SUFFIX)
    )


def list_drafts(project_path: Path) -> list[Path]:
    return sorted(digests_dir(project_path).glob(f"*{DRAFT_SUFFIX}"))


def latest_final(project_path: Path) -> Optional[dict]:
    """Return the most recently updated final digest, or None."""
    finals = list_finals(project_path)
    if not finals:
        return None
    finals.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return load(finals[0])


@dataclass
class DraftState:
    """Convenience bundle for UI/agent display of the current draft."""

    session_id: str
    focus: str
    decisions: list = field(default_factory=list)
    surprises: list = field(default_factory=list)
    open_questions: list = field(default_factory=list)
    next_steps: list = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "DraftState":
        return cls(
            session_id=d["session_id"],
            focus=d.get("focus", ""),
            decisions=list(d.get("decisions", [])),
            surprises=list(d.get("surprises", [])),
            open_questions=list(d.get("open_questions", [])),
            next_steps=list(d.get("next_steps", [])),
        )
