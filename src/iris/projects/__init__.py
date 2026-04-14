"""Project workspace management for IRIS.

A project is a durable analysis workspace under ``projects/<name>/`` that
bundles uploaded datasets, artifacts, per-project config, versioned
operations, and the full memory system (SQLite + content-addressed FS +
curated Markdown). Projects are gitignored except for ``TEMPLATE/``,
``projects/README.md``, and ``projects/CLAUDE.md``.

The active project is tracked via ``.iris/active_project`` (an untracked
file at the repo root containing a single project name).

See ``docs/memory-restructure.md`` §6 for the filesystem contract and
``src/iris/projects/CLAUDE.md`` for the module map.
"""

from __future__ import annotations

import json as _json
import re
import shutil
import sys
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from iris.config import find_project_root
from iris.projects import db as _db

# -- constants --------------------------------------------------------------

PROJECTS_DIRNAME = "projects"
TEMPLATE_NAME = "TEMPLATE"
ACTIVE_POINTER_REL = Path(".iris") / "active_project"
CONFIG_FILENAME = "config.toml"
OUTPUT_DIRNAME = "artifacts"  # content-addressed artifact store (spec §6)
CACHE_DIRNAME = "indexes"  # runtime indexes (spec §6)
USER_REFS_DIRNAME = "user_references"
CLAUDE_REFS_DIRNAME = "claude_references"

_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")

__all__ = [
    "ProjectInfo",
    "CachedPlot",
    "project_root",
    "active_project_path",
    "project_output_dir",
    "project_cache_dir",
    "resolve_active_project",
    "set_active_project",
    "open_project",
    "close_project",
    "create_project",
    "delete_project",
    "list_projects",
    "get_project_config",
    "find_cached_plots",
    "add_reference",
    "list_references",
]


# -- data classes -----------------------------------------------------------


@dataclass(frozen=True)
class ProjectInfo:
    """Summary row for ``iris project list``."""

    name: str
    path: Path
    created_at: str | None
    description: str | None
    n_references: int
    n_outputs: int


# -- path helpers -----------------------------------------------------------


def project_root() -> Path:
    """Return the absolute path of ``projects/`` under the IRIS repo root.

    Walks up from CWD looking for ``pyproject.toml`` (delegating to
    :func:`iris.config.find_project_root`). The projects directory is
    created if it doesn't exist so callers can rely on its presence.
    """
    root = find_project_root()
    projects = root / PROJECTS_DIRNAME
    projects.mkdir(parents=True, exist_ok=True)
    return projects


def active_project_path() -> Path:
    """Return the absolute path to ``.iris/active_project`` (may not exist)."""
    return find_project_root() / ACTIVE_POINTER_REL


def project_output_dir(project_path: Path) -> Path:
    """Return ``<project>/artifacts`` (ensures exists).

    Under the new spec §6 layout, content-addressed outputs live in
    ``artifacts/``; legacy callers asking for an "output dir" are routed
    here for now.
    """
    out = project_path / OUTPUT_DIRNAME
    out.mkdir(parents=True, exist_ok=True)
    return out


def project_cache_dir(project_path: Path) -> Path:
    """Return ``<project>/indexes`` (runtime index dir, ensures exists)."""
    cache = project_path / CACHE_DIRNAME
    cache.mkdir(parents=True, exist_ok=True)
    return cache


# -- active project ---------------------------------------------------------


def resolve_active_project() -> Path | None:
    """Return the absolute path of the active project, or ``None`` if none set.

    Reads ``.iris/active_project`` and validates the named project still
    exists on disk. If the pointer file exists but the named project is
    missing, prints a warning to stderr and returns ``None`` (does not raise).
    """
    pointer = active_project_path()
    if not pointer.is_file():
        return None
    try:
        name = pointer.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not name:
        return None
    candidate = project_root() / name
    if not candidate.is_dir():
        print(
            f"warning: active project '{name}' no longer exists at {candidate}; "
            f"clearing pointer with `iris project close` is recommended.",
            file=sys.stderr,
        )
        return None
    return candidate


def set_active_project(name: str) -> Path:
    """Mark ``name`` as the active project. Returns the project path.

    Raises ``FileNotFoundError`` if the project does not exist. Creates
    ``.iris/`` if needed and writes the bare project name so the pointer
    stays portable across clones.
    """
    _validate_name(name)
    path = project_root() / name
    if not path.is_dir():
        raise FileNotFoundError(f"project not found: {path}")
    pointer = active_project_path()
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text(name + "\n", encoding="utf-8")
    return path


def open_project(name: str) -> Path:
    """Validate that ``name`` exists, mark it active, and return the path.

    Historically this set the active-project pointer as a side effect; that
    behavior is preserved so existing CLI/daemon callers keep working.
    Phase 1+ callers that want pure validation should use
    :func:`set_active_project` directly (same behavior) or reach for
    ``project_root() / name`` and check ``is_dir()``.
    """
    return set_active_project(name)


def close_project() -> None:
    """Delete the active-project pointer if present (idempotent)."""
    pointer = active_project_path()
    if pointer.is_file():
        pointer.unlink()


# -- lifecycle --------------------------------------------------------------


def create_project(name: str, description: str | None = None) -> Path:
    """Create ``projects/<name>/`` by copying TEMPLATE. Returns the new path.

    Steps:
      1. Validate the name against ``[a-zA-Z0-9_-]{1,64}``.
      2. ``shutil.copytree`` TEMPLATE → ``projects/<name>/``.
      3. Patch the new project's ``config.toml`` with name + description +
         creation timestamp.
      4. ``db.connect()`` + ``db.init_schema()`` so ``iris.sqlite`` exists
         with the V1 schema before the caller returns.

    Raises ``FileExistsError`` if the project already exists. Does NOT
    set the new project as active.
    """
    _validate_name(name)
    if name == TEMPLATE_NAME:
        raise ValueError(f"'{TEMPLATE_NAME}' is reserved; pick another name")

    projects = project_root()
    template = projects / TEMPLATE_NAME
    if not template.is_dir():
        raise FileNotFoundError(f"TEMPLATE missing at {template}; cannot create new projects")

    dest = projects / name
    if dest.exists():
        raise FileExistsError(f"project already exists: {dest}")

    shutil.copytree(template, dest)

    # Patch the per-project config.toml with identity fields.
    cfg_path = dest / CONFIG_FILENAME
    _patch_project_toml_identity(
        cfg_path,
        name=name,
        description=description or "",
        created_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )

    # Initialise iris.sqlite with the V1 schema.
    conn = _db.connect(dest)
    try:
        _db.init_schema(conn)
    finally:
        conn.close()

    return dest


def delete_project(name: str) -> None:
    """Delete ``projects/<name>/`` and all its contents.

    Clears the active-project pointer if it pointed at ``name``. Raises
    ``FileNotFoundError`` if the project does not exist. Refuses to
    delete ``TEMPLATE``.
    """
    _validate_name(name)
    if name == TEMPLATE_NAME:
        raise ValueError(f"refusing to delete reserved directory '{TEMPLATE_NAME}'")
    path = project_root() / name
    if not path.is_dir():
        raise FileNotFoundError(f"project not found: {path}")
    shutil.rmtree(path)
    # Clear the active pointer if it still points at this project.
    pointer = active_project_path()
    if pointer.is_file():
        try:
            current = pointer.read_text(encoding="utf-8").strip()
        except OSError:
            current = ""
        if current == name:
            pointer.unlink()


def list_projects() -> list[ProjectInfo]:
    """Return all projects under ``projects/`` (excluding TEMPLATE), sorted by name."""
    projects = project_root()
    infos: list[ProjectInfo] = []
    for child in sorted(projects.iterdir(), key=lambda p: p.name):
        if not child.is_dir():
            continue
        if child.name == TEMPLATE_NAME:
            continue
        if child.name.startswith("."):
            continue
        infos.append(_describe_project(child))
    return infos


def get_project_config(name_or_path: str | Path) -> dict:
    """Load a project's ``config.toml`` and return the parsed mapping.

    Accepts a project name (looked up under projects/) or a Path. Returns
    an empty dict if the file is missing. Does NOT merge with global config;
    that is :func:`iris.config.apply_project_overrides`.

    The returned dict flattens a couple of common ``[project]`` fields to
    the top level (``name``, ``description``, ``created_at``) so legacy
    callers that expect the old ``claude_config.yaml`` top-level keys keep
    working.
    """
    if isinstance(name_or_path, Path):
        path = name_or_path
    else:
        path = project_root() / name_or_path
    cfg_path = path / CONFIG_FILENAME
    if not cfg_path.is_file():
        return {}
    try:
        with cfg_path.open("rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    project_section = data.get("project")
    if not isinstance(project_section, dict):
        project_section = {}
    # Promote identity fields to the top level for legacy consumers.
    for key in ("name", "description", "created_at"):
        if key in project_section and key not in data:
            data[key] = project_section[key]
    return data


# -- plot-level dedup cache -------------------------------------------------


@dataclass(frozen=True)
class CachedPlot:
    """A plot that already exists in the project artifact/output and matches a query."""

    plot_path: Path
    sidecar_path: Path
    session_dir: Path
    dsl: str
    window_ms: tuple[float, float] | None
    timestamp: str
    ops: list


def _file_fingerprints_for_paths(paths_cfg: dict) -> dict[str, dict]:
    """Return {key: {path, mtime, size}} for every file path in paths_cfg."""
    skip = {"output_dir", "cache_dir"}
    out: dict[str, dict] = {}
    for key, value in paths_cfg.items():
        if key in skip or not value:
            continue
        p = Path(value)
        if p.is_file():
            stat = p.stat()
            out[key] = {
                "path": str(p),
                "mtime": stat.st_mtime,
                "size": stat.st_size,
            }
        elif p.is_dir():
            out[key] = {"path": str(p), "kind": "directory"}
        else:
            out[key] = {"path": str(p), "missing": True}
    return out


def _fingerprints_match(
    sidecar_sources: dict,
    current_sources: dict,
    tolerance_s: float = 1.0,
) -> bool:
    """Compare two file-fingerprint dicts for equality."""
    if set(sidecar_sources) != set(current_sources):
        return False
    for key in sidecar_sources:
        a = sidecar_sources[key] or {}
        b = current_sources[key] or {}
        if a.get("missing") != b.get("missing"):
            return False
        if a.get("kind") != b.get("kind"):
            return False
        if "size" in a or "size" in b:
            if a.get("size") != b.get("size"):
                return False
            if abs(float(a.get("mtime", 0)) - float(b.get("mtime", 0))) > tolerance_s:
                return False
    return True


def _window_matches(sidecar_window, current_window) -> bool:
    """Compare a sidecar's stored ``window_ms`` against a query window."""
    if current_window in (None, "full"):
        return True
    if sidecar_window is None:
        return False
    if not isinstance(sidecar_window, (list, tuple)) or len(sidecar_window) != 2:
        return False
    if not isinstance(current_window, (list, tuple)) or len(current_window) != 2:
        return False
    return (
        abs(float(sidecar_window[0]) - float(current_window[0])) < 1e-6
        and abs(float(sidecar_window[1]) - float(current_window[1])) < 1e-6
    )


def find_cached_plots(
    project_path: Path,
    dsl: str,
    paths_cfg: dict,
    window_ms,
) -> list[CachedPlot]:
    """Scan the project's output/ for plots whose sidecar matches the query.

    Searches both the legacy ``output/`` location (pre-REVAMP projects)
    and the new ``artifacts/`` location (spec §6). Matches a sidecar iff:

      1. sidecar["dsl"] equals ``dsl`` (literal string comparison)
      2. sidecar["window_ms"] equals ``window_ms``
      3. sidecar["sources"] file fingerprints match ``paths_cfg``

    Returns matches newest first.
    """
    project_path = Path(project_path)
    candidates: list[Path] = []
    for sub in ("output", OUTPUT_DIRNAME):
        d = project_path / sub
        if d.is_dir():
            candidates.append(d)
    if not candidates:
        return []

    current_sources = _file_fingerprints_for_paths(paths_cfg)

    matches: list[CachedPlot] = []
    for search_dir in candidates:
        for sidecar in search_dir.rglob("*.json"):
            if sidecar.name == "manifest.json":
                continue
            if not sidecar.name.endswith(".png.json") and not sidecar.name.endswith(".pdf.json"):
                continue
            try:
                data = _json.loads(sidecar.read_text(encoding="utf-8"))
            except (OSError, _json.JSONDecodeError):
                continue
            if not isinstance(data, dict):
                continue
            if data.get("dsl") != dsl:
                continue
            if not _window_matches(data.get("window_ms"), window_ms):
                continue
            if not _fingerprints_match(data.get("sources") or {}, current_sources):
                continue
            plot_path = sidecar.with_suffix("")
            if not plot_path.is_file():
                continue
            matches.append(
                CachedPlot(
                    plot_path=plot_path,
                    sidecar_path=sidecar,
                    session_dir=sidecar.parent,
                    dsl=data["dsl"],
                    window_ms=(
                        tuple(data["window_ms"])
                        if isinstance(data.get("window_ms"), (list, tuple))
                        else data.get("window_ms")
                    ),
                    timestamp=data.get("timestamp", ""),
                    ops=data.get("ops") or [],
                )
            )

    matches.sort(
        key=lambda m: (m.timestamp, m.sidecar_path.stat().st_mtime),
        reverse=True,
    )
    return matches


# -- references -------------------------------------------------------------
#
# Pre-REVAMP projects kept lightweight markdown stubs under
# ``claude_references/`` and ``user_references/``. The new memory layer
# (Phase 4+) replaces these with curated ``memory_entries`` rows; until
# those land, the helpers below still work for any caller that uses them,
# creating the directories on demand.

_REFERENCE_SOURCES: tuple[str, ...] = ("web", "user", "claude")
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def add_reference(
    project_path: Path,
    url_or_path: str,
    source: str,
    summary: str,
    tags: list[str] | None = None,
    title: str | None = None,
) -> Path:
    """Record a reference stub under ``claude_references/`` or ``user_references/``.

    See module docstring for the pre/post-REVAMP story. Returns the
    absolute path of the reference record (the stub for web/claude, the
    sidecar for user sources).
    """
    if source not in _REFERENCE_SOURCES:
        raise ValueError(f"source must be one of {_REFERENCE_SOURCES}, got {source!r}")
    project_path = Path(project_path)
    if not project_path.is_dir():
        raise FileNotFoundError(f"project directory not found: {project_path}")

    tags = list(tags) if tags else []
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    if source == "user":
        candidate = Path(url_or_path)
        if not candidate.is_absolute():
            candidate = project_path / USER_REFS_DIRNAME / candidate
        if not candidate.is_file():
            raise FileNotFoundError(
                f"user reference file not found: {candidate}; place it under "
                f"{project_path / USER_REFS_DIRNAME} before adding the reference"
            )
        sidecar = candidate.with_suffix(candidate.suffix + ".ref.md")
        frontmatter = {
            "source": "user",
            "file": candidate.name,
            "title": title or candidate.stem,
            "added_at": now,
            "tags": tags,
            "summary": summary,
        }
        body = f"# {frontmatter['title']}\n\n{summary}\n"
        _write_reference_stub(sidecar, frontmatter, body)
        return sidecar

    refs_dir = project_path / CLAUDE_REFS_DIRNAME
    refs_dir.mkdir(parents=True, exist_ok=True)
    slug_source = title or url_or_path
    slug = _slugify(slug_source)
    stub = refs_dir / f"{slug}.md"
    counter = 2
    while stub.exists():
        stub = refs_dir / f"{slug}-{counter}.md"
        counter += 1

    frontmatter = {
        "source": source,
        "title": title or slug_source,
        "added_at": now,
        "tags": tags,
        "summary": summary,
    }
    if source == "web":
        frontmatter["url"] = url_or_path
    else:
        frontmatter["identifier"] = url_or_path

    body_header = frontmatter["title"]
    body = f"# {body_header}\n\n{summary}\n"
    if source == "claude":
        body += "\n<!-- training-data-derived claim; verify before citing in a report -->\n"
    _write_reference_stub(stub, frontmatter, body)
    return stub


def list_references(project_path: Path) -> list[dict]:
    """Return a flat list of reference records from both references dirs."""
    project_path = Path(project_path)
    records: list[dict] = []

    claude_refs = project_path / CLAUDE_REFS_DIRNAME
    if claude_refs.is_dir():
        for md in sorted(claude_refs.glob("*.md")):
            records.append(_parse_reference_stub(md, default_source="claude"))

    user_refs = project_path / USER_REFS_DIRNAME
    if user_refs.is_dir():
        seen_sidecars: set[Path] = set()
        for sidecar in sorted(user_refs.glob("*.ref.md")):
            seen_sidecars.add(sidecar)
            rec = _parse_reference_stub(sidecar, default_source="user")
            records.append(rec)
        for f in sorted(user_refs.iterdir()):
            if not f.is_file() or f.name == ".gitkeep":
                continue
            if f.name.endswith(".ref.md"):
                continue
            sidecar = f.with_suffix(f.suffix + ".ref.md")
            if sidecar in seen_sidecars:
                continue
            records.append(
                {
                    "path": str(f),
                    "source": "user",
                    "title": f.stem,
                    "file": f.name,
                    "added_at": None,
                    "tags": [],
                    "summary": "(no sidecar metadata)",
                }
            )

    return records


# -- internal helpers -------------------------------------------------------


def _validate_name(name: str) -> None:
    if not isinstance(name, str) or not _NAME_RE.match(name):
        raise ValueError(f"invalid project name {name!r}; must match [a-zA-Z0-9_-]{{1,64}}")


def _describe_project(path: Path) -> ProjectInfo:
    cfg = get_project_config(path)
    # Prefer top-level promotion from get_project_config; fall back to [project].
    project_section_raw = cfg.get("project")
    project_section: dict = project_section_raw if isinstance(project_section_raw, dict) else {}
    created_at = cfg.get("created_at") or project_section.get("created_at")
    description = cfg.get("description") or project_section.get("description") or None
    if description == "":
        description = None

    user_refs = path / USER_REFS_DIRNAME
    claude_refs = path / CLAUDE_REFS_DIRNAME
    n_refs = _count_files(user_refs) + _count_files(claude_refs)

    n_outputs = 0
    for sub in ("output", OUTPUT_DIRNAME):
        d = path / sub
        if d.is_dir():
            n_outputs += sum(1 for _ in d.rglob("plot_*.png")) + sum(
                1 for _ in d.rglob("plot_*.pdf")
            )

    return ProjectInfo(
        name=path.name,
        path=path,
        created_at=created_at,
        description=description,
        n_references=n_refs,
        n_outputs=n_outputs,
    )


def _count_files(directory: Path) -> int:
    if not directory.is_dir():
        return 0
    return sum(
        1
        for p in directory.rglob("*")
        if p.is_file() and p.name != ".gitkeep" and not p.name.endswith(".ref.md")
    )


def _slugify(text: str) -> str:
    """Produce a stable filename slug from a URL or title."""
    stripped = re.sub(r"^[a-z]+://", "", text.lower())
    slug = _SLUG_RE.sub("-", stripped).strip("-")
    if not slug:
        slug = "ref"
    return slug[:60].strip("-") or "ref"


def _write_reference_stub(path: Path, frontmatter: dict, body: str) -> None:
    """Write a markdown file with a YAML-ish frontmatter header.

    We emit a minimal YAML-shaped block by hand; the old implementation
    depended on pyyaml, which Task 0.7 removed as a global dependency.
    The format stays compatible with :func:`_parse_reference_stub`.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["---"]
    for key, value in frontmatter.items():
        lines.append(f"{key}: {_yaml_scalar(value)}")
    lines.append("---")
    lines.append("")
    content = "\n".join(lines) + "\n" + body
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def _yaml_scalar(value) -> str:
    """Serialize a Python scalar/list into a one-line YAML-ish value."""
    if isinstance(value, list):
        if not value:
            return "[]"
        return "[" + ", ".join(_yaml_scalar(v) for v in value) + "]"
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value)
    # Quote if it contains YAML-significant characters.
    if any(ch in text for ch in ":#,[]{}\"'\n") or text in ("", "null", "true", "false"):
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return text


def _parse_reference_stub(path: Path, default_source: str) -> dict:
    """Parse a reference stub's minimal YAML frontmatter into a record dict."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {
            "path": str(path),
            "source": default_source,
            "title": path.stem,
            "added_at": None,
            "tags": [],
            "summary": "(unreadable)",
        }

    frontmatter: dict = {}
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end > 0:
            fm_block = text[4:end]
            for line in fm_block.splitlines():
                if ":" not in line:
                    continue
                key, _, raw = line.partition(":")
                frontmatter[key.strip()] = _parse_yaml_scalar(raw.strip())

    record = {
        "path": str(path),
        "source": frontmatter.get("source", default_source),
        "title": frontmatter.get("title", path.stem),
        "added_at": frontmatter.get("added_at"),
        "tags": frontmatter.get("tags") or [],
        "summary": frontmatter.get("summary", "(no summary)"),
    }
    for key in ("url", "file", "identifier"):
        if key in frontmatter:
            record[key] = frontmatter[key]
    return record


def _parse_yaml_scalar(raw: str):
    """Inverse of :func:`_yaml_scalar` for the subset we emit."""
    if raw == "" or raw == "null":
        return None
    if raw == "true":
        return True
    if raw == "false":
        return False
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        if not inner:
            return []
        return [_parse_yaml_scalar(p.strip()) for p in _split_commas(inner)]
    if len(raw) >= 2 and raw[0] == '"' and raw[-1] == '"':
        return raw[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return raw


def _split_commas(text: str) -> list[str]:
    """Split on commas outside quoted strings (minimal parser)."""
    parts: list[str] = []
    buf: list[str] = []
    in_quotes = False
    escape = False
    for ch in text:
        if escape:
            buf.append(ch)
            escape = False
            continue
        if ch == "\\":
            buf.append(ch)
            escape = True
            continue
        if ch == '"':
            in_quotes = not in_quotes
            buf.append(ch)
            continue
        if ch == "," and not in_quotes:
            parts.append("".join(buf).strip())
            buf = []
            continue
        buf.append(ch)
    if buf:
        parts.append("".join(buf).strip())
    return parts


def _patch_project_toml_identity(
    path: Path,
    *,
    name: str,
    description: str,
    created_at: str,
) -> None:
    """Patch ``[project]`` identity fields in a TEMPLATE-copied config.toml.

    This is a minimal line-oriented rewrite: it finds the ``[project]``
    section (which TEMPLATE guarantees with empty ``name``/``description``
    keys) and replaces those two lines, then appends ``created_at`` if
    absent. No generalised TOML writer — stdlib ``tomllib`` is read-only
    and we don't pull in ``tomli-w`` just for this.
    """
    if not path.is_file():
        # TEMPLATE is malformed — synthesise a minimal config.toml.
        path.write_text(
            f'[project]\nname = "{name}"\ndescription = "{description}"\n'
            f'created_at = "{created_at}"\n',
            encoding="utf-8",
        )
        return

    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    in_project = False
    seen_name = False
    seen_description = False
    seen_created_at = False
    out: list[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_project = stripped == "[project]"
            out.append(line)
            continue
        if in_project:
            # Strip inline comments for matching.
            key_part = line.split("=", 1)[0].strip() if "=" in line else ""
            if key_part == "name" and not seen_name:
                out.append(f'name = "{name}"')
                seen_name = True
                continue
            if key_part == "description" and not seen_description:
                out.append(f'description = "{description}"')
                seen_description = True
                continue
            if key_part == "created_at" and not seen_created_at:
                out.append(f'created_at = "{created_at}"')
                seen_created_at = True
                continue
        out.append(line)

    # If we never saw a [project] section, prepend one.
    if not seen_name and not seen_description:
        prefix = [
            "[project]",
            f'name = "{name}"',
            f'description = "{description}"',
            f'created_at = "{created_at}"',
            "",
        ]
        out = prefix + out
    elif not seen_created_at:
        # Insert created_at right after the project section identity lines.
        patched: list[str] = []
        inserted = False
        in_proj = False
        for line in out:
            patched.append(line)
            s = line.strip()
            if s == "[project]":
                in_proj = True
                continue
            if in_proj and not inserted:
                key_part = line.split("=", 1)[0].strip() if "=" in line else ""
                if key_part == "description":
                    patched.append(f'created_at = "{created_at}"')
                    inserted = True
        if not inserted:
            patched.append(f'created_at = "{created_at}"')
        out = patched

    path.write_text("\n".join(out) + ("\n" if text.endswith("\n") else ""), encoding="utf-8")
