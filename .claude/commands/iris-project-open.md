---
description: Open an existing IRIS project as the active workspace
allowed-tools: Task
argument-hint: <name>
---

Use the `iris` subagent to open an existing project.

$ARGUMENTS

The agent should:
1. Run `iris project list` if the name is ambiguous or missing
2. Run `iris project open <name>` to set the active project
3. Load the project's `claude_config.yaml` and the `## Goals` + `## Next Steps` sections of `claude_history.md`
4. Greet the user with a one-paragraph resumption summary
