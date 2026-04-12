"""PostToolUse hook: run ruff check --fix + ruff format on changed Python files.

Receives Claude Code tool-use JSON on stdin. Extracts file_path from
tool_input and runs ruff only if the file is under src/ or tests/ and
ends with .py.
"""
import json
import re
import subprocess
import sys


def main():
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return

    file_path = data.get("tool_input", {}).get("file_path", "")
    # Normalize to forward slashes for matching
    normalized = file_path.replace("\\", "/")

    if not re.search(r"(src|tests)/.*\.py$", normalized):
        return

    subprocess.run(
        ["uv", "run", "ruff", "check", "--fix", file_path],
        cwd="d:/Projects/CASI",
        capture_output=True,
    )
    subprocess.run(
        ["uv", "run", "ruff", "format", file_path],
        cwd="d:/Projects/CASI",
        capture_output=True,
    )


if __name__ == "__main__":
    main()
