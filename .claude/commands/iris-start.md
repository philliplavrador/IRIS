---
description: Launch the IRIS pipeline agent and verify configuration
allowed-tools: Task
---

Use the `iris` subagent to start a new analysis session.

The agent should:
1. Detect the active project (`.iris/active_project`) and load its `claude_config.yaml` + the `## Goals` / `## Next Steps` sections of its `claude_history.md`
2. Run `iris config show` and present a clean human-readable summary
3. Flag any missing input files
4. Wait for the user to confirm or request config changes
5. Once confirmed, create a new session via `iris session new` and remember it for the rest of the conversation
