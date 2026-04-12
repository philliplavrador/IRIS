---
description: Create a new IRIS project workspace
allowed-tools: Task
argument-hint: <name> [-- <description>]
---

Use the `iris` subagent to create a new project workspace.

$ARGUMENTS

The agent should:
1. Parse the name and optional description from the arguments
2. Run `iris project new <name> --description "<description>" --open` to create and activate the project
3. Confirm the project layout was created under `projects/<name>/`
4. Ask the user about their goals for this project and (optionally) seed `## Goals` in `claude_history.md` via Edit
