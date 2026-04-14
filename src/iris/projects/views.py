"""Regenerated markdown views — human-readable dumps of the SQLite tables.

Views are derived outputs. Users read them; they never edit them. Sources
of truth are ``knowledge.sqlite``, ``ledger.sqlite``, and the L2 digest
JSON files. See §3.7.
"""
from __future__ import annotations

from pathlib import Path

from . import digest as _digest
from . import knowledge as _knowledge

VIEWS_DIRNAME = "views"


def views_dir(project_path: Path) -> Path:
    d = Path(project_path) / VIEWS_DIRNAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def regenerate_history(project_path: Path) -> Path:
    """Rebuild ``views/history.md`` from L3 tables. Overwrites any existing file."""
    out = views_dir(project_path) / "history.md"
    lines: list[str] = ["# History view", ""]
    lines.append("_Regenerated from knowledge.sqlite. Do not edit by hand._")
    lines.append("")

    def emit(title: str, rows: list[dict], fmt):
        lines.append(f"## {title}")
        if not rows:
            lines.append("_none_")
        else:
            for r in rows:
                lines.append(fmt(r))
        lines.append("")

    with _knowledge.open_knowledge(project_path) as conn:
        goals = [dict(r) for r in conn.execute(
            "SELECT * FROM goals ORDER BY status, id DESC"
        )]
        decisions = [dict(r) for r in conn.execute(
            "SELECT * FROM decisions ORDER BY status, id DESC"
        )]
        facts = [dict(r) for r in conn.execute(
            "SELECT * FROM learned_facts ORDER BY id DESC"
        )]
        annots = [dict(r) for r in conn.execute(
            "SELECT * FROM data_profile_fields ORDER BY id ASC"
        )]
        declined = [dict(r) for r in conn.execute(
            "SELECT * FROM declined_suggestions ORDER BY id DESC"
        )]

    emit("Goals", goals, lambda r: f"- [{r['status']}] #{r['id']} {r['text']}")
    emit(
        "Decisions",
        decisions,
        lambda r: (
            f"- [{r['status']}] #{r['id']} {r['text']}"
            + (f" — _supersedes #{r['supersedes']}_" if r.get("supersedes") else "")
            + (f"\n    rationale: {r['rationale']}" if r.get("rationale") else "")
        ),
    )
    emit(
        "Learned facts",
        facts,
        lambda r: f"- #{r['id']} **{r['key']}** = {r['value']}",
    )
    emit(
        "Data profile annotations",
        annots,
        lambda r: f"- {r['field_path']}: {r.get('annotation') or '(unannotated)'}",
    )
    emit(
        "Declined suggestions",
        declined,
        lambda r: f"- #{r['id']} {r['text']}",
    )

    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def regenerate_analysis_log(project_path: Path) -> Path:
    """Rebuild ``views/analysis_log.md`` from L2 digest JSONs, reverse-chrono."""
    out = views_dir(project_path) / "analysis_log.md"
    finals = sorted(
        _digest.list_finals(project_path),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    lines = ["# Analysis log", "", "_Regenerated from digests/*.json._", ""]
    if not finals:
        lines.append("_no completed sessions yet_")
    for path in finals:
        try:
            d = _digest.load(path)
        except Exception:
            continue
        lines.append(f"## Session {d['session_id']} — {d.get('updated_at', '')}")
        lines.append("")
        lines.append(f"**Focus:** {d.get('focus', '(none)')}")
        for key in ("decisions", "surprises", "open_questions", "next_steps"):
            entries = d.get(key, [])
            if not entries:
                continue
            lines.append(f"\n**{key.replace('_', ' ').title()}:**")
            for e in entries:
                lines.append(f"- {e['text']}")
        lines.append("")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def regenerate_all(project_path: Path) -> list[Path]:
    return [regenerate_history(project_path), regenerate_analysis_log(project_path)]
