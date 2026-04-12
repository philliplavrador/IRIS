---
description: Implement a previously-proposed IRIS operation across all six touch points
allowed-tools: Task
argument-hint: <op_name>
---

Use the `iris` subagent to implement an operation that already has an approved proposal at `docs/op-proposals/<op_name>.md`.

$ARGUMENTS

The agent should:

1. Confirm there is an active project (`cat .iris/active_project`). If not, stop.
2. **Require an existing proposal.** Read `docs/op-proposals/<op_name>.md` via the Read tool. If it doesn't exist, stop and tell the user to run `/iris-op-propose <op_name>` first. Do NOT proceed with implementation without a proposal.
3. **Require recent user approval.** Check `claude_history.md ## Decisions` for a bullet like `drafted op proposal <op_name>` and an accompanying `approved op proposal <op_name>` bullet. If the proposal was drafted but not approved, stop and ask the user for explicit approval to proceed. Do NOT infer approval from silence.
4. Re-verify the cross-check gate in §6 of the proposal. If the active project's `## Goals` have changed since the proposal was drafted and no longer align, surface the mismatch and stop.
5. Implement **all six touch points** in order. The agent uses Edit (not Write) on existing files and Write on new files:
   a. **Touch point 1** — add to `TYPE_TRANSITIONS` in `src/iris/engine.py`
   b. **Touch point 2** — add the `op_<name>` handler function in the OP HANDLERS section of `src/iris/engine.py` (match the signature sketch from proposal §7)
   c. **Touch point 3** — add `registry.register_op("<name>", op_<name>)` inside `create_registry()` in `src/iris/engine.py`
   d. **Touch point 4** — add the `<name>:` defaults entry to `configs/ops.yaml`
   e. **Touch point 5** — add the `## \`<name>\` —` section to `docs/operations.md` using the math, parameters, and citations from the proposal. **Mandatory — the op does not ship without this.**
   f. **Touch point 6** — add `test_<name>_transitions` to `tests/test_op_registry.py`
6. Run `python scripts/check_op_registered.py <name>` via Bash. **If any check is `[ ]`, fix it and re-run.** The agent does not mark the task done until the verifier returns `PASS`.
7. Run the new op against the user's data via `iris run "<a simple DSL using the new op>"` to confirm it produces output without errors. Report the session path.
8. Append to `claude_history.md`:
   - `## Decisions` — `implemented op_<name> across all 6 touch points [reason: proposal approved <date>]`
   - `## Operations Run` — the first successful DSL string + session path
9. Delete the proposal file or move it to `docs/op-proposals/archive/<op_name>.md` (ask the user which).

Hard rules for this command:

- **Never** skip touch point 5 (the docs section). An op without its math documented is unusable by other agents and by the user.
- **Never** commit to a touch point before the previous one is complete. Wire them up in order.
- **Never** fabricate citations in the docs section. All citations must come from the proposal, which means from real files in `projects/<active>/claude_references/`.
- **Never** mark the task done until `check_op_registered.py <name>` returns `PASS`.
- **Never** proceed past step 4 if the cross-check gate fails.

The full agent flow is in [`docs/operations.md`](../../docs/operations.md) § "Adding a new operation".
