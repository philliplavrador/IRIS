#!/usr/bin/env python3
"""Verify that a CASI operation is fully wired across all six touch points.

Usage:
    python scripts/check_op_registered.py <op_name>
    python scripts/check_op_registered.py --all

The six touch points for any op named ``<name>``:

    1. ``TYPE_TRANSITIONS["<name>"]`` exists in src/casi/engine.py
    2. A handler function ``def op_<name>(...)`` is defined in src/casi/engine.py
    3. ``registry.register_op("<name>", op_<name>)`` appears in
       ``create_registry()`` in src/casi/engine.py
    4. A defaults entry ``<name>:`` exists in configs/ops.yaml
    5. A ``## `<name>` —`` section exists in docs/operations.md
    6. A ``test_<name>_transitions`` test exists in tests/test_op_registry.py
       (or the op appears inside the parametrized ``test_op_in_type_transitions``
       via membership in TYPE_TRANSITIONS — that counts as a weaker check)

This script is read-only. It does NOT import ``casi.engine`` (which has heavy
dependencies on scipy/spikeinterface); it parses the source files directly
with regex + YAML. That means it runs in any environment, including CI
containers without the scientific stack installed.

Exit codes:
    0 — all touch points present (or --all: every op passes)
    1 — at least one touch point missing
    2 — bad invocation (missing arg, file not found)
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml


# Repo layout — these are resolved relative to the script location so the
# check can be run from any working directory.
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
ENGINE_PATH = REPO_ROOT / "src" / "casi" / "engine.py"
OPS_YAML_PATH = REPO_ROOT / "configs" / "ops.yaml"
OPS_DOC_PATH = REPO_ROOT / "docs" / "operations.md"
TEST_PATH = REPO_ROOT / "tests" / "test_op_registry.py"


@dataclass
class OpCheckResult:
    op_name: str
    checks: dict[str, bool] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(self.checks.values())

    def report(self) -> str:
        lines: list[str] = []
        status = "PASS" if self.passed else "FAIL"
        lines.append(f"{status}: {self.op_name}")
        for label, ok in self.checks.items():
            mark = "  [x]" if ok else "  [ ]"
            lines.append(f"{mark} {label}")
        for note in self.notes:
            lines.append(f"    note: {note}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Source file loaders — read once, reuse for multi-op checks
# ---------------------------------------------------------------------------


def _require(path: Path) -> str:
    if not path.is_file():
        print(f"error: required file missing: {path}", file=sys.stderr)
        sys.exit(2)
    return path.read_text(encoding="utf-8")


def load_repo_sources() -> dict[str, str]:
    """Read the four repo files this verifier inspects."""
    return {
        "engine": _require(ENGINE_PATH),
        "ops_yaml": _require(OPS_YAML_PATH),
        "ops_doc": _require(OPS_DOC_PATH),
        "tests": _require(TEST_PATH),
    }


# ---------------------------------------------------------------------------
# Touch-point extractors
# ---------------------------------------------------------------------------

_TYPE_TRANS_KEY_RE = re.compile(
    r'''^\s*["']([a-zA-Z_][a-zA-Z0-9_]*)["']\s*:\s*\{''',
    re.MULTILINE,
)
_REGISTER_OP_RE = re.compile(
    r'''registry\.register_op\(\s*["']([a-zA-Z_][a-zA-Z0-9_]*)["']\s*,\s*op_([a-zA-Z_][a-zA-Z0-9_]*)''',
)
_OP_HANDLER_RE = re.compile(
    r'''^def\s+op_([a-zA-Z_][a-zA-Z0-9_]*)\s*\(''',
    re.MULTILINE,
)


def _extract_type_transitions_keys(engine_src: str) -> set[str]:
    """Return every op name that appears as a key inside TYPE_TRANSITIONS."""
    start = engine_src.find("TYPE_TRANSITIONS")
    if start < 0:
        return set()
    # Find the matching closing brace of the outermost dict literal
    brace_open = engine_src.find("{", start)
    if brace_open < 0:
        return set()
    depth = 0
    end = brace_open
    for i in range(brace_open, len(engine_src)):
        ch = engine_src[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    block = engine_src[brace_open:end]
    return set(_TYPE_TRANS_KEY_RE.findall(block))


def _extract_registered_ops(engine_src: str) -> dict[str, str]:
    """Return {op_name: handler_symbol_name} for every register_op call."""
    return {m.group(1): f"op_{m.group(2)}" for m in _REGISTER_OP_RE.finditer(engine_src)}


def _extract_defined_handlers(engine_src: str) -> set[str]:
    """Return the set of defined `op_<name>` functions."""
    return {f"op_{m.group(1)}" for m in _OP_HANDLER_RE.finditer(engine_src)}


def _extract_ops_yaml_keys(ops_yaml_src: str) -> set[str]:
    """Return the set of top-level op names in configs/ops.yaml."""
    data = yaml.safe_load(ops_yaml_src) or {}
    if not isinstance(data, dict):
        return set()
    return set(data.keys())


def _extract_doc_sections(ops_doc_src: str) -> set[str]:
    """Return the set of op names with ``## `<name>` —`` headers in operations.md.

    Only the op catalog (everything BEFORE the "# Adding a new operation"
    separator) is scanned, so example snippets inside the authoring guide
    don't pollute the real op list.
    """
    # Stop scanning at the "Adding a new operation" section if it exists.
    cutoff = ops_doc_src.find("# Adding a new operation")
    scope = ops_doc_src if cutoff < 0 else ops_doc_src[:cutoff]
    pattern = re.compile(r'^## `([a-zA-Z_][a-zA-Z0-9_]*)`\s*—', re.MULTILINE)
    return set(pattern.findall(scope))


def _extract_transition_tests(tests_src: str) -> set[str]:
    """Return op names with dedicated ``test_<name>_transitions`` tests."""
    pattern = re.compile(r'^def\s+test_([a-zA-Z_][a-zA-Z0-9_]*)_transitions\s*\(', re.MULTILINE)
    return set(pattern.findall(tests_src))


# ---------------------------------------------------------------------------
# Per-op checker
# ---------------------------------------------------------------------------


def check_op(op_name: str, sources: dict[str, str]) -> OpCheckResult:
    engine = sources["engine"]
    ops_yaml = sources["ops_yaml"]
    ops_doc = sources["ops_doc"]
    tests = sources["tests"]

    result = OpCheckResult(op_name=op_name)

    # 1. TYPE_TRANSITIONS entry
    trans_keys = _extract_type_transitions_keys(engine)
    result.checks["TYPE_TRANSITIONS entry in src/casi/engine.py"] = op_name in trans_keys

    # 2. handler function defined
    handlers = _extract_defined_handlers(engine)
    expected = f"op_{op_name}"
    result.checks[f"handler function `{expected}(...)` in src/casi/engine.py"] = expected in handlers

    # 3. register_op call in create_registry()
    registered = _extract_registered_ops(engine)
    if op_name in registered:
        registered_symbol = registered[op_name]
        if registered_symbol != expected:
            result.notes.append(
                f"register_op(\"{op_name}\", {registered_symbol}) binds a handler "
                f"named {registered_symbol!r}, not {expected!r} — rename for consistency"
            )
        result.checks[f'register_op("{op_name}", ...) in create_registry()'] = True
    else:
        result.checks[f'register_op("{op_name}", ...) in create_registry()'] = False

    # 4. defaults entry in configs/ops.yaml
    yaml_keys = _extract_ops_yaml_keys(ops_yaml)
    has_yaml = op_name in yaml_keys
    result.checks[f"`{op_name}:` entry in configs/ops.yaml"] = has_yaml
    if has_yaml:
        parsed = yaml.safe_load(ops_yaml) or {}
        entry = parsed.get(op_name)
        if entry is None:
            result.notes.append(f"configs/ops.yaml['{op_name}'] is null — use {{}} for param-less ops")
        elif isinstance(entry, dict) and not entry:
            # Empty dict is a valid signal that the op has no defaults
            pass

    # 5. docs/operations.md section
    doc_sections = _extract_doc_sections(ops_doc)
    result.checks[f"`## {op_name}` section in docs/operations.md"] = op_name in doc_sections

    # 6. tests/test_op_registry.py
    test_names = _extract_transition_tests(tests)
    has_own_test = op_name in test_names
    if has_own_test:
        result.checks[f"`test_{op_name}_transitions` in tests/test_op_registry.py"] = True
    else:
        # Fall back to the parametrized coverage check
        parametrized_covered = (
            "@pytest.mark.parametrize" in tests
            and "TYPE_TRANSITIONS.keys()" in tests
            and "test_op_in_type_transitions" in tests
            and op_name in trans_keys
        )
        result.checks[f"test coverage in tests/test_op_registry.py"] = parametrized_covered
        if parametrized_covered:
            result.notes.append(
                f"no dedicated `test_{op_name}_transitions` - covered weakly by "
                f"parametrized `test_op_in_type_transitions`; add a dedicated test"
            )

    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="check_op_registered",
        description=(
            "Verify that a CASI op is fully wired across all six touch points "
            "(TYPE_TRANSITIONS, handler function, register_op call, configs/ops.yaml, "
            "docs/operations.md, tests/test_op_registry.py)."
        ),
    )
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("op_name", nargs="?", help="Name of the op to check (e.g. butter_bandpass)")
    g.add_argument("--all", action="store_true",
                   help="Check every op in TYPE_TRANSITIONS at once")
    args = parser.parse_args(argv)

    sources = load_repo_sources()

    if args.all:
        all_ops = sorted(_extract_type_transitions_keys(sources["engine"]))
        if not all_ops:
            print("error: no ops found in TYPE_TRANSITIONS", file=sys.stderr)
            return 2
        all_passed = True
        print(f"Checking {len(all_ops)} ops...\n")
        for name in all_ops:
            res = check_op(name, sources)
            print(res.report())
            print()
            if not res.passed:
                all_passed = False
        print(f"Summary: {sum(1 for n in all_ops if check_op(n, sources).passed)}/{len(all_ops)} ops passed")
        return 0 if all_passed else 1

    result = check_op(args.op_name, sources)
    print(result.report())
    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
