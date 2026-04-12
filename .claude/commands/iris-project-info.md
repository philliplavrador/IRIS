---
description: Show details about a IRIS project
allowed-tools: Task
argument-hint: [name]
---

Show detailed information about a IRIS project.

$ARGUMENTS

The agent should:
1. If a name is provided, run `iris project info <name>`. Otherwise run `iris project info` (uses the active project).
2. Present the output: name, path, creation date, description, reference count, plot count, and last history update.
