"""Bidirectional sync between ``memory_entries`` and ``memory/*.md``.

Spec references: §5.1 Store 3 (curated Markdown is a human-auditable view
over the SQLite source of truth), Appendix B Decision Log ("Core memory
format: Dual: DB row + Markdown file — DB for programmatic access; file
for human inspection and editing; sync required but proven pattern").

The DB is the source of truth. Markdown is a regenerated view. User edits
to Markdown become draft proposals via :func:`memory_entries.propose` and
are never auto-committed — the curation ritual is the only path to
``status='active'``.

Layout on disk
--------------
``<project_path>/memory/``::

    PROJECT.md            # H2 sections: Findings / Assumptions / Caveats /
                          #              Open Questions / Preferences
    DECISIONS.md          # decision entries (project scope)
    OPEN_QUESTIONS.md     # open_question entries (project scope, mirrored
                          #   here so users have a single-file inbox)
    DATASETS/<id>.md      # every scope='dataset' entry grouped by type

Each entry is emitted as::

    <!-- memory_id: <id> -->
    - <single-line text>

or, for multi-line text::

    <!-- memory_id: <id> -->
    - first line
      second line
      ...

The comment marker is the round-trip key: :func:`ingest_markdown` reads it
to know which DB row a block corresponds to.

Round-trip semantics
--------------------
* **Unchanged**: marker present in file + DB, text identical → no-op.
* **Edited**: marker present in file + DB, text differs → new draft
  proposal with the same ``memory_type`` / ``scope`` / ``dataset_id``.
  The original row is untouched; the curation ritual can
  :func:`memory_entries.supersede` on commit.
* **New**: block without a marker → new draft proposal. We infer
  ``memory_type`` from the H2 section (or file name) the block lives in.
* **Deleted**: marker in DB but missing from file → we do **not**
  soft-delete the row. Per §5.1 the DB is source of truth and destructive
  ops must go through the curation UI. Instead we append a
  ``memory_update`` event with payload
  ``{"action": "user_delete_requested", "memory_id": <id>}`` so the UI
  can surface the request. Trade-off: the user has to confirm deletes in
  the UI even though they already removed them from the file; this
  prevents a stray editor save from nuking active memory.

Public API
----------
- :func:`regenerate_markdown`
- :func:`ingest_markdown`

TODO: tests for this module live in a follow-up (REVAMP Task 4.4 file list
doesn't cover markdown_sync). Keep round-trip fidelity in mind when
extending: any change to the emitted template must stay parseable by
:func:`ingest_markdown`.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any, Final

from iris.projects import events as events_mod
from iris.projects import memory_entries as me

__all__ = ["ingest_markdown", "regenerate_markdown"]

# -- template constants -----------------------------------------------------

_MEMORY_DIR: Final[str] = "memory"
_DATASETS_DIR: Final[str] = "DATASETS"

# File names.
_PROJECT_FILE: Final[str] = "PROJECT.md"
_DECISIONS_FILE: Final[str] = "DECISIONS.md"
_OPEN_QUESTIONS_FILE: Final[str] = "OPEN_QUESTIONS.md"

# Memory types that live under PROJECT.md, in section order.
# Each entry: (memory_type, section_heading).
_PROJECT_SECTIONS: Final[tuple[tuple[str, str], ...]] = (
    ("finding", "Findings"),
    ("assumption", "Assumptions"),
    ("caveat", "Caveats"),
    ("open_question", "Open Questions"),
    ("preference", "Preferences"),
)

# Reverse index: H2 heading → memory_type. Used by the ingester.
_SECTION_TO_TYPE: Final[dict[str, str]] = {h: t for t, h in _PROJECT_SECTIONS}

# Dataset files: every memory_type gets its own section.
_DATASET_SECTIONS: Final[tuple[tuple[str, str], ...]] = (
    ("finding", "Findings"),
    ("assumption", "Assumptions"),
    ("caveat", "Caveats"),
    ("open_question", "Open Questions"),
    ("decision", "Decisions"),
    ("preference", "Preferences"),
    ("failure_reflection", "Failure Reflections"),
    ("reflection", "Reflections"),
)
_DATASET_SECTION_TO_TYPE: Final[dict[str, str]] = {h: t for t, h in _DATASET_SECTIONS}

_MARKER_RE: Final[re.Pattern[str]] = re.compile(r"<!--\s*memory_id:\s*([0-9a-fA-F]+)\s*-->")
_H2_RE: Final[re.Pattern[str]] = re.compile(r"^##\s+(.+?)\s*$")


# -- helpers ----------------------------------------------------------------


def _fetch_project_id(conn: sqlite3.Connection) -> str:
    """Return the single ``project_id`` in this per-project DB."""
    row = conn.execute("SELECT project_id FROM projects LIMIT 1").fetchone()
    if row is None:
        raise RuntimeError("no project row in this database")
    return row[0]


def _all_active(conn: sqlite3.Connection, project_id: str) -> list[dict[str, Any]]:
    """Active memories across every type, ordered deterministically."""
    # Pull with ``status=None`` + manual filter so we can sort in Python
    # by (memory_type, created_at, memory_id) → deterministic template.
    rows = me.query(
        conn,
        project_id=project_id,
        status="active",
        limit=100_000,
        order_by="created_at ASC",
    )
    rows.sort(key=lambda r: (r["memory_type"], r["created_at"] or "", r["memory_id"]))
    return rows


def _render_entry(entry: dict[str, Any]) -> str:
    """Render one entry as ``<marker>\\n- <text>\\n``.

    Multi-line text is indented with two spaces on continuation lines so a
    single ``- `` bullet still owns the whole block.
    """
    text = (entry["text"] or "").rstrip()
    lines = text.split("\n")
    first, rest = lines[0], lines[1:]
    out = [f"<!-- memory_id: {entry['memory_id']} -->", f"- {first}"]
    for line in rest:
        out.append(f"  {line}")
    return "\n".join(out) + "\n"


def _render_section(heading: str, entries: list[dict[str, Any]]) -> str:
    body = "\n".join(_render_entry(e) for e in entries) if entries else "_None recorded._\n"
    return f"## {heading}\n\n{body}\n"


def _write_if_changed(path: Path, content: str) -> None:
    """Write ``content`` only when it differs from the file on disk.

    Avoids churning mtimes so the file-watcher (Task 4.6) doesn't loop on
    its own regenerations.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        existing = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        existing = None
    if existing != content:
        path.write_text(content, encoding="utf-8")


# -- regenerate (DB → MD) ---------------------------------------------------


def regenerate_markdown(conn: sqlite3.Connection, project_path: Path) -> None:
    """Rewrite ``<project_path>/memory/*.md`` from active memory rows.

    Idempotent: running twice in a row on an unchanged DB leaves files
    byte-identical. Files that no longer correspond to any dataset are
    left alone (we never delete user-facing files here).
    """
    project_id = _fetch_project_id(conn)
    memory_dir = Path(project_path) / _MEMORY_DIR
    datasets_dir = memory_dir / _DATASETS_DIR

    active = _all_active(conn, project_id)

    # -- PROJECT.md (project-scope, no dataset_id) --------------------------
    project_entries = [e for e in active if e["scope"] == "project" and e["dataset_id"] is None]
    by_type: dict[str, list[dict[str, Any]]] = {t: [] for t, _ in _PROJECT_SECTIONS}
    for entry in project_entries:
        if entry["memory_type"] in by_type:
            by_type[entry["memory_type"]].append(entry)

    project_md = ["# Project Memory\n"]
    for mtype, heading in _PROJECT_SECTIONS:
        project_md.append(_render_section(heading, by_type[mtype]))
    _write_if_changed(memory_dir / _PROJECT_FILE, "\n".join(project_md))

    # -- DECISIONS.md -------------------------------------------------------
    decisions = [
        e
        for e in active
        if e["memory_type"] == "decision" and e["scope"] == "project" and e["dataset_id"] is None
    ]
    decisions_md = "# Decisions\n\n" + (
        "\n".join(_render_entry(e) for e in decisions) if decisions else "_None recorded._\n"
    )
    _write_if_changed(memory_dir / _DECISIONS_FILE, decisions_md)

    # -- OPEN_QUESTIONS.md --------------------------------------------------
    open_qs = [
        e
        for e in active
        if e["memory_type"] == "open_question"
        and e["scope"] == "project"
        and e["dataset_id"] is None
    ]
    open_qs_md = "# Open Questions\n\n" + (
        "\n".join(_render_entry(e) for e in open_qs) if open_qs else "_None recorded._\n"
    )
    _write_if_changed(memory_dir / _OPEN_QUESTIONS_FILE, open_qs_md)

    # -- DATASETS/<id>.md ---------------------------------------------------
    dataset_entries: dict[str, list[dict[str, Any]]] = {}
    for entry in active:
        if entry["scope"] == "dataset" and entry["dataset_id"]:
            dataset_entries.setdefault(entry["dataset_id"], []).append(entry)

    for dataset_id, entries in dataset_entries.items():
        per_type: dict[str, list[dict[str, Any]]] = {t: [] for t, _ in _DATASET_SECTIONS}
        for entry in entries:
            if entry["memory_type"] in per_type:
                per_type[entry["memory_type"]].append(entry)
        parts = [f"# Dataset: {dataset_id}\n"]
        for mtype, heading in _DATASET_SECTIONS:
            if per_type[mtype]:
                parts.append(_render_section(heading, per_type[mtype]))
        _write_if_changed(datasets_dir / f"{dataset_id}.md", "\n".join(parts))


# -- ingest (MD → DB drafts) ------------------------------------------------


def _parse_blocks(
    text: str, section_to_type: dict[str, str], default_type: str | None
) -> list[tuple[str | None, str, str]]:
    """Split a markdown file into ``(memory_id_or_None, memory_type, body)`` blocks.

    ``memory_type`` is resolved from the most recent H2 heading via
    ``section_to_type``; if no heading has been seen yet (or the heading
    is unknown), ``default_type`` is used. Blocks with neither a marker
    nor a resolvable type are skipped — we can't round-trip them.
    """
    lines = text.splitlines()
    blocks: list[tuple[str | None, str, str]] = []
    current_type: str | None = default_type
    i = 0
    while i < len(lines):
        line = lines[i]
        h2 = _H2_RE.match(line)
        if h2:
            heading = h2.group(1).strip()
            current_type = section_to_type.get(heading, current_type)
            i += 1
            continue

        marker_match = _MARKER_RE.match(line.strip())
        bullet_match = line.lstrip().startswith("- ")

        if marker_match or bullet_match:
            memory_id = marker_match.group(1) if marker_match else None
            # If we just saw a marker, consume the following bullet.
            if marker_match:
                i += 1
                if i >= len(lines):
                    break
                bullet_line = lines[i]
                if not bullet_line.lstrip().startswith("- "):
                    # Marker without a bullet; skip.
                    continue
            else:
                bullet_line = line

            # Collect bullet + its indented continuation lines.
            body_lines = [bullet_line.lstrip()[2:]]  # strip "- "
            i += 1
            while i < len(lines):
                cont = lines[i]
                if cont.startswith("  ") and not cont.lstrip().startswith("- "):
                    body_lines.append(cont[2:])
                    i += 1
                else:
                    break
            body = "\n".join(body_lines).rstrip()
            if not body or body.startswith("_None recorded._"):
                continue
            if current_type is None:
                # No heading context and no default — unparseable.
                continue
            blocks.append((memory_id, current_type, body))
            continue

        i += 1
    return blocks


def _iter_memory_files(
    memory_dir: Path,
) -> list[tuple[Path, dict[str, str], str | None, str | None]]:
    """Return ``(path, section_to_type, default_type, dataset_id)`` per file."""
    files: list[tuple[Path, dict[str, str], str | None, str | None]] = []
    project_md = memory_dir / _PROJECT_FILE
    if project_md.is_file():
        files.append((project_md, _SECTION_TO_TYPE, None, None))
    decisions_md = memory_dir / _DECISIONS_FILE
    if decisions_md.is_file():
        files.append((decisions_md, {}, "decision", None))
    open_qs_md = memory_dir / _OPEN_QUESTIONS_FILE
    if open_qs_md.is_file():
        files.append((open_qs_md, {}, "open_question", None))
    datasets_dir = memory_dir / _DATASETS_DIR
    if datasets_dir.is_dir():
        for md_file in sorted(datasets_dir.glob("*.md")):
            dataset_id = md_file.stem
            files.append((md_file, _DATASET_SECTION_TO_TYPE, None, dataset_id))
    return files


def ingest_markdown(conn: sqlite3.Connection, project_path: Path) -> list[str]:
    """Scan ``memory/*.md`` for edits and file them as draft proposals.

    Returns the list of new draft ``memory_id``s created. User deletions
    are **not** acted on destructively; they are recorded as
    ``memory_update`` events with payload
    ``{"action": "user_delete_requested"}`` so the curation UI can
    surface them.
    """
    project_id = _fetch_project_id(conn)
    memory_dir = Path(project_path) / _MEMORY_DIR
    if not memory_dir.is_dir():
        return []

    # DB snapshot: active rows keyed by memory_id.
    db_rows = {r["memory_id"]: r for r in _all_active(conn, project_id)}

    new_drafts: list[str] = []
    seen_ids: set[str] = set()

    for path, section_map, default_type, dataset_id in _iter_memory_files(memory_dir):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for memory_id, memory_type, body in _parse_blocks(text, section_map, default_type):
            if memory_id is not None:
                seen_ids.add(memory_id)
                existing = db_rows.get(memory_id)
                if existing is None:
                    # Marker points at a missing (or non-active) row. Treat
                    # as a new draft so the curation UI can decide.
                    scope = "dataset" if dataset_id else "project"
                    new_id = me.propose(
                        conn,
                        project_id=project_id,
                        scope=scope,
                        memory_type=memory_type,
                        text=body,
                        dataset_id=dataset_id,
                    )
                    new_drafts.append(new_id)
                    continue
                if (existing["text"] or "").rstrip() != body:
                    # Edited — propose the new text as a draft. Curation
                    # ritual can supersede the old row on commit.
                    new_id = me.propose(
                        conn,
                        project_id=project_id,
                        scope=existing["scope"],
                        memory_type=existing["memory_type"],
                        text=body,
                        dataset_id=existing["dataset_id"],
                    )
                    new_drafts.append(new_id)
            else:
                # New entry, no marker yet.
                scope = "dataset" if dataset_id else "project"
                new_id = me.propose(
                    conn,
                    project_id=project_id,
                    scope=scope,
                    memory_type=memory_type,
                    text=body,
                    dataset_id=dataset_id,
                )
                new_drafts.append(new_id)

    # User deletions: active DB rows whose marker never showed up in any
    # file. Record a pending request event; do NOT mutate the row.
    for memory_id, row in db_rows.items():
        if memory_id in seen_ids:
            continue
        events_mod.append_event(
            conn,
            project_id=project_id,
            type=events_mod.EVT_MEMORY_UPDATE,
            payload={
                "action": "user_delete_requested",
                "memory_id": memory_id,
                "memory_type": row["memory_type"],
            },
        )

    return new_drafts
