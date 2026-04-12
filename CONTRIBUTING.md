# Contributing to IRIS

Thanks for your interest! Issues, PRs, and discussion are welcome.

## Quick start

1. Fork and clone the repo
2. `uv sync --extra dev` to install dependencies
3. `uv run pre-commit install` to enable lint/format hooks
4. Make your change on a feature branch
5. `uv run pytest` and `uv run ruff check src tests` should pass
6. Open a PR against `main`

## Where to look

- **`docs/development.md`** — full developer setup, code organization, and conventions
- **`docs/architecture.md`** — DSL, AST, executor, cache, type system
- **`docs/operations.md`** — math reference for every op (if you're adding one, document it here)

## Reporting bugs

Please include:

- The DSL string you ran (or a minimal repro)
- The contents of `configs/globals.yaml` and the relevant chunk of `configs/ops.yaml`
- The full traceback or error message
- The output of `iris --version` and `python --version`
- Operating system

If the bug is data-dependent and you can share a small synthetic example via `tests/synthetic_data.py`, that's the gold standard.

## Pull requests

- Keep changes focused — one logical change per PR
- Add tests for new code paths
- Update `docs/operations.md` if you add an op
- Update `README.md` features list if you add a backend or major feature
- Don't reformat unrelated code
- Don't add docstrings, comments, or type annotations to code you didn't change
