"""Operation validation sandbox (REVAMP Task 15.1, spec §12.2).

Three stages run in order; the first failure short-circuits the pipeline
and leaves ``operations.validation_status = 'rejected'``:

1. **Static** — parse with ``ast.parse``; reject on ``SyntaxError``.
2. **Unit** — if a test artifact is present, run it in a subprocess with
   ``python -m pytest`` (timeout-guarded).
3. **Sample** — execute a smoke call against a small synthetic input
   dictionary passed in by the caller (omit to skip).

When every stage passes, the op is promoted to ``'validated'`` and
``validated_at`` is stamped.

Sandbox notes
-------------
We use ``subprocess.run`` with a tight timeout and a restricted cwd. We
do **not** claim cryptographic isolation — this is a seatbelt against
accidental misbehaviour (infinite loops, flaky tests), not a defence
against adversarial code. The generated-op pipeline is for trusted LLM
output, not third-party uploads.
"""

from __future__ import annotations

import ast
import sqlite3
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

__all__ = [
    "VALIDATION_STATUSES",
    "ValidationResult",
    "validate_operation",
]

VALIDATION_STATUSES: Final[frozenset[str]] = frozenset(
    {"draft", "validated", "rejected", "deprecated"}
)

_TEST_TIMEOUT_SECONDS: Final[float] = 30.0


class ValidationResult(dict):
    """Dict subclass so callers can treat the return value as structured data."""


def _update_status(conn: sqlite3.Connection, op_id: str, status: str, *, validated: bool) -> None:
    if validated:
        conn.execute(
            "UPDATE operations SET validation_status = ?, validated_at = ? WHERE op_id = ?",
            (status, datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ"), op_id),
        )
    else:
        conn.execute(
            "UPDATE operations SET validation_status = ? WHERE op_id = ?",
            (status, op_id),
        )


def _load_source(conn: sqlite3.Connection, op_id: str) -> tuple[str | None, str | None]:
    """Return ``(source_code, test_code)`` for an operation, each may be None."""
    row = conn.execute(
        "SELECT code_artifact_id, test_artifact_id FROM operations WHERE op_id = ?",
        (op_id,),
    ).fetchone()
    if row is None:
        return None, None
    code_artifact_id, test_artifact_id = row
    source = _load_artifact_bytes(conn, code_artifact_id)
    tests = _load_artifact_bytes(conn, test_artifact_id) if test_artifact_id else None
    return source, tests


def _load_artifact_bytes(conn: sqlite3.Connection, artifact_id: str | None) -> str | None:
    """Best-effort artifact read; falls back to None if the caller can't
    supply ``source_code`` directly. Resolves the project path by pairing
    the DB filename with the artifact's ``storage_path`` column.
    """
    if not artifact_id:
        return None
    row = conn.execute(
        "SELECT storage_path FROM artifacts WHERE artifact_id = ?", (artifact_id,)
    ).fetchone()
    if row is None or not row[0]:
        return None
    db_row = conn.execute("PRAGMA database_list").fetchone()
    if not db_row or not db_row[2]:
        return None
    project_path = Path(db_row[2]).parent
    blob_path = project_path / row[0]
    try:
        return blob_path.read_text(encoding="utf-8")
    except (FileNotFoundError, UnicodeDecodeError, OSError):
        return None


def _static_check(source: str) -> tuple[bool, str | None]:
    try:
        ast.parse(source)
    except SyntaxError as exc:
        return False, f"SyntaxError: {exc.msg} (line {exc.lineno})"
    return True, None


def _run_tests(source: str, test_code: str) -> tuple[bool, str | None]:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "op.py").write_text(source, encoding="utf-8")
        (root / "test_op.py").write_text(test_code, encoding="utf-8")
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pytest", "-x", "-q", "test_op.py"],
                cwd=root,
                capture_output=True,
                timeout=_TEST_TIMEOUT_SECONDS,
                text=True,
            )
        except subprocess.TimeoutExpired:
            return False, f"tests timed out after {_TEST_TIMEOUT_SECONDS:.0f}s"
        except FileNotFoundError:
            return False, "pytest not found on PATH"
        if result.returncode != 0:
            tail = (result.stdout or result.stderr or "").strip().splitlines()[-10:]
            return False, "tests failed:\n" + "\n".join(tail)
    return True, None


def _sample_run(
    source: str, sample_input: dict[str, Any], entry_point: str
) -> tuple[bool, str | None]:
    """Import the op module in a subprocess and call ``entry_point(sample_input)``."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "op.py").write_text(source, encoding="utf-8")
        runner = (
            "import json, sys, runpy\n"
            "ns = runpy.run_path('op.py')\n"
            f"fn = ns.get({entry_point!r})\n"
            "if fn is None:\n"
            "    sys.stderr.write('entry point missing')\n"
            "    sys.exit(2)\n"
            "args = json.loads(sys.stdin.read() or '{}')\n"
            "out = fn(**args) if isinstance(args, dict) else fn(args)\n"
            "json.dumps(out, default=str)\n"
        )
        (root / "runner.py").write_text(runner, encoding="utf-8")
        try:
            import json as _json

            proc = subprocess.run(
                [sys.executable, "runner.py"],
                cwd=root,
                capture_output=True,
                timeout=_TEST_TIMEOUT_SECONDS,
                text=True,
                input=_json.dumps(sample_input),
            )
        except subprocess.TimeoutExpired:
            return False, "sample run timed out"
        if proc.returncode != 0:
            return False, (proc.stderr or proc.stdout or "sample run failed").strip()
    return True, None


def validate_operation(
    conn: sqlite3.Connection,
    op_id: str,
    *,
    sample_input: dict[str, Any] | None = None,
    entry_point: str = "run",
    source_code: str | None = None,
    test_code: str | None = None,
) -> ValidationResult:
    """Run the 3-stage sandbox. Mutates ``operations.validation_status``.

    Callers can pass ``source_code``/``test_code`` directly (useful in
    tests, and for the propose-then-validate flow where artifacts aren't
    yet content-addressed). When omitted, they're loaded from the
    artifact store via :func:`_load_source`.
    """
    if source_code is None:
        source_code, test_code = _load_source(conn, op_id)
    if source_code is None:
        _update_status(conn, op_id, "rejected", validated=False)
        return ValidationResult(ok=False, stage="static", error="no source code")

    ok, err = _static_check(source_code)
    if not ok:
        _update_status(conn, op_id, "rejected", validated=False)
        return ValidationResult(ok=False, stage="static", error=err)

    if test_code:
        ok, err = _run_tests(source_code, test_code)
        if not ok:
            _update_status(conn, op_id, "rejected", validated=False)
            return ValidationResult(ok=False, stage="unit", error=err)

    if sample_input is not None:
        ok, err = _sample_run(source_code, sample_input, entry_point)
        if not ok:
            _update_status(conn, op_id, "rejected", validated=False)
            return ValidationResult(ok=False, stage="sample", error=err)

    _update_status(conn, op_id, "validated", validated=True)
    return ValidationResult(ok=True, stage="done", error=None)
