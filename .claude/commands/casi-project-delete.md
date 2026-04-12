---
description: Delete a CASI project and all its data
allowed-tools: Bash, Task
argument-hint: <name>
---

Delete a CASI project workspace permanently.

$ARGUMENTS

Steps:
1. Parse the project name from the arguments. If missing, ask the user.
2. Verify `projects/<name>/` exists.
3. Show the user what will be deleted: run `casi project info <name>` so they can see the output count, references, and history.
4. **Ask the user for explicit confirmation** before proceeding — this is destructive and irreversible.
5. If the project is the active project, run `casi project close` first.
6. Remove the directory: `rm -rf projects/<name>`
7. Confirm deletion to the user.
