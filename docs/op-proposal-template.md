# IRIS operation proposal — `<op_name>`

> This document is the design spec the analysis agent fills out **before** writing any code for a new op. It lives in `docs/op-proposals/<op_name>.md`. Once the op is implemented and merged, this file can be deleted or moved to `docs/op-proposals/archive/`.
>
> Every section is required. Sections left blank are a blocker — the op does not get implemented.

## 1. Identity

- **Name:** `<snake_case_op_name>`
- **Category:** Signal Filtering | Spike Detection | Calcium Imaging | Signal Simulation | Analysis | Diagnostics
- **One-line purpose:** <what it does in one sentence>
- **Author:** <human or agent name + date>
- **Project that motivated it:** `projects/<name>/` (the project whose `## Goals` this op serves)

## 2. Signature

List every `{input_type: output_type}` pair this op should support. Copy from the existing types in [`src/iris/engine.py`](../src/iris/engine.py) — do NOT invent new data classes without a separate proposal for each.

```
MEATrace  -> MEATrace
MEABank   -> MEABank
```

- **Polymorphism:** yes (two transitions) | no (one transition)
- **Is this a function-op** (operates on the bank directly, no per-channel auto-application)? yes | no
- **New output type required?** yes (describe) | no

## 3. Parameters

One row per parameter, with a default value, units, valid range, and a one-line rationale for the default.

| Param | Default | Units | Range | Why this default |
|---|---|---|---|---|
| `low_hz` | 350 | Hz | 0 < low < high < fs/2 | Matches the bandpass used in the rest of the pipeline |
| `...` | | | | |

## 4. Math / algorithm

The operation in formal notation. Use LaTeX for equations (`$$ ... $$` blocks) and cite sources for any non-trivial formula.

### Input

<what the op reads from its input type — e.g. "takes the MEATrace's `data` array of shape (N,) at `fs_hz` Hz">

### Algorithm

<step-by-step, numbered. One paragraph per step.>

1. ...

### Output

<what goes into the output type — dimensions, units, any new fields>

### Edge cases

<NaN handling, empty input, single-sample input, fs_hz mismatches, margin trimming, anything else that will bite>

## 5. Citations (rule 2 of the partner contract)

Every non-obvious claim about the algorithm's correctness must cite a saved reference from the active project. Citations go here as a bulleted list with `claude_references/<stub>.md` paths. If a citation can't be found, flag it with `[training-data claim]` — do NOT proceed to implementation with unsupported claims.

- `claude_references/<ref1>.md` — <one sentence on what this supports>
- `claude_references/<ref2>.md` — <one sentence>
- [training-data claim] — <any sentence not backed by a saved reference, tagged here>

## 6. Cross-check against user goal (rule 1 of the partner contract)

This is the **gate** that prevents building the wrong op. The agent must fill out all three:

- **Active project's current top goal (from `claude_history.md ## Goals`):**
  > <paste the most recent ## Goals bullet verbatim>

- **How this op serves that goal:**
  > <one paragraph; concrete, not aspirational>

- **What could go wrong:** <at least one of — "I might be building the wrong op," "I misunderstood the user's request," "the user might actually need an existing op they don't know about">. Address each risk in one sentence.

If the agent cannot convincingly fill in all three, it must STOP and surface the mismatch to the user with the exact phrasing from `.claude/agents/iris.md` § "Autonomous op creation":

> "I might be building the wrong thing. Your goal is X; this op solves Y. Which is it?"

## 7. Implementation sketch

Pseudocode for the handler function. This is NOT the actual Python — it's a contract the agent implements against. Keep it to ≤ 30 lines.

```python
def op_<name>(inp: <InputType>, ctx: PipelineContext, *,
              <param1>, <param2>) -> <OutputType>:
    # 1. Validate params
    # 2. ...
    # 3. Return <OutputType>(...)
```

## 8. Test plan

### Type-transition test (mandatory)

A dedicated `test_<name>_transitions` function in `tests/test_op_registry.py` following the existing pattern:

```python
def test_<name>_transitions():
    registry, _ = create_registry()
    assert registry.validate_type_transition("<name>", InputType) is OutputType
```

### Behavioral tests (optional but strongly preferred)

List any synthetic-data tests you'll add (e.g. "pure-tone input → filtered output has expected passband attenuation"). Use `tests/synthetic_data.py` helpers where possible.

## 9. Six-touch-point checklist (enforced by `scripts/check_op_registered.py`)

- [ ] 1. `TYPE_TRANSITIONS["<name>"]` entry in `src/iris/engine.py`
- [ ] 2. `def op_<name>(...)` handler function in `src/iris/engine.py`
- [ ] 3. `registry.register_op("<name>", op_<name>)` inside `create_registry()` in `src/iris/engine.py`
- [ ] 4. `<name>:` defaults entry in `configs/ops.yaml`
- [ ] 5. `## \`<name>\` —` section in `docs/operations.md` with the math, parameters, and citations
- [ ] 6. `test_<name>_transitions` test in `tests/test_op_registry.py`

All six must be ticked before the op ships. Run `python scripts/check_op_registered.py <name>` to verify.

## 10. Risks and open questions

Anything you want the user's eyes on before implementation starts: alternative designs, known limitations, performance concerns, dependency additions, parameter choices you're unsure about.

---

_Filled out by: `<agent or human>`  — `<ISO date>`  — project: `projects/<name>`_
