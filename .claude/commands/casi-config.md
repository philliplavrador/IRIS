---
description: View or edit CASI configuration
allowed-tools: Task
argument-hint: [show | edit <file> <key> <value> | validate]
---

Use the `casi` subagent to inspect or modify configuration.

$ARGUMENTS

The agent should call the appropriate `casi config ...` subcommand and report the result. Edits go through `casi config edit`, never via direct file writes.
