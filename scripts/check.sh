#!/usr/bin/env bash
# Maximalist validation gate for IRIS.
# Runs the Standard validation gate from REVAMP.md.
# Exits non-zero on any failure.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

fail=0
run() {
    echo ""
    echo "==> $*"
    if ! "$@"; then
        echo "FAIL: $*" >&2
        fail=1
    fi
}

echo "=== Python gate ==="
run uv run ruff format --check src tests
run uv run ruff check src tests
run uv run pyright src/iris
run uv run pytest -x -q
run uvx semgrep --config=auto --error src/iris
run uv run vulture src/iris --min-confidence 80

if [ -d "iris-app" ]; then
    echo ""
    echo "=== TypeScript gate (iris-app/) ==="
    (cd iris-app && run npx tsc --noEmit)
    if [ -f iris-app/package.json ] && grep -q '"lint"' iris-app/package.json; then
        (cd iris-app && run npm run lint)
    else
        echo "(iris-app: no lint script yet — skipping)"
    fi
fi

if [ "$fail" -ne 0 ]; then
    echo ""
    echo "check.sh: one or more gates FAILED" >&2
    exit 1
fi

echo ""
echo "check.sh: all gates passed"
