---
description: Draft a design proposal for a new CASI operation (propose-only, writes no code)
allowed-tools: Task
argument-hint: <op_name> [-- <what it should do>]
---

Use the `casi` subagent in **propose-only mode** to draft a design document for a new operation.

$ARGUMENTS

The agent should:

1. Confirm there is an active project (`cat .casi/active_project`). If not, stop and ask the user to open one — proposals are project-scoped because the cross-check against user goals requires a project's `claude_history.md ## Goals`.
2. Check that the requested op name doesn't already exist in `casi ops list` and that the functionality can't be composed from existing ops. If it can be composed, surface the composition instead and do NOT write a proposal.
3. Offer to spawn the `casi-researcher` subagent via the Task tool to gather primary sources for the op's math. Wait for user consent.
4. Copy [`docs/op-proposal-template.md`](../../docs/op-proposal-template.md) to `docs/op-proposals/<op_name>.md` and fill it out. Every section is mandatory. Citations in §5 must link to real files in `projects/<active>/claude_references/` — never fabricate.
5. **The cross-check gate in §6 is the hard stop.** Read the active project's `claude_history.md ## Goals` section. If the agent cannot convincingly explain how the proposed op serves that goal, it surfaces the mismatch to the user with the exact phrasing from `.claude/agents/casi.md`:
   > "I might be building the wrong thing. Your goal is X; this op solves Y. Which is it?"
   and stops without writing the proposal.
6. Once the proposal is written, report the file path and summarize §1 (Identity), §2 (Signature), §3 (Parameters), §6 (Cross-check) to the user.
7. Append a bullet to `claude_history.md ## Decisions` via `casi project history add --section Decisions --bullet "drafted op proposal <op_name> [reason: <one-line>]"`.
8. **Do NOT write any code.** This command is propose-only. Implementation is `/casi-op-implement <op_name>`, which the user invokes separately after reviewing and approving the proposal.

The full agent flow for op creation is documented in [`docs/operations.md`](../../docs/operations.md) § "Adding a new operation" and [`.claude/agents/casi.md`](../agents/casi.md) § "Autonomous op creation". This slash command is the entry point for **step 3** of that flow (draft a proposal), not the full implementation.
