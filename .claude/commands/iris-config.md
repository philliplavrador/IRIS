---
description: View or edit IRIS configuration
allowed-tools: Task
argument-hint: [show | edit <file> <key> <value> | validate]
---

Use the `iris` subagent to inspect or modify configuration.

$ARGUMENTS

The agent should call the appropriate `iris config ...` subcommand and report the result. Edits go through `iris config edit`, never via direct file writes.
