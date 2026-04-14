"""Project workspace management for IRIS.

A project is a durable analysis workspace under ``projects/<name>/`` that
bundles references, per-project config, cached outputs, a living report,
and the L0/L1/L2/L3 memory stores. Projects are gitignored except for
``TEMPLATE/`` and ``projects/README.md``.

The active project is tracked via ``.iris/active_project`` (an untracked
file at the repo root containing a single project name). All ``iris run``
invocations require an active project.

See docs/projects.md for the full contract.
"""

from __future__ import annotations

import re
import shutil
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Optional

import yaml

from iris.config import find_project_root

# -- constants --------------------------------------------------------------

PROJECTS_DIRNAME = "projects"
TEMPLATE_NAME = "TEMPLATE"
ACTIVE_POINTER_REL = Path(".iris") / "active_project"
CONFIG_FILENAME = "claude_config.yaml"
REPORT_FILENAME = "report.md"
CACHE_DIRNAME = ".cache"
OUTPUT_DIRNAME = "output"
USER_REFS_DIRNAME = "user_references"
CLAUDE_REFS_DIRNAME = "claude_references"

_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


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
    """Return ``<project>/output`` (ensures exists)."""
    out = project_path / OUTPUT_DIRNAME
    out.mkdir(parents=True, exist_ok=True)
    return out


def project_cache_dir(project_path: Path) -> Path:
    """Return ``<project>/.cache`` (sibling of output/, ensures exists)."""
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


def open_project(name: str) -> Path:
    """Set ``name`` as the active project and return its path.

    Creates ``.iris/`` if needed. Writes the bare project name (not the full
    path) so the pointer stays portable across clones.
    """
    _validate_name(name)
    path = project_root() / name
    if not path.is_dir():
        raise FileNotFoundError(f"project not found: {path}")
    pointer = active_project_path()
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text(name + "\n", encoding="utf-8")
    return path


def close_project() -> None:
    """Delete the active-project pointer if present (idempotent)."""
    pointer = active_project_path()
    if pointer.is_file():
        pointer.unlink()


# -- lifecycle --------------------------------------------------------------


def create_project(name: str, description: str | None = None) -> Path:
    """Create ``projects/<name>/`` by copying TEMPLATE. Returns the new path.

    Raises FileExistsError if the project already exists. Validates the name
    matches ``[a-zA-Z0-9_-]{1,64}``. Fills in ``claude_config.yaml`` with
    the creation timestamp, name, and description. Does NOT set as active.
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

    # Initialize the L1/L3 SQLite stores and ensure the L2 digests dir exists.
    # Schemas live in code (not shipped as binary TEMPLATE files) so migrations
    # are sane. See projects/ledger.py, knowledge.py, digest.py.
    from . import digest as _digest
    from . import knowledge as _knowledge
    from . import ledger as _ledger

    _ledger.init_ledger(dest)
    _knowledge.init_knowledge(dest)
    _digest.digests_dir(dest)

    # Fill in the new project's claude_config.yaml
    cfg_path = dest / CONFIG_FILENAME
    cfg = _load_yaml_or_empty(cfg_path)
    cfg["name"] = name
    cfg["description"] = description
    cfg["created_at"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    _dump_yaml(cfg_path, cfg)

    return dest


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
    """Load ``claude_config.yaml`` from a project and return as a dict.

    Accepts a project name (looked up under projects/) or a Path. Returns
    an empty dict if the file is missing. Does NOT merge with global config;
    that is the job of ``iris.config.apply_project_overrides``.
    """
    if isinstance(name_or_path, Path):
        path = name_or_path
    else:
        path = project_root() / name_or_path
    cfg_path = path / CONFIG_FILENAME
    return _load_yaml_or_empty(cfg_path)


# -- plot-level dedup cache -------------------------------------------------

import json as _json


@dataclass(frozen=True)
class CachedPlot:
    """A plot that already exists in the project output and matches a query."""

    plot_path: Path  # e.g. projects/<name>/output/.../plot_001_*.png
    sidecar_path: Path  # the .json next to it
    session_dir: Path  # the parent session directory
    dsl: str  # the DSL string recorded in the sidecar
    window_ms: tuple[float, float] | None
    timestamp: str  # sidecar's "timestamp" field
    ops: list  # the sidecar's expanded ops list (for display)


def _file_fingerprints_for_paths(paths_cfg: dict) -> dict[str, dict]:
    """Return {key: {path, mtime, size}} for every file path in paths_cfg.

    Mirrors the helper in ``iris.sessions`` without importing it (avoids
    the heavy ``iris.engine`` import chain when all we want is a fingerprint).
    Skips ``output_dir`` and ``cache_dir`` and records directories/missing
    files with a kind tag so comparisons are still meaningful.
    """
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
    """Compare two file-fingerprint dicts for equality.

    Allows a 1-second mtime tolerance (some filesystems round mtimes).
    Requires the same set of keys and, for file entries, the same size and
    (approximately) the same mtime. Directory / missing entries must match
    exactly by kind.
    """
    if set(sidecar_sources) != set(current_sources):
        return False
    for key in sidecar_sources:
        a = sidecar_sources[key] or {}
        b = current_sources[key] or {}
        # Missing markers must match
        if a.get("missing") != b.get("missing"):
            return False
        # Directory markers must match
        if a.get("kind") != b.get("kind"):
            return False
        # If it's a file (has size), compare size + mtime
        if "size" in a or "size" in b:
            if a.get("size") != b.get("size"):
                return False
            if abs(float(a.get("mtime", 0)) - float(b.get("mtime", 0))) > tolerance_s:
                return False
    return True


def _window_matches(sidecar_window, current_window) -> bool:
    """Compare a sidecar's stored ``window_ms`` against a query window.

    Query semantics:
      - ``current_window == "full"`` or ``None``: match any sidecar whose
        sources were identical. This exists because the resolved "full"
        window depends on the recording's duration, which we cannot compute
        without loading the file. Since this check is called AFTER the
        sources-fingerprint filter, any sidecar that passes the sources
        check must have been generated from the same data — and therefore
        "full" against that data resolves to the same tuple. A false
        positive is only possible if a previous run used an explicit
        partial window that happened to match; the caller prints the
        sidecar's stored window so the user can verify.
      - ``current_window == [start, end]``: require literal equality with
        the sidecar's stored ``window_ms`` (within 1e-6 tolerance).
    """
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

    Matches a sidecar iff:
      1. sidecar["dsl"] equals ``dsl`` (literal string comparison)
      2. sidecar["window_ms"] equals ``window_ms``
      3. sidecar["sources"] file fingerprints (mtime + size) match the
         fingerprints derived from ``paths_cfg``

    This is the user-requested "output folder acts as a cache" behavior:
    identical data + identical operation order + identical params produces
    a cache hit, avoiding duplicate plots. Param equality is guaranteed by
    the DSL string comparison (inline overrides like ``op(low_hz=300)`` are
    part of the DSL, and global-config-level overrides are rejected by the
    fingerprint check when ``configs/ops.yaml`` has changed content-wise).

    Returns a list (typically 0 or 1 entries) of matching cached plots,
    newest first. Does not read the plot image itself — only the sidecars.
    """
    project_path = Path(project_path)
    output_dir = project_path / OUTPUT_DIRNAME
    if not output_dir.is_dir():
        return []

    current_sources = _file_fingerprints_for_paths(paths_cfg)

    matches: list[CachedPlot] = []
    for sidecar in output_dir.rglob("*.json"):
        # Skip non-sidecar jsons (e.g. manifest.json at the session root)
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

        # Plot file is the sidecar path with the trailing .json stripped
        plot_path = sidecar.with_suffix("")  # e.g. "plot_001_x.png"
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

    # Newest first (by sidecar timestamp, falling back to mtime)
    matches.sort(
        key=lambda m: (m.timestamp, m.sidecar_path.stat().st_mtime),
        reverse=True,
    )
    return matches


# -- references -------------------------------------------------------------

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
    """Record a reference in one of the project's references directories.

    - ``source="web"``: ``url_or_path`` is a URL. Writes a stub markdown file
      with YAML frontmatter under ``claude_references/``.
    - ``source="claude"``: a training-data-derived claim. Writes a stub under
      ``claude_references/``; ``url_or_path`` is treated as a short identifier.
    - ``source="user"``: ``url_or_path`` is a path (absolute, or relative to
      ``user_references/``). Writes a sidecar ``<file>.ref.md`` next to the
      file recording metadata. The file itself is NOT copied — the user is
      expected to have placed it there already.

    Returns the absolute path of the reference record (the stub for web/claude
    sources, the sidecar for user sources).
    """
    if source not in _REFERENCE_SOURCES:
        raise ValueError(f"source must be one of {_REFERENCE_SOURCES}, got {source!r}")
    project_path = Path(project_path)
    if not project_path.is_dir():
        raise FileNotFoundError(f"project directory not found: {project_path}")

    tags = list(tags) if tags else []
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    if source == "user":
        # Locate the file the user dropped into user_references/
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

    # web / claude → stub file under claude_references/
    refs_dir = project_path / CLAUDE_REFS_DIRNAME
    refs_dir.mkdir(parents=True, exist_ok=True)
    slug_source = title or url_or_path
    slug = _slugify(slug_source)
    stub = refs_dir / f"{slug}.md"
    counter = 2
    while stub.exists():
        stub = refs_dir / f"{slug}-{counter}.md"
        counter += 1

    frontmatter: dict = {
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
    """Return a flat list of reference records from both references dirs.

    Each record is a dict with keys: ``path``, ``source``, ``title``,
    ``added_at``, ``tags``, ``summary``, and either ``url`` (web), ``file``
    (user), or ``identifier`` (claude). Files without parseable frontmatter
    are included with minimal metadata so raw drops are still visible.
    """
    project_path = Path(project_path)
    records: list[dict] = []

    claude_refs = project_path / CLAUDE_REFS_DIRNAME
    if claude_refs.is_dir():
        for md in sorted(claude_refs.glob("*.md")):
            records.append(_parse_reference_stub(md, default_source="claude"))

    user_refs = project_path / USER_REFS_DIRNAME
    if user_refs.is_dir():
        seen_sidecars: set[Path] = set()
        # First: files with sidecars
        for sidecar in sorted(user_refs.glob("*.ref.md")):
            seen_sidecars.add(sidecar)
            rec = _parse_reference_stub(sidecar, default_source="user")
            records.append(rec)
        # Then: bare files with no sidecar (so the user still sees what's there)
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
    cfg = _load_yaml_or_empty(path / CONFIG_FILENAME)

    user_refs = path / USER_REFS_DIRNAME
    claude_refs = path / CLAUDE_REFS_DIRNAME
    n_refs = _count_files(user_refs) + _count_files(claude_refs)

    output = path / OUTPUT_DIRNAME
    n_outputs = 0
    if output.is_dir():
        n_outputs = sum(1 for _ in output.rglob("plot_*.png")) + sum(
            1 for _ in output.rglob("plot_*.pdf")
        )

    return ProjectInfo(
        name=path.name,
        path=path,
        created_at=cfg.get("created_at"),
        description=cfg.get("description"),
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
    # Strip a URL scheme if present so the slug isn't dominated by "https"
    stripped = re.sub(r"^[a-z]+://", "", text.lower())
    slug = _SLUG_RE.sub("-", stripped).strip("-")
    if not slug:
        slug = "ref"
    return slug[:60].strip("-") or "ref"


def _write_reference_stub(path: Path, frontmatter: dict, body: str) -> None:
    """Write a markdown file with a YAML frontmatter header."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fm_yaml = yaml.safe_dump(frontmatter, sort_keys=False, default_flow_style=False).strip()
    content = f"---\n{fm_yaml}\n---\n\n{body}"
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def _parse_reference_stub(path: Path, default_source: str) -> dict:
    """Parse a reference stub's YAML frontmatter into a record dict."""
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
            try:
                parsed = yaml.safe_load(fm_block)
                if isinstance(parsed, dict):
                    frontmatter = parsed
            except yaml.YAMLError:
                frontmatter = {}

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


def _load_yaml_or_empty(path: Path) -> dict:
    if not path.is_file():
        return {}
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping, got {type(data).__name__}")
    return data


def _dump_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, default_flow_style=False)
    tmp.replace(path)
