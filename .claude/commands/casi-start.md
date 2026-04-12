---
description: Launch the CASI pipeline agent and verify configuration
allowed-tools: Task
---

Use the `casi` subagent to start a new analysis session.

The agent should:
1. Detect the active project (`.casi/active_project`) and load its `claude_config.yaml` + the `## Goals` / `## Next Steps` sections of its `claude_history.md`
2. Run `casi config show` and present a clean human-readable summary
3. Flag any missing input files
4. Wait for the user to confirm or request config changes
5. Once confirmed, create a new session via `casi session new` and remember it for the rest of the conversation
