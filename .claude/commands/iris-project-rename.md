---
description: Rename an existing IRIS project
allowed-tools: Bash, Read, Edit
argument-hint: <old-name> <new-name>
---

Rename a IRIS project workspace.

$ARGUMENTS

Steps:
1. Parse `<old-name>` and `<new-name>` from the arguments. If either is missing, ask the user.
2. Validate `<new-name>` matches `[a-zA-Z0-9_-]{1,64}` and that `projects/<new-name>/` does not already exist.
3. Check whether `<old-name>` is the active project by reading `.iris/active_project`.
4. Move the directory: `mv projects/<old-name> projects/<new-name>`
5. Update the `name` field in `projects/<new-name>/claude_config.yaml` to the new name.
6. If the project was active, run `iris project open <new-name>` to update the pointer.
7. Confirm the rename to the user.
