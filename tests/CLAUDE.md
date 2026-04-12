# tests/ — test navigation

Pytest suite using synthetic data. Runs headless — no hardware data or uploads required.

## Test files

- `test_op_registry.py` — validates that every op in `TYPE_TRANSITIONS` is registered, every registered op has a handler, and input→output type transitions are correct.
- Other synthetic-data tests per module as they exist.

## Running tests

```bash
uv run pytest -x -q          # Python tests (ops, engine, config, sessions)
cd iris-app && npm test       # Webapp tests (vitest + testing-library)
```

## Adding a test for a new op

Minimum pattern for a type-transition check:

```python
def test_<op_name>_transitions():
    registry, _ = create_registry()
    assert registry.validate_type_transition("<op_name>", InputType) is OutputType
```

## See also
- [../CLAUDE.md](../CLAUDE.md) — repo root nav
- [../src/iris/CLAUDE.md](../src/iris/CLAUDE.md) — package layout + op authoring checklist
- [../docs/operations.md](../docs/operations.md) — op catalog
