---
description: Reset the entire CASI repo to a clean state
allowed-tools: Bash, Read, Edit
---

Reset the CASI repository to a clean state by deleting all projects and restoring default configs.

**This is extremely destructive.** Before doing anything:

1. List what will be destroyed:
   - Run `casi project list` to show all projects and their output/reference counts.
   - Run `casi config show` to show current config state.
2. Print a clear warning:
   ```
   WARNING: This will permanently destroy:
     - ALL project workspaces (outputs, caches, history, references, reports)
     - ALL config customizations (paths.yaml, ops.yaml, globals.yaml reset to defaults)
     - The active project pointer (.casi/active_project)
   This cannot be undone.
   ```
3. **Ask the user to type "yes" to confirm.** Do not proceed on anything other than an explicit "yes".
4. Only after confirmation, execute the reset:
   a. Run `casi project close` to clear the active pointer.
   b. Delete every directory under `projects/` except `TEMPLATE/`, `README.md`, `CLAUDE.md`, and `.gitignore`:
      ```bash
      find projects/ -mindepth 1 -maxdepth 1 -type d ! -name TEMPLATE -exec rm -rf {} +
      ```
   c. Restore configs to their git defaults:
      ```bash
      git checkout HEAD -- configs/paths.yaml configs/ops.yaml configs/globals.yaml
      ```
5. Confirm the reset is complete.
