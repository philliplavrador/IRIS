"""L0 conversation — append-only JSONL per session.

The substrate for everything else. L0 writes are automatic, never gated,
and must never be lost. See §3.1.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

CONV_DIRNAME = "conversations"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def conversations_dir(project_path: Path) -> Path:
    d = Path(project_path) / CONV_DIRNAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def session_path(project_path: Path, session_id: str) -> Path:
    return conversations_dir(project_path) / f"{session_id}.jsonl"


def append_turn(
    project_path: Path,
    session_id: str,
    role: str,
    text: str,
    *,
    tool_calls: Optional[list] = None,
    tool_results: Optional[list] = None,
    timestamp: Optional[str] = None,
) -> int:
    """Append one turn. Returns the turn index within the session (0-based)."""
    if role not in ("user", "assistant", "system", "tool"):
        raise ValueError(f"invalid role {role!r}")
    path = session_path(project_path, session_id)
    entry = {
        "ts": timestamp or _now(),
        "role": role,
        "text": text,
    }
    if tool_calls:
        entry["tool_calls"] = tool_calls
    if tool_results:
        entry["tool_results"] = tool_results

    existing = 0
    if path.is_file():
        # Cheap line count for the returned turn index.
        with open(path, "rb") as f:
            existing = sum(1 for _ in f)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, separators=(",", ":")) + "\n")
    return existing


def read_conversation(
    project_path: Path,
    session_id: str,
    turn_range: Optional[str] = None,
) -> list[dict]:
    """Read turns. ``turn_range`` is ``"a:b"`` (Python slice) or None for all."""
    path = session_path(project_path, session_id)
    if not path.is_file():
        return []
    turns: list[dict] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                turns.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    if turn_range:
        a, _, b = turn_range.partition(":")
        i = int(a) if a else 0
        j = int(b) if b else len(turns)
        turns = turns[i:j]
    return turns


def list_sessions(project_path: Path) -> list[str]:
    d = conversations_dir(project_path)
    return sorted(p.stem for p in d.glob("*.jsonl"))
