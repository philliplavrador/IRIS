---
description: Generate a IRIS plot from a natural-language request
allowed-tools: Task
argument-hint: [what you want to plot]
---

Use the `iris` subagent to translate the following request into a DSL string and run it via the `iris` CLI:

$ARGUMENTS

If no session is active yet, the agent should run its full startup verification flow first. If an active project is set, the plot will land in `projects/<name>/output/`.
