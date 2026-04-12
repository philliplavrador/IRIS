---
description: Open an existing CASI project as the active workspace
allowed-tools: Task
argument-hint: <name>
---

Use the `casi` subagent to open an existing project.

$ARGUMENTS

The agent should:
1. Run `casi project list` if the name is ambiguous or missing
2. Run `casi project open <name>` to set the active project
3. Load the project's `claude_config.yaml` and the `## Goals` + `## Next Steps` sections of `claude_history.md`
4. Greet the user with a one-paragraph resumption summary
