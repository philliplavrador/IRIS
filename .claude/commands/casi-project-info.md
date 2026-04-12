---
description: Show details about a CASI project
allowed-tools: Task
argument-hint: [name]
---

Show detailed information about a CASI project.

$ARGUMENTS

The agent should:
1. If a name is provided, run `casi project info <name>`. Otherwise run `casi project info` (uses the active project).
2. Present the output: name, path, creation date, description, reference count, plot count, and last history update.
