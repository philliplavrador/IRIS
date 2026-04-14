"""PostToolUse hook: run the maximalist validation gate on changed Python files.

Receives Claude Code tool-use JSON on stdin. If a Python file under src/ or
tests/ was edited, runs ruff check --fix + ruff format on that file for fast
feedback, then invokes scripts/check.sh (POSIX) or scripts/check.ps1 (Windows)
to run the full Standard validation gate from REVAMP.md.

The full gate is intentionally heavy: it keeps the maximalist contract honest
every time Claude edits a Python file. Agents and humans can invoke the gate
directly via `bash scripts/check.sh` or `pwsh scripts/check.ps1`.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def main():
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return

    file_path = data.get("tool_input", {}).get("file_path", "")
    normalized = file_path.replace("\\", "/")

    if not re.search(r"(src|tests)/.*\.py$", normalized):
        return

    # Fast per-file ruff pass for immediate feedback.
    subprocess.run(
        ["uv", "run", "ruff", "check", "--fix", file_path],
        cwd=str(REPO_ROOT),
        capture_output=True,
    )
    subprocess.run(
        ["uv", "run", "ruff", "format", file_path],
        cwd=str(REPO_ROOT),
        capture_output=True,
    )

    # Opt-in full gate: set IRIS_HOOK_FULL_GATE=1 to run the maximalist gate
    # on every Python edit. Off by default to keep edit latency low; the gate
    # is still available via `bash scripts/check.sh` and is required before
    # any REVAMP.md task commit.
    if os.environ.get("IRIS_HOOK_FULL_GATE") == "1":
        if os.name == "nt":
            script = REPO_ROOT / "scripts" / "check.ps1"
            subprocess.run(
                ["pwsh", "-NoProfile", "-File", str(script)],
                cwd=str(REPO_ROOT),
                capture_output=True,
            )
        else:
            script = REPO_ROOT / "scripts" / "check.sh"
            subprocess.run(
                ["bash", str(script)],
                cwd=str(REPO_ROOT),
                capture_output=True,
            )


if __name__ == "__main__":
    main()
