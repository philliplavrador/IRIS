"""Tests for ``iris.projects`` lifecycle CRUD (Task 1.6).

Covers the Task 1.6 checklist:
- create produces all spec §6 directories
- create produces ``iris.sqlite`` with all V1 tables
- list excludes TEMPLATE
- open returns the path; raises if missing
- delete removes everything
- active project tracking round-trips

The tests work in an isolated repo-like tmp dir — we seed a fake
``pyproject.toml`` (which :func:`iris.config.find_project_root` anchors on)
plus a ``projects/TEMPLATE/`` copied from the real repo, then
``monkeypatch.chdir`` into that tmp dir so every ``project_root()`` call
resolves inside the sandbox. This keeps the real ``projects/`` tree clean.
"""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

import iris.projects as projects
from iris.projects.db import DB_FILENAME

# Expected spec §6 layout inside a freshly-created project (directories).
EXPECTED_DIRS = (
    "memory",
    "memory/DATASETS",
    "datasets",
    "datasets/raw",
    "datasets/derived",
    "artifacts",
    "ops",
    "indexes",
)

# Expected Markdown skeleton files shipped by TEMPLATE.
EXPECTED_MEMORY_FILES = (
    "memory/PROJECT.md",
    "memory/DECISIONS.md",
    "memory/OPEN_QUESTIONS.md",
)

# The V1 base tables + FTS5 virtual tables we expect to see after init_schema.
EXPECTED_TABLES = {
    "projects",
    "sessions",
    "events",
    "messages",
    "messages_fts",
    "tool_calls",
    "datasets",
    "dataset_versions",
    "artifacts",
    "runs",
    "memory_entries",
    "memory_entries_fts",
    "contradictions",
    "operations",
    "operations_fts",
    "operation_executions",
    "user_preferences",
}


# -- fixtures ---------------------------------------------------------------


@pytest.fixture
def sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create an isolated repo-like sandbox and chdir into it.

    Layout produced:

        tmp/
          pyproject.toml         # anchors find_project_root
          projects/
            TEMPLATE/            # copied from the real repo
    """
    # Anchor file for find_project_root.
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'iris-test'\n")

    # Copy the real TEMPLATE so create_project has something to clone.
    real_template = Path(__file__).resolve().parents[1] / "projects" / "TEMPLATE"
    sandbox_projects = tmp_path / "projects"
    sandbox_projects.mkdir()
    shutil.copytree(real_template, sandbox_projects / "TEMPLATE")

    monkeypatch.chdir(tmp_path)
    return tmp_path


# -- create_project ---------------------------------------------------------


def test_create_produces_spec_directory_layout(sandbox: Path) -> None:
    dest = projects.create_project("alpha", description="first project")
    assert dest == sandbox / "projects" / "alpha"
    assert dest.is_dir()

    for rel in EXPECTED_DIRS:
        assert (dest / rel).is_dir(), f"missing directory: {rel}"

    for rel in EXPECTED_MEMORY_FILES:
        assert (dest / rel).is_file(), f"missing memory skeleton file: {rel}"

    # Per-project config exists and has [project] identity patched in.
    cfg_text = (dest / "config.toml").read_text(encoding="utf-8")
    assert 'name = "alpha"' in cfg_text
    assert 'description = "first project"' in cfg_text
    assert "created_at" in cfg_text


def test_create_produces_iris_sqlite_with_v1_schema(sandbox: Path) -> None:
    dest = projects.create_project("beta")
    db_path = dest / DB_FILENAME
    assert db_path.is_file(), "iris.sqlite must be created by create_project"

    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        tables = {r[0] for r in rows}
        missing = EXPECTED_TABLES - tables
        assert not missing, f"missing tables after create_project: {missing}"

        version = conn.execute("PRAGMA user_version").fetchone()[0]
        assert version >= 1
    finally:
        conn.close()


def test_create_rejects_duplicate_name(sandbox: Path) -> None:
    projects.create_project("dup")
    with pytest.raises(FileExistsError):
        projects.create_project("dup")


def test_create_rejects_template_name(sandbox: Path) -> None:
    with pytest.raises(ValueError):
        projects.create_project("TEMPLATE")


def test_create_rejects_invalid_name(sandbox: Path) -> None:
    with pytest.raises(ValueError):
        projects.create_project("has spaces")
    with pytest.raises(ValueError):
        projects.create_project("with/slash")


# -- list_projects ----------------------------------------------------------


def test_list_excludes_template(sandbox: Path) -> None:
    projects.create_project("one")
    projects.create_project("two")

    names = [p.name for p in projects.list_projects()]
    assert names == ["one", "two"]
    assert "TEMPLATE" not in names


def test_list_empty_when_only_template(sandbox: Path) -> None:
    assert projects.list_projects() == []


# -- open_project -----------------------------------------------------------


def test_open_returns_path_for_existing_project(sandbox: Path) -> None:
    created = projects.create_project("gamma")
    opened = projects.open_project("gamma")
    assert opened == created


def test_open_raises_for_missing_project(sandbox: Path) -> None:
    with pytest.raises(FileNotFoundError):
        projects.open_project("nope-does-not-exist")


# -- delete_project ---------------------------------------------------------


def test_delete_removes_everything(sandbox: Path) -> None:
    dest = projects.create_project("doomed")
    assert dest.is_dir()

    projects.delete_project("doomed")
    assert not dest.exists()

    # Still listable after removal (now empty).
    assert [p.name for p in projects.list_projects()] == []


def test_delete_missing_raises(sandbox: Path) -> None:
    with pytest.raises(FileNotFoundError):
        projects.delete_project("never-existed")


def test_delete_refuses_template(sandbox: Path) -> None:
    with pytest.raises(ValueError):
        projects.delete_project("TEMPLATE")
    # TEMPLATE survives.
    assert (sandbox / "projects" / "TEMPLATE").is_dir()


def test_delete_clears_active_pointer_when_matching(sandbox: Path) -> None:
    projects.create_project("active-one")
    projects.set_active_project("active-one")
    assert projects.resolve_active_project() is not None

    projects.delete_project("active-one")
    assert projects.resolve_active_project() is None
    assert not projects.active_project_path().is_file()


# -- active-project round trip ----------------------------------------------


def test_active_project_roundtrip(sandbox: Path) -> None:
    # No pointer → resolve returns None.
    assert projects.resolve_active_project() is None

    projects.create_project("work")
    returned = projects.set_active_project("work")
    assert returned == sandbox / "projects" / "work"

    resolved = projects.resolve_active_project()
    assert resolved == sandbox / "projects" / "work"

    # Close clears the pointer.
    projects.close_project()
    assert projects.resolve_active_project() is None
    assert not projects.active_project_path().is_file()


def test_set_active_raises_for_missing_project(sandbox: Path) -> None:
    with pytest.raises(FileNotFoundError):
        projects.set_active_project("ghost")


def test_resolve_active_returns_none_when_pointer_dangling(
    sandbox: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """If the pointer names a project that was deleted out-of-band, we warn
    and return None rather than raising."""
    projects.create_project("ephemeral")
    projects.set_active_project("ephemeral")

    # Nuke the directory without going through delete_project — simulates a
    # user rm -rf'ing the project folder.
    shutil.rmtree(sandbox / "projects" / "ephemeral")

    assert projects.resolve_active_project() is None
    captured = capsys.readouterr()
    assert "no longer exists" in captured.err
