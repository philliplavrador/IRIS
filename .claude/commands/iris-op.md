---
description: Design and implement a new IRIS operation in a single flow with internal checkpoints
allowed-tools: Task
argument-hint: <op_name> [-- <what it should do>]
---

Use the `iris` subagent to design and implement a new operation. This replaces the old `/iris-op-propose` + `/iris-op-implement` split with a single flow that has two internal checkpoints: (1) user approval of the design, (2) automatic verification that tests pass. See [`.claude/agents/iris.md`](../agents/iris.md) § "New op creation" for the contract.

$ARGUMENTS

The agent must:

1. **Confirm active project.** `cat .iris/active_project`. Stop if none.
2. **Step 0 — is a new op actually needed?**
   - Does something close already exist? Run `iris ops list`.
   - Can the functionality be composed from existing ops? If yes, show the composition and stop. Composition beats a new op.
   - Is this a one-off? Encode inline with `op(param=value)` in the DSL instead.
   Only proceed if all three are no.
3. **(Optional) Research.** If the math needs primary sources, spawn `iris-researcher` via the `Task` tool. Read every new stub before citing.
4. **Announce the design.** Post in chat:
   - Name, category, one-line purpose
   - Signature: every `{input_type: output_type}` pair (from existing types — do not invent data classes)
   - Parameters table with defaults, units, ranges
   - Math / algorithm
   - Citations (real files in `claude_references/` OR explicitly tagged `[training-data claim]` — no fabrications)
   - Six touch points to be modified
   - Default scope: **project-local** (`projects/<active>/custom_ops/`) unless the user explicitly promotes to core
5. **Checkpoint 1.** Wait for explicit approval ("approve", "go", "ship it", "implement"). Silence is not approval.
6. **Implement** across the six touch points in order (see [`docs/operations.md`](../../docs/operations.md)):
   1. `TYPE_TRANSITIONS` entry
   2. `op_<name>` handler
   3. `registry.register_op(...)` in `create_registry()`
   4. `configs/ops.yaml` defaults
   5. `docs/operations.md` section (mandatory — an undocumented op is not shipped)
   6. `test_<name>_transitions` in `tests/test_op_registry.py`
7. **Checkpoint 2 (automatic).** Run `uv run pytest -x -q`. On pass, report success. On fail, report the failure output and wait — do not force through failing tests.
8. **Run the op against user data.** Pick a simple DSL expression, run it, confirm output.
9. **Log via the proposal tools.** Queue a `propose_decision` with `text = "implemented op_<name>"` and a brief rationale. It enters the pending queue and is committed during the curation ritual, per the standard flow.

Hard rules:
- **Default scope is project-local.** Ops go under `projects/<active>/custom_ops/` unless the user explicitly says "promote to core" or similar.
- **Never fabricate citations.** Every math claim is either backed by a real file under `claude_references/` or tagged `[training-data claim]`.
- **Never force past failing tests.** Checkpoint 2 is a hard stop.
- **Never infer approval from silence** at checkpoint 1.
