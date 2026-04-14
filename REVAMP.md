# REVAMP.md — Read this whole top section, then execute exactly one task.

## Agent quick-start

You were invoked with something like "Read and Implement REVAMP.md." Follow this procedure exactly. Do not deviate.

1. **Find your task.** Scan this file from the top for the lowest-numbered `### [ ] Task N.M` heading. That heading is your task. Do not skip ahead — even if a later task's `Blocks:` line says "none," strict numeric order keeps the workflow predictable and reviewable.
2. **Read the references** listed in the task block before opening any code. This is non-negotiable: the task body deliberately omits context that lives in the spec and the linked CLAUDE.md files.
3. **Do the work** described under **What to build**. Stay inside the listed file set. Do not expand scope. If you discover more work that genuinely belongs in REVAMP.md, file it as a new sub-task in this file rather than doing it inline.
4. **Run the Standard validation gate** (below) plus any task-specific additions. All checks must pass before you commit. If a task block declares **Acceptable temporary failures**, those specific failures are exempt — nothing else is.
5. **Commit** with the prefix the task specifies. **The same commit must flip `### [ ] Task N.M` to `### [x] Task N.M` in this file.** One task = one commit.
6. **Stop.** Do not start the next task. A fresh agent invocation handles the next one. Output a one-line summary of what you did and exit.

### Edge cases

- **No unchecked tasks left.** If every task in this file is `[x]`, output exactly `REVAMP complete — all tasks done.` and exit. Do not invent new work.
- **Task description is wrong.** If the spec contradicts the task, an assumed file doesn't exist, the validation gate is impossible to satisfy as written, or anything else makes the task block unworkable: **stop and ask the user.** Do not improvise a fix and do not silently work around the problem.

The plan-mode blueprint behind this document is at `C:/Users/phill/.claude/plans/compressed-leaping-crab.md`. Read it only if the task instructions reference it.

---

## Standard validation gate (every task)

```bash
# Python
uv run ruff format --check src tests
uv run ruff check src tests
uv run pyright src/iris
uv run pytest -x -q
uvx semgrep --config=auto --error src/iris
uv run vulture src/iris --min-confidence 80

# TypeScript (run when iris-app/ touched)
cd iris-app && npx tsc --noEmit && npm run lint
```

Tasks may add to this gate (e.g., a new test file) but never remove from it. If a task legitimately can't pass (e.g., Phase 0 deletes break the import graph until Phase 1 lands), the task block calls that out explicitly under **Acceptable temporary failures**.

## Phase-boundary E2E checkpoint

At the last task of every phase, additionally:

```bash
cd iris-app && npm run dev   # daemon on 4002, server on 4001
# Smoke: open http://localhost:4173, exercise the phase's end-to-end flow
# (specific playwright script per phase boundary)
```

---

## Phase 0 — Nuke + Baseline

Goal: clear every file destined for deletion before any rewrite begins. Build will be partially broken between Phase 0 and Phase 1; that is intentional.

### [x] Task 0.1 — Delete legacy test projects

**Phase**: 0 · **Effort**: S · **Blocks**: none

**References**: `C:/Users/phill/.claude/plans/compressed-leaping-crab.md` (Phase 0)

**Files to delete**:
- `projects/test/` (entire directory)
- `projects/profile_test/` (entire directory)

**What to build**: Pure deletion. These are old-format test fixtures (claude_history.md, partial knowledge.sqlite). Tests will be re-seeded from the new TEMPLATE in Phase 1.

**Acceptable temporary failures**: none.

**Commit**: `chore: remove legacy test projects`

**Done when**: `ls projects/` shows only `TEMPLATE/`, `CLAUDE.md`, `README.md`.

---

### [x] Task 0.2 — Delete superseded docs

**Phase**: 0 · **Effort**: S · **Blocks**: none

**Files to delete**:
- `docs/iris-memory.md`
- `docs/iris-behavior.md`
- `docs/agent-guide.md`
- `docs/refactoring-plan.md`
- `docs/analysis-assistant.md`
- `IRIS_BEHAVIOR_PLAN.md` (root)

**What to build**: Pure deletion. Replacement docs (`docs/memory.md`, rewritten `docs/architecture.md`, rewritten `docs/projects.md`) come in Phase 10.

**Commit**: `docs: drop superseded design docs`

**Done when**: `git status` shows the six files deleted.

---

### [x] Task 0.3 — Delete empty directories

**Phase**: 0 · **Effort**: S · **Blocks**: none

**Files to delete**:
- `cache/` (empty)
- `outputs/` (empty)

**Commit**: `chore: drop empty top-level dirs`

---

### [x] Task 0.4 — Delete legacy memory modules

**Phase**: 0 · **Effort**: S · **Blocks**: 1.5, 1.7, all later memory tasks

**Files to delete**:
- `src/iris/projects/knowledge.py`
- `src/iris/projects/ledger.py`
- `src/iris/projects/recall.py`
- `src/iris/projects/digest.py`
- `src/iris/projects/conversation.py`
- `src/iris/projects/profile.py`
- `src/iris/projects/embeddings.py`
- `src/iris/projects/slice_builder.py`
- `src/iris/projects/views.py`
- `src/iris/projects/tools.py`
- `src/iris/projects/archive.py`
- `tests/test_memory_foundation.py`
- `tests/test_memory_phase2.py`
- `tests/test_memory_scale.py`

**Files to modify**:
- `src/iris/projects/__init__.py` — strip every memory-layer import; replace with a stub: `def __getattr__(name): raise NotImplementedError(f"{name}: memory layer rebuilding — see REVAMP.md")`. Project lifecycle (`create_project`, `open_project`, etc.) stays as-is for now; Phase 1.7 rebuilds it cleanly.

**Acceptable temporary failures**: `pytest` will be missing the deleted memory tests but should still pass for engine/CLI/session tests. `pyright` may surface unresolved-import errors in `src/iris/daemon/routes/memory.py` (which Task 0.5 stubs out).

**Commit**: `chore: nuke legacy memory modules`

**Done when**: `ls src/iris/projects/*.py` shows only `__init__.py`. Pytest passes (engine + CLI tests only).

---

### [x] Task 0.5 — Stub broken daemon routes

**Phase**: 0 · **Effort**: S · **Blocks**: 1.10, 2.4

**Files to modify**:
- `src/iris/daemon/routes/memory.py` — replace entire file with a stub router whose every endpoint returns `503 {"error": "memory layer rebuilding — see REVAMP.md"}`.
- `src/iris/daemon/routes/pipeline.py` — remove any imports of deleted modules; if the pipeline route depends on `tools` or `digest`, gate those calls behind `try/except NotImplementedError` returning 503.

**What to build**: Keep the daemon runnable. Memory endpoints all 503 cleanly, pipeline endpoint runs ops but skips memory side-effects.

**Acceptable temporary failures**: `iris-app` integration tests that rely on memory endpoints will fail; mark them `@pytest.mark.skip(reason="phase 0 stub")`.

**Commit**: `feat(daemon): stub memory routes pending rewrite`

**Done when**: `uvicorn iris.daemon.app:app --port 4002` starts; `curl localhost:4002/health` returns 200; `curl localhost:4002/memory/recall` returns 503.

---

### [x] Task 0.6 — Rebuild TEMPLATE per spec §6

**Phase**: 0 · **Effort**: M · **Blocks**: 1.7

**References**: `IRIS Memory Restructure.md` §6 (Filesystem Layout)

**Files to delete**:
- `projects/TEMPLATE/conversations/`
- `projects/TEMPLATE/digests/`
- `projects/TEMPLATE/views/`
- `projects/TEMPLATE/claude_references/`
- `projects/TEMPLATE/user_references/`
- `projects/TEMPLATE/claude_history.md`
- `projects/TEMPLATE/report.md`
- `projects/TEMPLATE/input_data/`
- `projects/TEMPLATE/output/`
- `projects/TEMPLATE/claude_config.yaml`

**Files to create**:
- `projects/TEMPLATE/config.toml` — empty per-project config (sections present, values empty/default)
- `projects/TEMPLATE/memory/PROJECT.md` — header skeleton: `# Project`, `## Goals`, `## Active Hypotheses`, `## Open Questions`, `## Caveats`, `## User Preferences`
- `projects/TEMPLATE/memory/DECISIONS.md` — header skeleton: `# Decisions` + empty list
- `projects/TEMPLATE/memory/OPEN_QUESTIONS.md` — header skeleton: `# Open Questions` + empty list
- `projects/TEMPLATE/memory/DATASETS/.gitkeep`
- `projects/TEMPLATE/datasets/raw/.gitkeep`
- `projects/TEMPLATE/datasets/derived/.gitkeep`
- `projects/TEMPLATE/artifacts/.gitkeep`
- `projects/TEMPLATE/ops/.gitkeep`
- `projects/TEMPLATE/indexes/.gitkeep`

**Files to modify**:
- `projects/TEMPLATE/CLAUDE.md` — rewrite to describe the new layout, explain that `iris.sqlite` is created at runtime by `db.init_schema()`, link to spec §6 and `src/iris/projects/CLAUDE.md`.
- `.gitignore` — add: `projects/*/iris.sqlite`, `projects/*/iris.sqlite-wal`, `projects/*/iris.sqlite-shm`, `projects/*/indexes/*` (except `.gitkeep`), `projects/*/datasets/raw/*` (except `.gitkeep`), `projects/*/datasets/derived/*` (except `.gitkeep`), `projects/*/artifacts/*` (except `.gitkeep`).

**Commit**: `chore(template): rebuild for new memory layout`

**Done when**: `tree projects/TEMPLATE` matches spec §6 (modulo runtime-created `iris.sqlite`).

---

### [x] Task 0.7 — Collapse YAML configs into config.toml

**Phase**: 0 · **Effort**: M · **Blocks**: 1.7, 1.10, all later config-touching tasks

**References**: `IRIS Memory Restructure.md` §6

**Files to delete**:
- `configs/globals.yaml`
- `configs/ops.yaml`
- `configs/paths.yaml`
- `configs/agent_rules.yaml`

**Files to create**:
- `configs/config.toml` — global default. Top-level sections: `[engine]` (cache, plot backend), `[paths]` (data, output, cache dirs), `[plot]` (backend, defaults), `[agent.dials]` (autonomy, pushback). Faithful TOML translation of what the four YAMLs contain today.

**Files to modify**:
- `src/iris/config.py` — switch loader from `pyyaml` to stdlib `tomllib` (or `tomli` for py<3.11). Keep the public API: `load_config()`, `apply_project_overrides(project_path)`, path expansion. Per-project override file is now `projects/<name>/config.toml`.
- `pyproject.toml` — remove `pyyaml` from dependencies if no other module uses it (grep first).
- `configs/CLAUDE.md` — rewrite to describe the TOML schema.

**Commit**: `feat(config): collapse YAMLs into single config.toml`

**Done when**: `iris config show` (CLI) prints the merged effective config from TOML. All existing tests using config still pass.

---

### [x] Task 0.8 — Dev tooling + maximalist gate script

**Phase**: 0 · **Effort**: M · **Blocks**: every later task

**Files to create**:
- `scripts/check.sh` (POSIX) — runs the full Standard validation gate above. Exits non-zero on any failure. Used by hooks and humans.
- `scripts/check.ps1` (PowerShell) — Windows mirror of the same.

**Files to modify**:
- `pyproject.toml` — add dev dependencies: `pyright`, `vulture`, `semgrep` (optional, can run via `uvx`).
- `iris-app/package.json` — confirm `tsc` and `eslint` available; add `playwright` to devDependencies.
- `scripts/hook_ruff_format.py` — extend (or replace with `scripts/check.sh`) so the pre-commit hook runs the maximalist gate.

**What to build**: One-liner gate that any agent can copy-paste. Document it in `README.md` under a "For contributors / agents" section.

**Commit**: `chore: install maximalist validation toolchain`

**Done when**: `bash scripts/check.sh` exits 0 on a clean checkout of Phase 0 state.

---

## Phase 1 — Foundation: SQLite, Schema, Module Scaffolding

Goal: stand up `iris.sqlite` per spec §7, scaffold every CLAUDE.md the implementer needs, and rebuild project lifecycle so create/open/list works end-to-end via the webapp. No memory writes yet.

### [x] Task 1.1 — Author CLAUDE.md scaffolding (this is the meta-step; it deserves its own commit)

**Phase**: 1 · **Effort**: L · **Blocks**: every later task that references a CLAUDE.md

**References**: `IRIS Memory Restructure.md` (whole document for cross-references); existing `CLAUDE.md`, `src/iris/CLAUDE.md`, `iris-app/CLAUDE.md` for tone.

**Files to create**:
- `src/iris/projects/CLAUDE.md` — most detailed nav file. Per-module map: every module to be built across Phases 1–17 with name, role, public API, storage, spec §, and links to the task that creates it.
- `src/iris/daemon/CLAUDE.md` — daemon overview, route categories.
- `src/iris/daemon/routes/CLAUDE.md` — endpoint inventory (current + planned).
- `iris-app/server/CLAUDE.md` — Express proxy contract. Memory routes proxy daemon; agent-bridge integrates SDK.
- `iris-app/src/renderer/CLAUDE.md` — frontend module map (Zustand stores, workspace tabs).
- `tests/CLAUDE.md` — test inventory + planned new test files.
- `src/iris/engine/CLAUDE.md` — short note that engine is stable; SpikeLab port adds files but doesn't restructure.

**Files to modify**:
- `CLAUDE.md` (root) — add **Memory System Migration** section linking to `IRIS Memory Restructure.md` and `REVAMP.md`. Refresh "Where to go" table.
- `src/iris/CLAUDE.md` — refresh module map for new `projects/` layout.
- `iris-app/CLAUDE.md` — note frontend deferral of Appendix A UX.
- `projects/TEMPLATE/CLAUDE.md` — already touched in Task 0.6; just confirm cross-links.
- `docs/CLAUDE.md` — refresh staleness map; mark surviving docs as current.
- `configs/CLAUDE.md` — already touched in Task 0.7.

**What to build**: Each CLAUDE.md follows the 5-section structure: (1) what this dir is for, (2) what's changing, (3) migration notes, (4) dependencies, (5) implementation order hints. Cite spec § numbers liberally.

**Commit**: `docs: scaffold CLAUDE.md briefings for memory rewrite`

**Done when**: Every directory that gets touched in Phases 1–24 has a CLAUDE.md describing what's coming.

---

### [x] Task 1.2 — Transcribe target schema to schema.sql

**Phase**: 1 · **Effort**: M · **Blocks**: 1.3, 2.1, all later DB tasks

**References**: `IRIS Memory Restructure.md` §7.1 (full DDL) + §7.2 (rationale comments)

**Files to create**:
- `src/iris/projects/schema.sql` — verbatim transcription of every CREATE TABLE / CREATE INDEX / CREATE VIRTUAL TABLE from spec §7.1. Inline rationale notes from §7.2 as SQL comments. End the file with `PRAGMA user_version = 1;`.

**What to build**: Faithful translation. Tables: `projects`, `sessions`, `events`, `messages` + `messages_fts`, `tool_calls`, `datasets`, `dataset_versions`, `artifacts`, `runs`, `memory_entries` + `memory_entries_fts`, `contradictions`, `operations` + `operations_fts`, `operation_executions`, `user_preferences`. All indexes from spec.

**Validation additions**:
- `sqlite3 :memory: < src/iris/projects/schema.sql` exits 0.
- `sqlite3 :memory: < src/iris/projects/schema.sql ".tables"` lists all 12 base tables + 3 FTS5 virtual tables.

**Commit**: `feat(memory): add target SQLite schema (spec §7)`

**Done when**: schema applies cleanly to a fresh in-memory SQLite.

---

### [x] Task 1.3 — db.py: connection helper + schema migration

**Phase**: 1 · **Effort**: M · **Blocks**: 1.5, 2.1+

**References**: `IRIS Memory Restructure.md` §5.1 (Store 1), §7

**Files to create**:
- `src/iris/projects/db.py` — public API: `connect(project_path: Path) -> sqlite3.Connection`, `init_schema(conn)`, `current_version(conn) -> int`, `migrate(conn, target_version: int)`. On connect: `PRAGMA journal_mode=WAL`, `PRAGMA foreign_keys=ON`, `PRAGMA synchronous=NORMAL`. `init_schema` executes `schema.sql` only if `user_version == 0`. `migrate` reserved for future schema bumps (no-op in V1).

**What to build**: Single source of truth for SQLite access. Every other memory module imports from here. Connection pooling not needed (SQLite + WAL handles concurrent reads, daemon is single-process).

**Validation additions**: gate must include `pyright` strict mode for this file (no `Any` returns).

**Commit**: `feat(memory): db.py connection + schema migration`

**Done when**: `from iris.projects.db import connect; conn = connect(Path("/tmp/p")); init_schema(conn)` produces an `iris.sqlite` with the full schema.

---

### [x] Task 1.4 — tests/test_db.py

**Phase**: 1 · **Effort**: S · **Blocks**: 1.5

**References**: Task 1.3

**Files to create**:
- `tests/test_db.py` — cases:
  - schema applies cleanly to a fresh project path
  - `init_schema` is idempotent (re-run on existing DB is a no-op)
  - foreign keys enforced (insert violating row raises)
  - WAL files (`-wal`, `-shm`) appear after first write
  - all FTS5 virtual tables queryable

**Commit**: `test(memory): db.py + schema migration coverage`

**Done when**: `uv run pytest tests/test_db.py -x -q` green.

---

### [x] Task 1.5 — Rebuild project lifecycle CRUD

**Phase**: 1 · **Effort**: M · **Blocks**: 1.6, 1.10

**References**: `IRIS Memory Restructure.md` §6 (filesystem layout)

**Files to modify**:
- `src/iris/projects/__init__.py` — replace the Phase 0 stub. Public API:
  - `create_project(name: str) -> Path`: copy TEMPLATE → `projects/<name>/`, then `db.connect()` + `db.init_schema()` against the new `iris.sqlite`.
  - `open_project(name: str) -> Path`: validate it exists, return the path.
  - `list_projects() -> list[ProjectInfo]`: scan `projects/`, exclude TEMPLATE.
  - `delete_project(name: str)`: confirm + rmtree.
  - `resolve_active_project() -> Path | None`: read `.iris/active_project` (existing convention).
  - `set_active_project(name: str)`: write `.iris/active_project`.

**What to build**: Pure lifecycle. No memory operations, no agent bridge integration. The TEMPLATE copy must produce a project that boots (has the new directory structure + a fresh empty `iris.sqlite`).

**Commit**: `feat(projects): rebuild lifecycle CRUD on new layout`

**Done when**: `iris project new test-project` (CLI) creates `projects/test-project/` with the spec §6 layout + `iris.sqlite` containing the schema.

---

### [x] Task 1.6 — tests/test_project_lifecycle.py

**Phase**: 1 · **Effort**: S · **Blocks**: 1.10

**Files to create**:
- `tests/test_project_lifecycle.py` — cases:
  - create produces all spec §6 directories
  - create produces `iris.sqlite` with all V1 tables
  - list excludes TEMPLATE
  - open returns the path; raises if missing
  - delete removes everything
  - active project tracking round-trips

**Commit**: `test(projects): lifecycle CRUD coverage`

---

### [x] Task 1.7 — Reserved (was: project lifecycle — moved into 1.5/1.6)

Skip — folded into 1.5 and 1.6.

---

### [x] Task 1.8 — Update root navigation

**Phase**: 1 · **Effort**: S · **Blocks**: none (touches docs only)

**Files to modify**:
- `CLAUDE.md` — finalize "Memory System Migration" section. Confirm it points at `IRIS Memory Restructure.md`, REVAMP.md, and `src/iris/projects/CLAUDE.md`.
- `src/iris/CLAUDE.md` — confirm module map matches reality post-Phase 1.

**Commit**: `docs: refresh root navigation post-foundation`

---

### [x] Task 1.9 — Daemon project routes

**Phase**: 1 · **Effort**: S · **Blocks**: 1.10

**Files to modify**:
- `src/iris/daemon/routes/projects.py` — endpoints: `GET /projects`, `POST /projects` (body: `{"name": "..."}`), `GET /projects/<name>` (open), `DELETE /projects/<name>`, `GET /projects/active`, `POST /projects/active` (body: `{"name": "..."}`). All call into the rebuilt `iris.projects` module.
- Confirm `/health` endpoint exists and returns `{"status": "ok"}`.

**Commit**: `feat(daemon): project lifecycle routes`

---

### [x] Task 1.10 — Express proxy + frontend project flow + Phase 1 E2E

**Phase**: 1 · **Effort**: M · **Blocks**: Phase 2

**Files to modify**:
- `iris-app/server/routes/projects.ts` — proxy endpoints to new daemon shape. Match the 6 endpoints from Task 1.9.
- `iris-app/src/renderer/lib/api.ts` — confirm `listProjects()`, `createProject()`, `openProject()`, `deleteProject()`, `getActiveProject()`, `setActiveProject()` match.
- `iris-app/src/renderer/stores/project-store.ts` — no shape change expected; verify.

**Validation additions** (Phase 1 boundary E2E):
- `cd iris-app && npm run dev` boots cleanly (server 4001, daemon 4002).
- Playwright script in `iris-app/e2e/phase1.spec.ts`:
  1. open `http://localhost:4173`
  2. click "New project" → name "phase1-smoke"
  3. open the project
  4. assert `iris.sqlite` exists at `projects/phase1-smoke/iris.sqlite`
  5. delete the project

**Commit**: `feat(webapp): project lifecycle end-to-end`

**Done when**: Playwright phase1 spec passes. Tag commit `phase-1-complete`.

---

## Phase 2 — Event Log + Hash Chain

Goal: every state change downstream of this phase writes an event row. Hash chain provides tamper evidence.

### [ ] Task 2.1 — events.py

**Phase**: 2 · **Effort**: M · **Blocks**: 2.2, 2.3, all later memory writes

**References**: `IRIS Memory Restructure.md` §4 (Layer 4), §7.1 events table, §7.2 (hash chaining rationale)

**Files to create**:
- `src/iris/projects/events.py` — public API:
  - `append_event(conn, *, type: str, payload: dict, session_id: str | None = None) -> str` (returns `event_id`). Computes `event_hash = sha256(type + canonical_json(payload) + (prev_event_hash or ""))`. Reads chain head with `SELECT event_hash FROM events WHERE project_id=? ORDER BY ts DESC LIMIT 1` inside the same transaction.
  - `verify_chain(conn, project_id: str) -> bool` — re-walks the chain, returns False on first mismatch.
  - Event types (literal enum or constants): `message`, `tool_call`, `tool_result`, `dataset_import`, `transform_run`, `artifact_created`, `memory_write`, `memory_update`, `memory_delete`, `operation_created`, `preference_changed`, `session_started`, `session_ended`.

**What to build**: Append-only. Never UPDATE or DELETE on `events`. Use canonical JSON serialization (sorted keys, no whitespace) for hash determinism. Concurrent-write safety: rely on SQLite's WAL + immediate transaction.

**Commit**: `feat(memory): events.py append-only event log with hash chain`

---

### [ ] Task 2.2 — tests/test_events.py

**Phase**: 2 · **Effort**: S · **Blocks**: 2.3

**Files to create**:
- `tests/test_events.py` — cases:
  - append produces increasing rowids and chained hashes
  - `verify_chain` returns True on a clean chain
  - manual UPDATE on a payload → `verify_chain` returns False
  - canonical JSON: `{"a": 1, "b": 2}` and `{"b": 2, "a": 1}` produce identical hashes
  - 1000 concurrent appends from threads → chain still verifies

**Commit**: `test(memory): event log + chain integrity`

---

### [ ] Task 2.3 — Memory-layer sessions module

**Phase**: 2 · **Effort**: M · **Blocks**: 2.4, 3.1+

**References**: `IRIS Memory Restructure.md` §7.1 sessions table

**Files to create**:
- `src/iris/projects/sessions.py` — public API:
  - `start_session(conn, *, project_id: str, model_provider: str, model_name: str, system_prompt: str) -> str` — inserts row, computes `system_prompt_hash`, writes `session_started` event, returns `session_id`.
  - `end_session(conn, *, session_id: str, summary: str)` — sets `ended_at`, sets `summary`, writes `session_ended` event.
  - `get_session(conn, session_id: str) -> dict`.

**Naming collision**: `src/iris/sessions.py` already exists for plot-output sessions. Decide: rename it to `src/iris/plot_sessions.py` and update imports, OR leave it and namespace the new one as `src/iris/projects/memory_sessions.py`. Recommend: rename the old one. Less surprising long-term.

**Files to modify** (if rename chosen):
- `src/iris/sessions.py` → `src/iris/plot_sessions.py`
- All imports across the repo (~5 sites; grep first).

**Commit**: `feat(memory): sessions table + start/end with event log`

---

### [ ] Task 2.4 — Daemon /memory/events + /memory/sessions + Express proxy

**Phase**: 2 · **Effort**: M · **Blocks**: 2.5

**Files to modify**:
- `src/iris/daemon/routes/memory.py` — replace Phase 0 stub with real router exposing:
  - `GET /memory/events?project=&type=&since=&until=&session_id=&limit=`
  - `GET /memory/events/<id>`
  - `POST /memory/events/verify_chain` (returns `{"valid": bool, "first_break": event_id | null}`)
  - `POST /memory/sessions/start` (body: `{model_provider, model_name, system_prompt}`)
  - `POST /memory/sessions/<id>/end` (body: `{summary}`)
  - `GET /memory/sessions/<id>`
- `iris-app/server/routes/memory.ts` — proxy these.

**Commit**: `feat(daemon): /memory/events + /memory/sessions endpoints`

---

### [ ] Task 2.5 — agent-bridge.ts: session lifecycle wiring

**Phase**: 2 · **Effort**: M · **Blocks**: Phase 3

**References**: `iris-app/server/agent-bridge.ts`

**Files to modify**:
- `iris-app/server/agent-bridge.ts`:
  - On first message of a conversation, call `POST /memory/sessions/start` with the system prompt and Claude model identifier; store returned `session_id` per project.
  - On conversation-close signal (e.g., when the SDK session ends or a new one is requested), call `POST /memory/sessions/<id>/end` with a brief summary.
  - Pass `session_id` through to subsequent memory writes (Phase 3+).

**Validation additions** (Phase 2 boundary):
- Playwright `iris-app/e2e/phase2.spec.ts`: create project, send 1 chat message, assert exactly one `session_started` event in `iris.sqlite`. Restart daemon. Send another message, assert a second `session_started` event.

**Commit**: `feat(webapp): session lifecycle via /memory/sessions`

**Done when**: Phase 2 E2E passes. Tag `phase-2-complete`.

---

## Phase 3 — Messages, Tool Calls, FTS5

Goal: every chat message and tool invocation persists to SQLite with FTS5 search. Tool-result clearing lands in this phase.

### [ ] Task 3.1 — messages.py

**Phase**: 3 · **Effort**: M · **Blocks**: 3.3, 3.5

**References**: `IRIS Memory Restructure.md` §7.1 messages + messages_fts

**Files to create**:
- `src/iris/projects/messages.py` — `append_message(conn, *, session_id, role, content, event_id, token_count=None) -> str`. Insert into `messages` and into `messages_fts` (triggers handle this if defined; otherwise explicit insert). `search(conn, *, project_id, query, limit) -> list[dict]` using FTS5 BM25.

**Commit**: `feat(memory): messages.py + FTS5 search`

---

### [ ] Task 3.2 — tool_calls.py

**Phase**: 3 · **Effort**: M · **Blocks**: 3.3, 3.6

**References**: `IRIS Memory Restructure.md` §7.1 tool_calls, §9.3 (tool-result clearing)

**Files to create**:
- `src/iris/projects/tool_calls.py` — `append_tool_call(conn, *, session_id, event_id, tool_name, input, success, output_summary=None, output_artifact_id=None, error=None, execution_time_ms=None) -> str`. `attach_output_artifact(conn, tool_call_id, artifact_id)`. `summarize_for_clearing(tool_call_id, output_text) -> str` returns `[Tool result for {name}: {1-line summary}. Full output as artifact {id}.]` for the agent-bridge to substitute into the conversation.

**Commit**: `feat(memory): tool_calls.py + clearing-stub helper`

---

### [ ] Task 3.3 — Daemon /memory/messages + /memory/tool_calls

**Phase**: 3 · **Effort**: S · **Blocks**: 3.5

**Files to modify**:
- `src/iris/daemon/routes/memory.py` — add:
  - `POST /memory/messages` (append)
  - `GET /memory/messages?session_id=&limit=&offset=`
  - `GET /memory/messages/search?project=&q=&limit=`
  - `POST /memory/tool_calls`
  - `PATCH /memory/tool_calls/<id>/output_artifact`
- `iris-app/server/routes/memory.ts` — proxy.

**Commit**: `feat(daemon): /memory/messages + /memory/tool_calls`

---

### [ ] Task 3.4 — Tests for messages + tool_calls

**Phase**: 3 · **Effort**: S · **Blocks**: 3.5

**Files to create**:
- `tests/test_messages.py` — append + FTS5 BM25 returns hits in expected order
- `tests/test_tool_calls.py` — append, attach artifact, summarize_for_clearing format

**Commit**: `test(memory): messages + tool_calls coverage`

---

### [ ] Task 3.5 — agent-bridge.ts: message + tool-call logging

**Phase**: 3 · **Effort**: M · **Blocks**: 3.6

**Files to modify**:
- `iris-app/server/agent-bridge.ts`:
  - `logTurn()` rewritten: for every assistant message, call `POST /memory/messages`. For every `tool_use` block, call `POST /memory/tool_calls` with input + tool name. For every `tool_result`, update the matching tool_call row (success, output_summary, output_artifact_id if applicable).
  - Fire-and-forget pattern preserved (failures logged, never raised).

**Commit**: `feat(webapp): persist messages + tool calls per turn`

---

### [ ] Task 3.6 — Tool-result clearing (V1 critical)

**Phase**: 3 · **Effort**: L · **Blocks**: Phase 4

**References**: `IRIS Memory Restructure.md` §9.3 (single most impactful compaction rule)

**Files to modify**:
- `iris-app/server/agent-bridge.ts`:
  - After the assistant has responded to a turn that consumed tool results, replace the `tool_result` content blocks in the SDK conversation buffer with the stub from `summarize_for_clearing`. Keep the `tool_use` record intact.
  - Stubs persist across all subsequent turns of the session.
  - Configurable threshold: only clear results larger than N tokens (default 500 from `config.toml [agent.dials]`).

**Files to create**:
- `iris-app/server/services/tool-result-clearing.ts` — pure-function module: takes the SDK message array + a list of tool_call_ids to clear, returns the cleared array. Easy to unit-test.
- `iris-app/server/__tests__/tool-result-clearing.test.ts` — Vitest cases.
- `tests/test_tool_result_clearing_e2e.py` — Python integration: agent-bridge run with mock SDK that returns large tool results; assert subsequent turns see stubs not full output.

**Validation additions** (Phase 3 boundary):
- Playwright `iris-app/e2e/phase3.spec.ts`: create project → trigger an op via chat → confirm tool_result body in subsequent turn payload is the stub format.
- Manual count check: after a 5-turn chat with one bulky tool call, the conversation context size should be much smaller than the sum of all tool outputs.

**Commit**: `feat(webapp): tool-result clearing (spec §9.3)`

**Done when**: Phase 3 E2E passes. Tag `phase-3-complete`.

---

## Phase 4 — Memory Entries (Unified L3)

Goal: collapse the old `goals` / `decisions` / `learned_facts` tables into one `memory_entries` table with a `memory_type` enum. Propose/commit pattern preserved (mapped onto user-approved promotion per spec §10.1).

### [ ] Task 4.1 — memory_entries.py

**Phase**: 4 · **Effort**: L · **Blocks**: 4.2, 4.3, all later memory tasks

**References**: `IRIS Memory Restructure.md` §4 Layer 3, §7.1 memory_entries, §10.1 (creation), §10.4 (deletion)

**Files to create**:
- `src/iris/projects/memory_entries.py` — public API:
  - `propose(conn, *, project_id, scope, memory_type, text, importance=5.0, confidence=0.5, evidence=None, tags=None, dataset_id=None) -> str` — inserts with `status='draft'`, writes `memory_write` event.
  - `commit_pending(conn, ids: list[str])` — flips `status='active'`, writes `memory_update` events.
  - `discard_pending(conn, ids: list[str])` — hard-deletes rows whose `status='draft'`. (Drafts have no audit-trail value if rejected.)
  - `query(conn, *, project_id, memory_type=None, status='active', dataset_id=None, scope=None, limit=100, order_by='importance DESC')`.
  - `set_status(conn, id, new_status)` — for archive/contradicted/superseded transitions. Writes event.
  - `supersede(conn, *, old_id, new_id)` — sets `superseded_by` + status, writes event.
  - `soft_delete(conn, id)` — `status='archived'`, writes `memory_delete` event.
  - `touch(conn, id)` — bumps `last_accessed_at` and `access_count` (for retrieval ranking).

**Commit**: `feat(memory): memory_entries.py unified L3`

---

### [ ] Task 4.2 — extraction.py (V1 minimum: session-end only)

**Phase**: 4 · **Effort**: L · **Blocks**: 4.3, 4.4

**References**: `IRIS Memory Restructure.md` §10.1 (passive extraction), §11.4 (importance threshold)

**Files to create**:
- `src/iris/projects/extraction.py` — `extract_session(conn, session_id) -> list[str]` returns the IDs of proposed memories. Pulls all messages of the session, sends to Claude (Anthropic SDK from Python; key from `ANTHROPIC_API_KEY`) with a structured prompt asking for: findings, assumptions, caveats, open_questions, decisions, failure_reflections. Each candidate gets an LLM-assigned importance score 1–10. Filter to importance ≥ 4. For each, call `memory_entries.propose` with status='draft'.

**Commit**: `feat(memory): extraction.py session-end LLM extraction`

---

### [ ] Task 4.3 — Daemon /memory/entries

**Phase**: 4 · **Effort**: M · **Blocks**: 4.4, 4.7

**Files to modify**:
- `src/iris/daemon/routes/memory.py` — endpoints:
  - `POST /memory/entries` (propose)
  - `POST /memory/entries/commit` (body: `{ids: [...]}`)
  - `POST /memory/entries/discard`
  - `GET /memory/entries?project=&type=&status=&scope=&dataset_id=&limit=`
  - `GET /memory/entries/<id>`
  - `PATCH /memory/entries/<id>/status`
  - `POST /memory/entries/supersede`
  - `DELETE /memory/entries/<id>` (soft)
  - `POST /memory/extract` (body: `{session_id}` → returns proposed IDs)
- `iris-app/server/routes/memory.ts` — proxy.

**Commit**: `feat(daemon): /memory/entries CRUD + extract`

---

### [ ] Task 4.4 — Tests for memory_entries + extraction

**Phase**: 4 · **Effort**: M · **Blocks**: 4.5

**Files to create**:
- `tests/test_memory_entries.py` — propose roundtrip, commit, discard, supersession chain, soft-delete preserves audit row, query filters work.
- `tests/test_extraction.py` — synthetic transcript fixture; mock Anthropic SDK to return canned extraction; assert correct number of drafts proposed with correct importance threshold.

**Commit**: `test(memory): memory_entries + extraction coverage`

---

### [ ] Task 4.5 — markdown_sync.py

**Phase**: 4 · **Effort**: L · **Blocks**: 4.6

**References**: `IRIS Memory Restructure.md` §5.1 (Store 3), Appendix Decision Log (dual: DB + file)

**Files to create**:
- `src/iris/projects/markdown_sync.py` — public API:
  - `regenerate_markdown(conn, project_path)`: regenerates `memory/PROJECT.md`, `memory/DECISIONS.md`, `memory/OPEN_QUESTIONS.md`, `memory/DATASETS/<id>.md` from the DB.
  - `ingest_markdown(conn, project_path)`: detects user edits, parses them back into `memory_entries` updates (proposed, not auto-committed).
  - Strategy: deterministic templates with HTML-comment markers `<!-- memory_id: xyz -->` so round-trip is reliable.

**What to build**: DB is source of truth. MD regenerated on every memory commit. User edits to MD become draft proposals.

**Commit**: `feat(memory): markdown_sync.py bidirectional sync`

---

### [ ] Task 4.6 — Markdown file watcher + endpoint

**Phase**: 4 · **Effort**: M · **Blocks**: 4.7

**Files to create**:
- `src/iris/daemon/services/markdown_watcher.py` — on daemon startup, register a watchdog observer on `projects/<active>/memory/`. On change, debounce 2s, call `markdown_sync.ingest_markdown`.

**Files to modify**:
- `src/iris/daemon/app.py` — start the watcher on startup, stop on shutdown.
- `src/iris/daemon/routes/memory.py` — `POST /memory/regenerate_markdown` (manual trigger).

**Commit**: `feat(daemon): markdown sync watcher + endpoint`

---

### [ ] Task 4.7 — Frontend rewire + Phase 4 E2E

**Phase**: 4 · **Effort**: M · **Blocks**: Phase 5

**Files to modify**:
- `iris-app/src/renderer/lib/api.ts` — replace old `listKnowledge` / `listPending` / `commitSession` calls with the new `/memory/entries` shape.
- `iris-app/src/renderer/components/workspace/MemoryInspector.tsx` — adapt to single `memory_entries` shape with `memory_type` filter (instead of per-table tabs). Keep tab UX, just route them all through the same endpoint.
- `iris-app/src/renderer/components/workspace/CurationRitual.tsx` — adapt approve/reject to `/memory/entries/commit` and `/memory/entries/discard`.

**Validation additions** (Phase 4 boundary):
- Playwright `iris-app/e2e/phase4.spec.ts`: create project → simulate a chat that produces 2 findings + 1 open question → end session → trigger extract → 3 drafts visible in CurationRitual → approve all → 3 active memories visible in MemoryInspector → memory/PROJECT.md on disk shows the 3 entries.

**Commit**: `feat(webapp): rewire memory inspector + curation to new API`

**Done when**: Phase 4 E2E passes. Tag `phase-4-complete`.

---

## Phase 5 — Artifacts (Content-Addressed Store)

Goal: every "heavy" output (plot, report, slide deck, code file, cache) lives at `artifacts/<sha256>/` with metadata in SQLite.

### [ ] Task 5.1 — artifacts.py

**Phase**: 5 · **Effort**: M · **Blocks**: 5.2, 5.3

**References**: `IRIS Memory Restructure.md` §5.1 (Store 2), §7.1 artifacts table

**Files to create**:
- `src/iris/projects/artifacts.py` — public API:
  - `store(conn, project_path, *, content: bytes, type: str, metadata: dict | None = None, description: str | None = None) -> str` — computes SHA-256, writes to `artifacts/<sha>/blob` if not already present, inserts `artifacts` row, writes `artifact_created` event. Returns `artifact_id`.
  - `get_bytes(conn, project_path, artifact_id) -> bytes`.
  - `get_metadata(conn, artifact_id) -> dict`.
  - `list(conn, *, project_id, type=None, run_id=None) -> list[dict]`.
  - `soft_delete(conn, artifact_id)` — sets a deleted_at column (add to schema in 5.1 if not present); preserves file for retention window.

**Commit**: `feat(memory): artifacts.py content-addressed store`

---

### [ ] Task 5.2 — Tests for artifacts

**Phase**: 5 · **Effort**: S · **Blocks**: 5.3

**Files to create**:
- `tests/test_artifacts.py` — dedup (same bytes → same artifact_id, single file on disk), all spec types round-trip, metadata persists, list filters work.

**Commit**: `test(memory): artifacts coverage`

---

### [ ] Task 5.3 — Migrate plot output to artifacts

**Phase**: 5 · **Effort**: L · **Blocks**: 5.4

**Files to modify**:
- `src/iris/plot_sessions.py` (renamed from `sessions.py` in Task 2.3) — every plot save now goes through `artifacts.store(type='plot_png')`. Manifest references `artifact_id` not file paths.
- `src/iris/plot_backends/matplotlib.py` (and any others) — accept the artifact-aware writer.
- All call sites in `engine/executor.py` updated.

**Commit**: `refactor(engine): plots stored as artifacts`

---

### [ ] Task 5.4 — Daemon /artifacts

**Phase**: 5 · **Effort**: S · **Blocks**: 5.5

**Files to modify**:
- `src/iris/daemon/routes/artifacts.py` (new file) — `GET /artifacts/<id>` (binary), `HEAD /artifacts/<id>` (metadata as headers), `GET /artifacts?type=&run_id=&project=`.
- `iris-app/server/routes/artifacts.ts` — proxy with stream pass-through for binary.

**Commit**: `feat(daemon): /artifacts endpoints`

---

### [ ] Task 5.5 — Frontend artifact rendering + Phase 5 E2E

**Phase**: 5 · **Effort**: M · **Blocks**: Phase 6

**Files to modify**:
- `iris-app/src/renderer/components/PlotViewer.tsx` (or wherever plots render) — fetch images via `/artifacts/<id>` instead of static URLs.
- `iris-app/src/renderer/lib/api.ts` — `getArtifact(id) -> Blob`, `listArtifacts(filters)`.

**Validation additions** (Phase 5 boundary):
- Playwright `iris-app/e2e/phase5.spec.ts`: run an op → plot appears → confirm `artifacts/<sha>/blob` exists on disk → confirm img src is `/api/artifacts/<id>`.

**Commit**: `feat(webapp): plots fetched as artifacts`

**Done when**: Phase 5 E2E passes. Tag `phase-5-complete`.

---

## Phase 6 — Datasets, Versions, Profile

### [ ] Task 6.1 — datasets.py

**Phase**: 6 · **Effort**: M · **Blocks**: 6.2, 6.3

**References**: `IRIS Memory Restructure.md` §7.1 datasets + dataset_versions

**Files to create**:
- `src/iris/projects/datasets.py` — `import_dataset(conn, project_path, *, file_path, name) -> str`. Computes content hash, copies to `datasets/raw/<dataset_id>/<sha>.<ext>`, inserts `datasets` and `dataset_versions` rows. Writes `dataset_import` event. `list_datasets(conn, project_id)`. `get_version(conn, dataset_version_id)`.

**Commit**: `feat(memory): datasets.py + raw version capture`

---

### [ ] Task 6.2 — transformations.py

**Phase**: 6 · **Effort**: M · **Blocks**: 6.3

**Files to create**:
- `src/iris/projects/transformations.py` — `record_derived_version(conn, *, parent_dataset_version_id, transform_run_id, output_path, schema_json, row_count) -> str`. Inserts `dataset_versions` row with `derived_from_dataset_version_id` set. Used by Phase 7 runs.

**Commit**: `feat(memory): transformations.py derived versions`

---

### [ ] Task 6.3 — profile.py rebuilt

**Phase**: 6 · **Effort**: L · **Blocks**: 6.4

**References**: existing deleted `profile.py` for the dispatch pattern (CSV, Parquet, JSON, H5, NetCDF, NumPy, SQLite — but as ports, not preservation)

**Files to create**:
- `src/iris/projects/profile.py` — `profile_dataset(conn, dataset_version_id) -> dict`. Reads file, computes column schema/stats (matches old shape: column name, inferred type, missing %, sample values, range). Writes result into `dataset_versions.schema_json`. For each column, calls `memory_entries.propose(scope='dataset', memory_type='caveat'|'finding', text=...)` with `dataset_id` set, status='draft'.

**Commit**: `feat(memory): profile.py with annotation proposals`

---

### [ ] Task 6.4 — Daemon /datasets

**Phase**: 6 · **Effort**: M · **Blocks**: 6.5

**Files to modify**:
- `src/iris/daemon/routes/datasets.py` — `POST /datasets/import`, `GET /datasets`, `GET /datasets/<id>/versions`, `POST /datasets/<id>/profile`.
- Express proxy in `iris-app/server/routes/datasets.ts`.

**Commit**: `feat(daemon): /datasets endpoints`

---

### [ ] Task 6.5 — Tests for datasets + profile

**Phase**: 6 · **Effort**: M · **Blocks**: 6.6

**Files to create**:
- `tests/test_datasets.py` — import, version chain, hash dedup, list.
- `tests/test_profile.py` — CSV/Parquet fixtures; assert schema_json populated and N draft annotations proposed.

**Commit**: `test(memory): datasets + profile coverage`

---

### [ ] Task 6.6 — Frontend dataset upload + Phase 6 E2E

**Phase**: 6 · **Effort**: M · **Blocks**: Phase 7

**Files to modify**:
- `iris-app/src/renderer/components/workspace/ProfileConfirmation.tsx` — adapt to new endpoints. Approve/reject draft annotations via `/memory/entries/commit` (no UX change).
- `iris-app/src/renderer/lib/api.ts` — `importDataset`, `profileDataset`, `listDatasets`.

**Validation additions** (Phase 6 boundary):
- Playwright `iris-app/e2e/phase6.spec.ts`: upload sample CSV → profile runs → 5 column annotations propose → user approves 3 → DB has 3 active memory entries scoped to that dataset.

**Commit**: `feat(webapp): dataset upload + profile flow`

**Done when**: Phase 6 E2E passes. Tag `phase-6-complete`.

---

## Phase 7 — Runs DAG (Provenance)

### [ ] Task 7.1 — runs.py

**Phase**: 7 · **Effort**: L · **Blocks**: 7.2

**References**: `IRIS Memory Restructure.md` §4 Layer 4 (analysis/runs index), §7.1 runs table

**Files to create**:
- `src/iris/projects/runs.py` — public API:
  - `start_run(conn, *, project_id, session_id, operation_type, operation_id=None, parent_run_id=None, input_versions, parameters, code, llm_model=None) -> str`
  - `complete_run(conn, run_id, *, output_data_hash=None, output_artifact_ids=None, findings_text=None, execution_time_ms=None)`
  - `fail_run(conn, run_id, *, error_text, failure_reflection=None)`
  - `query_lineage(conn, run_id) -> {ancestors: [...], descendants: [...]}`
  - `list_runs(conn, *, project_id, status=None, operation_type=None, since=None, limit=100)`

Each call writes corresponding events (`transform_run` for start/complete).

**Commit**: `feat(memory): runs.py provenance DAG`

---

### [ ] Task 7.2 — Wire engine executor to runs

**Phase**: 7 · **Effort**: L · **Blocks**: 7.3

**Files to modify**:
- `src/iris/engine/executor.py` — every `run_pipeline()` invocation wraps in `start_run` / `complete_run` / `fail_run`. Captures: input dataset versions (from project context), parameters (from DSL parse), code (the DSL source string for now; later the actual op source), output artifact IDs (from the new artifact-backed plot writer in Phase 5).
- `src/iris/engine/cache.py` — cache hits also recorded as completed runs (with a flag `cache_hit=True` in metadata).

**Commit**: `feat(engine): runs recorded for every pipeline execution`

---

### [ ] Task 7.3 — Daemon /memory/runs

**Phase**: 7 · **Effort**: S · **Blocks**: 7.4

**Files to modify**:
- `src/iris/daemon/routes/memory.py` — `GET /memory/runs?project=&status=&op=&since=`, `GET /memory/runs/<id>`, `GET /memory/runs/<id>/lineage`.
- Express proxy.

**Commit**: `feat(daemon): /memory/runs endpoints`

---

### [ ] Task 7.4 — Tests for runs

**Phase**: 7 · **Effort**: M · **Blocks**: 7.5

**Files to create**:
- `tests/test_runs.py` — start/complete/fail flows, parent-child branching, lineage walk (3-deep chain), cache-hit recording, failure reflection storage.

**Commit**: `test(memory): runs DAG coverage`

---

### [ ] Task 7.5 — Frontend run history + Phase 7 E2E

**Phase**: 7 · **Effort**: M · **Blocks**: Phase 8

**Files to create**:
- `iris-app/src/renderer/components/workspace/RunHistory.tsx` — minimal flat list of recent runs with status, operation, timestamp, link to artifact. New tab in WorkspaceTabs.

**Files to modify**:
- `iris-app/src/renderer/lib/api.ts` — `listRuns(filters)`, `getRunLineage(id)`.

**Validation additions** (Phase 7 boundary):
- Playwright `iris-app/e2e/phase7.spec.ts`: run two ops sequentially → both appear in RunHistory → click second → lineage shows first as parent.

**Commit**: `feat(webapp): run history panel + lineage`

**Done when**: Phase 7 E2E passes. Tag `phase-7-complete`.

---

## Phase 8 — Operations Table

Goal: catalog every hardcoded op (the existing 17) into the `operations` table. Sets the foundation for Phase 15 (dynamic operation generation in V2).

### [ ] Task 8.1 — operations_store.py

**Phase**: 8 · **Effort**: M · **Blocks**: 8.2

**References**: `IRIS Memory Restructure.md` §4 Layer 5, §7.1 operations + operation_executions, §12

**Files to create**:
- `src/iris/projects/operations_store.py` — public API:
  - `register(conn, *, project_id=None, name, version, description, input_schema, output_schema, code, validation_status='validated') -> str` — bundles code as artifact, computes hash, inserts row. Writes `operation_created` event. Idempotent on `(name, version, code_hash)`.
  - `find(conn, name, version=None) -> dict | None`.
  - `list(conn, *, project_id=None, validation_status=None) -> list[dict]`.
  - `record_execution(conn, *, op_id, run_id, input_hash, output_hash, success, error=None, execution_time_ms=None)` — inserts `operation_executions`, updates `use_count`, `success_rate`, `last_used_at`.

**Commit**: `feat(memory): operations_store.py CRUD`

---

### [ ] Task 8.2 — Catalog hardcoded ops at daemon startup

**Phase**: 8 · **Effort**: M · **Blocks**: 8.3

**Files to modify**:
- `src/iris/daemon/app.py` — on startup (after schema init), iterate `engine.factory.create_registry()`. For each registered op: pull source code from the op handler module, build description from docstring, build input/output schema from `engine.type_system.TYPE_TRANSITIONS`, call `operations_store.register(project_id=None, ..., validation_status='validated')`. Skip if already registered (hash match).

**Commit**: `feat(daemon): catalog hardcoded ops at startup`

---

### [ ] Task 8.3 — Daemon /operations

**Phase**: 8 · **Effort**: S · **Blocks**: 8.4

**Files to modify**:
- `src/iris/daemon/routes/operations.py` — `GET /operations?project=&validation_status=`, `GET /operations/<id>`.
- Express proxy.

**Commit**: `feat(daemon): /operations endpoints`

---

### [ ] Task 8.4 — Tests for operations + Phase 8 E2E

**Phase**: 8 · **Effort**: S · **Blocks**: Phase 9

**Files to create**:
- `tests/test_operations_store.py` — register + idempotent re-register, list filters, execution recording updates use_count and success_rate.

**Validation additions** (Phase 8 boundary):
- Playwright phase8: fresh project → daemon startup → assert exactly N hardcoded ops registered → run an op → operation_executions row appears → use_count=1.

**Commit**: `test(memory): operations_store coverage`

**Done when**: Phase 8 E2E passes. Tag `phase-8-complete`.

---

## Phase 9 — Retrieval Pipeline (V1: FTS5 + Triple-Weighted)

### [ ] Task 9.1 — retrieval.py

**Phase**: 9 · **Effort**: L · **Blocks**: 9.2

**References**: `IRIS Memory Restructure.md` §8 (full pipeline), §11.5 (over-retrieval defenses)

**Files to create**:
- `src/iris/projects/retrieval.py` — public API:
  - `should_retrieve(query: str) -> bool` — gate (V1: rule-based; matches patterns from §8.2 like "what did we", "show me", "remember", dataset references).
  - `recall(conn, *, project_id, query, k=10, max_tokens=1500, weights=(0.5, 0.2, 0.3), filters=None) -> list[dict]`. Stages: structured filter, FTS5 BM25, rerank by `α*relevance_norm + β*recency + γ*importance_norm`, deduplicate (text similarity > 0.92 → keep higher-scored), truncate to `k`, then to `max_tokens`. Side-effect: `memory_entries.touch()` on each returned memory.

Recency formula: `exp(-Δdays / half_life_days)` with `half_life_days` from project config.

**Commit**: `feat(memory): retrieval.py three-stage pipeline (V1)`

---

### [ ] Task 9.2 — Daemon /memory/recall

**Phase**: 9 · **Effort**: S · **Blocks**: 9.3

**Files to modify**:
- `src/iris/daemon/routes/memory.py` — `POST /memory/recall` body: `{query, k?, max_tokens?, filters?}` returns ranked memories with evidence pointers.

**Commit**: `feat(daemon): /memory/recall`

---

### [ ] Task 9.3 — slice_builder.py

**Phase**: 9 · **Effort**: L · **Blocks**: 9.4

**References**: `IRIS Memory Restructure.md` §9.1 (segment structure), §9.2 (token budgets)

**Files to create**:
- `src/iris/projects/slice_builder.py` — `build_slice(conn, *, project_id, session_id, current_query=None, budgets=None) -> dict`. Returns 7 segments per spec §9.1: system_prompt, core_memory, dataset_context, retrieved_memories, prior_analyses, operations, conversation_window. Each segment respects its token budget. Segment 4 only populated if `should_retrieve(current_query)`.

**Commit**: `feat(memory): slice_builder.py 7-segment assembly`

---

### [ ] Task 9.4 — Daemon /memory/slice

**Phase**: 9 · **Effort**: S · **Blocks**: 9.5

**Files to modify**:
- `src/iris/daemon/routes/memory.py` — `POST /memory/slice` body: `{session_id, current_query?, budgets?}` returns the slice payload.

**Commit**: `feat(daemon): /memory/slice`

---

### [ ] Task 9.5 — agent-bridge.ts: prompt assembly via slice

**Phase**: 9 · **Effort**: L · **Blocks**: 9.6

**Files to modify**:
- `iris-app/server/agent-bridge.ts`:
  - `buildSystemPrompt()` rewritten: call `POST /memory/slice` with current user query, render the 7 segments in spec order. Stable prefix first (segments 1–3) for prompt-cache friendliness.
  - Drop the old behavior-dial block; dials now live in `[agent.dials]` of `config.toml` and are read by slice_builder into segment 1.

**Commit**: `feat(webapp): agent prompt assembled via /memory/slice`

---

### [ ] Task 9.6 — Tests for retrieval + slice + Phase 9 E2E

**Phase**: 9 · **Effort**: M · **Blocks**: Phase 10

**Files to create**:
- `tests/test_retrieval.py` — synthetic project with planted memories (varied importance, age, relevance). Assert ranking matches expected order. Assert dedup eliminates near-duplicates. Assert gate skips retrieval for "thanks", "ok", and other simple follow-ups.
- `tests/test_slice_builder.py` — token budget enforcement, all 7 segments present, segment 4 absent when gate says no.

**Validation additions** (Phase 9 boundary):
- Playwright phase9: project with seeded memories → user asks "what did we conclude about X?" → assistant response cites the planted memory → confirm `/memory/recall` was called with that query.

**Commit**: `test(memory): retrieval + slice coverage`

**Done when**: Phase 9 E2E passes. Tag `phase-9-complete`.

---

## Phase 10 — V1 Wrap-Up + Phase Gate

### [ ] Task 10.1 — Rewrite docs/architecture.md

**Phase**: 10 · **Effort**: M · **Blocks**: 10.4

**Files to modify**:
- `docs/architecture.md` — full rewrite. New module layout (`src/iris/projects/`), unified `iris.sqlite`, event log, memory layers map to spec §4. Engine package described as stable. Webapp described.

**Commit**: `docs: rewrite architecture for V1 memory`

---

### [ ] Task 10.2 — Rewrite docs/projects.md

**Phase**: 10 · **Effort**: M · **Blocks**: 10.4

**Files to modify**:
- `docs/projects.md` — full rewrite against new TEMPLATE + spec §6 layout. Document `iris.sqlite` lifecycle, MD sync semantics.

**Commit**: `docs: rewrite project contract`

---

### [ ] Task 10.3 — Add docs/memory.md

**Phase**: 10 · **Effort**: S · **Blocks**: 10.4

**Files to create**:
- `docs/memory.md` — short reference (~200 lines max). Defers to `IRIS Memory Restructure.md` for design; lists code locations for each layer; documents `propose → commit` flow; documents tool-result clearing.

**Commit**: `docs: add memory.md code-pointer reference`

---

### [ ] Task 10.4 — Phase 10 E2E + V1 tag

**Phase**: 10 · **Effort**: M · **Blocks**: Phase 11

**Validation additions**:
- `iris-app/e2e/v1-acceptance.spec.ts`: full V1 acceptance:
  1. Fresh project create
  2. Upload sample CSV
  3. Profile runs, 3 annotations approved
  4. Run op, plot appears
  5. Chat: "what did we find?" → assistant cites the annotations
  6. Session ends → extraction proposes 2 findings
  7. User approves both
  8. Restart daemon
  9. Reopen project → memories still there, MD files reflect them
  10. Verify event chain integrity

**Commit**: `chore: V1 acceptance gate`

**Done when**: V1 E2E passes. Tag commit `v1.0-memory`.

---

## Phase 11 — V2: Vector Search via sqlite-vec

### [ ] Task 11.1 — Add sqlite-vec dependency + db.py loader

**Phase**: 11 · **Effort**: S · **Blocks**: 11.2

**Files to modify**:
- `pyproject.toml` — add `sqlite-vec`.
- `src/iris/projects/db.py` — on connect, `conn.enable_load_extension(True); conn.load_extension(sqlite_vec.loadable_path())`.

**Commit**: `feat(memory): sqlite-vec dependency + loader`

---

### [ ] Task 11.2 — Schema migration v1 → v2

**Phase**: 11 · **Effort**: M · **Blocks**: 11.3

**Files to create**:
- `src/iris/projects/migrations/v2.sql` — `CREATE VIRTUAL TABLE memory_entries_vec USING vec0(embedding float[384])`. Same for `operations_vec`. `PRAGMA user_version = 2`.

**Files to modify**:
- `src/iris/projects/db.py` — `migrate(conn, target_version=2)` reads `v2.sql` when current is 1.

**Commit**: `feat(memory): schema v2 with sqlite-vec virtual tables`

---

### [ ] Task 11.3 — embeddings.py provider

**Phase**: 11 · **Effort**: M · **Blocks**: 11.4

**References**: `IRIS Memory Restructure.md` §14.2

**Files to create**:
- `src/iris/projects/embeddings.py` — abstract `EmbeddingProvider`. Implementations: `SentenceTransformerProvider("all-MiniLM-L6-v2")` (default, local, 384-dim), `OllamaProvider("nomic-embed-text")` (768-dim, optional). Selected via `[memory.embeddings]` in `config.toml`.

**Commit**: `feat(memory): embeddings.py provider abstraction`

---

### [ ] Task 11.4 — Background embedding job

**Phase**: 11 · **Effort**: M · **Blocks**: 11.5

**Files to modify**:
- `src/iris/projects/memory_entries.py` — on commit, enqueue an embedding job (BackgroundTasks via FastAPI, or a simple thread queue).
- `src/iris/projects/operations_store.py` — on register, enqueue.

**Files to create**:
- `src/iris/projects/embedding_worker.py` — drains the queue, computes embeddings, inserts into `*_vec` tables.

**Commit**: `feat(memory): background embedding worker`

---

### [ ] Task 11.5 — Hybrid retrieval + Phase 11 E2E

**Phase**: 11 · **Effort**: L · **Blocks**: Phase 12

**Files to modify**:
- `src/iris/projects/retrieval.py` — hybrid: FTS5 candidates ∪ vector candidates, fused via reciprocal rank. Same triple-weighted rerank.

**Files to modify**:
- `tests/test_retrieval.py` — add cases: semantically related but lexically different memories should now retrieve.

**Validation additions** (Phase 11 boundary):
- Playwright phase11: seed memories with semantic-but-not-lexical relationships, query → assistant retrieves the right ones (V1 wouldn't have).

**Commit**: `feat(memory): hybrid FTS5 + vector retrieval`

**Done when**: Phase 11 E2E passes. Tag `phase-11-complete`.

---

## Phase 12 — V2: Continuous Extraction

### [ ] Task 12.1 — Per-turn extraction with dedup

**Phase**: 12 · **Effort**: L · **Blocks**: 12.2

**References**: `IRIS Memory Restructure.md` §10.1 + Mem0 description

**Files to modify**:
- `src/iris/projects/extraction.py` — add `extract_turn(conn, *, message_id) -> list[str]`. Pulls just the assistant turn + its tool calls, asks Claude for candidates, dedup against existing memories at >0.85 similarity (vector or FTS5).

**Commit**: `feat(memory): per-turn extraction (Mem0-style)`

---

### [ ] Task 12.2 — Daemon /memory/extract per-turn + agent-bridge wiring

**Phase**: 12 · **Effort**: M · **Blocks**: 12.3

**Files to modify**:
- `src/iris/daemon/routes/memory.py` — `POST /memory/extract/turn` body `{message_id}`.
- `iris-app/server/agent-bridge.ts` — after each substantive assistant turn, fire-and-forget the extract call.

**Commit**: `feat(webapp): per-turn extraction trigger`

---

### [ ] Task 12.3 — Tests for continuous extraction

**Files to modify**:
- `tests/test_extraction.py` — add per-turn cases with dedup verification.

**Commit**: `test(memory): per-turn extraction coverage`

---

### [ ] Task 12.4 — Frontend pending count + Phase 12 E2E

**Phase**: 12 · **Effort**: S · **Blocks**: Phase 13

**Files to modify**:
- `iris-app/src/renderer/components/workspace/CurationRitual.tsx` — show count badge of pending drafts; subscribe to a daemon `/memory/pending/count` endpoint or poll.

**Validation additions** (Phase 12 boundary):
- Playwright phase12: chat that yields 3 substantive turns → 3 sets of drafts proposed → CurationRitual badge shows correct count.

**Commit**: `feat(webapp): pending memory badge`

**Done when**: Phase 12 E2E passes. Tag `phase-12-complete`.

---

## Phase 13 — V2: Reflection Cycles

### [ ] Task 13.1 — reflection.py

**Phase**: 13 · **Effort**: L · **Blocks**: 13.2

**References**: `IRIS Memory Restructure.md` §10.2

**Files to create**:
- `src/iris/projects/reflection.py` — accumulator on importance scores since last reflection. When sum > threshold (default: 5–8 substantive analyses' worth, configurable), trigger LLM call asking for higher-level insights. Store as `memory_type='reflection'` with high importance + evidence pointers to source memories.

**Commit**: `feat(memory): reflection.py importance-triggered cycles`

---

### [ ] Task 13.2 — Daemon /memory/reflect

**Phase**: 13 · **Effort**: S · **Blocks**: 13.3

**Files to modify**:
- `src/iris/daemon/routes/memory.py` — `POST /memory/reflect` (manual trigger), background scheduler for automatic.

**Commit**: `feat(daemon): /memory/reflect`

---

### [ ] Task 13.3 — Tests + Phase 13 E2E

**Phase**: 13 · **Effort**: M · **Blocks**: Phase 14

**Files to create**:
- `tests/test_reflection.py` — planted memories crossing threshold trigger reflection; reflection has correct evidence pointers.

**Validation additions**: Playwright phase13: seed 6 high-importance memories → trigger reflection → 1 reflection memory appears with all 6 as evidence.

**Commit**: `test(memory): reflection cycles`

**Done when**: Phase 13 E2E passes. Tag `phase-13-complete`.

---

## Phase 14 — V2: Progressive Summarization

### [ ] Task 14.1 — Session summarization at close + summary-of-summaries

**Phase**: 14 · **Effort**: L · **Blocks**: 14.2

**Files to modify**:
- `src/iris/projects/sessions.py` — `end_session()` calls extraction.summarize_session() to populate `sessions.summary`.

**Files to create**:
- `src/iris/projects/summarization.py` — `summarize_summaries(conn, project_id, n=10)` — when N session summaries accumulate, summarize them into a super-summary stored as `memory_entries(memory_type='session_summary')`.

**Commit**: `feat(memory): session + super-summaries`

---

### [ ] Task 14.2 — Retrieval integration

**Files to modify**:
- `src/iris/projects/retrieval.py` — session summaries retrievable as a memory_type.

**Commit**: `feat(memory): summaries retrievable`

---

### [ ] Task 14.3 — Tests + Phase 14 E2E

**Files to create**:
- `tests/test_summarization.py`.

**Commit**: `test(memory): summarization coverage`. Tag `phase-14-complete`.

---

## Phase 15 — V2: Operation Validation

### [ ] Task 15.1 — op_validation.py

**Phase**: 15 · **Effort**: L · **Blocks**: 15.2

**References**: `IRIS Memory Restructure.md` §12.2

**Files to create**:
- `src/iris/projects/op_validation.py` — `validate_operation(conn, op_id) -> dict`. Stages: static (imports, syntax via `ast.parse`), unit tests (run any included `tests/` against synthetic inputs in subprocess sandbox), sample run (against real project data). Promotes status `draft → validated` or `→ rejected`.

**Commit**: `feat(memory): op_validation.py sandbox runner`

---

### [ ] Task 15.2 — Generated-op pipeline

**Phase**: 15 · **Effort**: L · **Blocks**: 15.3

**Files to modify**:
- `src/iris/projects/operations_store.py` — `propose_operation(conn, *, name, version, description, code, ...)` writes to `ops/<name>/v<semver>/{op.py,schema.json,tests/,README.md}`, registers with status='draft'. Subsequent `validate_operation` promotes.

**Commit**: `feat(memory): generated-op pipeline`

---

### [ ] Task 15.3 — Daemon endpoints

**Files to modify**:
- `src/iris/daemon/routes/operations.py` — `POST /operations/propose`, `POST /operations/<id>/validate`.

**Commit**: `feat(daemon): operation propose + validate endpoints`

---

### [ ] Task 15.4 — Tests + Phase 15 E2E

**Files to create**:
- `tests/test_op_validation.py`.

**Commit**: `test(memory): op validation`. Tag `phase-15-complete`.

---

## Phase 16 — V2: Contradictions + Staleness

### [ ] Task 16.1 — contradictions.py

**Phase**: 16 · **Effort**: M · **Blocks**: 16.2

**References**: `IRIS Memory Restructure.md` §10.3, §11.3, §7.1 contradictions

**Files to create**:
- `src/iris/projects/contradictions.py` — `detect_contradictions(conn, new_memory_id) -> list[str]` — LLM check against active memories of same scope/type; on positive, insert `contradictions` row, mark old `status='contradicted'`. `resolve(conn, contradiction_id, resolution_text, winning_memory_id)`.

**Commit**: `feat(memory): contradictions.py`

---

### [ ] Task 16.2 — staleness.py

**Phase**: 16 · **Effort**: M · **Blocks**: 16.3

**References**: `IRIS Memory Restructure.md` §10.3 (temporal decay)

**Files to create**:
- `src/iris/projects/staleness.py` — `scan(conn, project_id) -> list[str]` flags memories whose `last_validated_at` exceeds type-specific thresholds (90/30/60 days for finding/assumption/open_question). Sets `status='stale'`. Retrieval prefixes stale memories with `[Finding from {date}, may need revalidation]`.

**Commit**: `feat(memory): staleness.py temporal decay`

---

### [ ] Task 16.3 — Daemon + tests

**Files to modify**:
- `src/iris/daemon/routes/memory.py` — `GET /memory/contradictions`, `POST /memory/contradictions/<id>/resolve`, `POST /memory/staleness/scan`.

**Files to create**:
- `tests/test_contradictions.py`, `tests/test_staleness.py`.

**Commit**: `feat(daemon): contradictions + staleness`. Tag `phase-16-complete`.

---

## Phase 17 — V2: Retrieval Metrics + V2 Wrap

### [ ] Task 17.1 — Track retrieval-to-usage

**Files to modify**:
- `src/iris/projects/retrieval.py` — when a slice is built, record retrieved memory IDs in a new `retrieval_events` table.
- `src/iris/projects/messages.py` — when assistant message is logged, scan for memory citations (looking for the evidence-pointer pattern emitted by slice_builder), update `retrieval_events.was_used`.

**Files to create**:
- `src/iris/projects/migrations/v3.sql` — `retrieval_events` table. `PRAGMA user_version = 3`.

**Commit**: `feat(memory): retrieval-to-usage tracking`

---

### [ ] Task 17.2 — Daemon /memory/metrics

**Files to modify**:
- `src/iris/daemon/routes/memory.py` — `GET /memory/metrics?project=` returns retrieval-to-usage ratio, stale-hit rate, contradiction rate.

**Commit**: `feat(daemon): /memory/metrics`

---

### [ ] Task 17.3 — V2 acceptance gate

**Validation additions**: full V2 E2E covering: hybrid retrieval, continuous extraction, reflection cycle, contradiction injection, staleness scan, metrics endpoint.

**Commit**: `chore: V2 acceptance gate`. Tag `v2.0-memory`.

---

## Phase 18 — SpikeLab Port: Setup + Data Loaders

### [ ] Task 18.1 — Restructure engine/loaders/

**Phase**: 18 · **Effort**: M · **Blocks**: 18.2

**Files to modify**:
- `src/iris/engine/loaders.py` → `src/iris/engine/loaders/` package. Subfiles: `mea.py`, `calcium.py`, `rtsort.py` (existing content split out), plus new empty stubs `hdf5.py`, `nwb.py`, `kilosort.py`, `spikeinterface.py`.
- All imports updated.

**Commit**: `refactor(engine): loaders/ as package`

---

### [ ] Task 18.2 — Port HDF5 loader

**Phase**: 18 · **Effort**: M · **Blocks**: 18.3

**References**: `SpikeLab-main/src/spikelab/data_loaders/data_loaders.py` (HDF5 functions)

**Files to modify**:
- `src/iris/engine/loaders/hdf5.py` — port function-by-function. No `import spikelab`. IRIS-style names. Returns `MEATrace` or new `SpikeData` (after Phase 19).

**Commit**: `feat(loaders): port SpikeLab HDF5 loader`

---

### [ ] Task 18.3 — Port NWB loader (optional dep)

**Files to modify**:
- `src/iris/engine/loaders/nwb.py` — port. Add `neo`, `quantities` to `[project.optional-dependencies] nwb = [...]` in `pyproject.toml`. Runtime check raises actionable error if missing.

**Commit**: `feat(loaders): port NWB loader`

---

### [ ] Task 18.4 — Port KiloSort + SpikeInterface loaders

**Files to modify**:
- `src/iris/engine/loaders/kilosort.py`, `src/iris/engine/loaders/spikeinterface.py` — port.

**Commit**: `feat(loaders): port KiloSort + SpikeInterface loaders`

---

### [ ] Task 18.5 — Tests with synthetic fixtures + Phase 18 E2E

**Files to create**:
- `tests/fixtures/sample.h5`, `tests/fixtures/sample.nwb` (small synthetic).
- `tests/test_loaders_hdf5.py`, `tests/test_loaders_nwb.py`, etc.

**Validation additions** (Phase 18 boundary): playwright upload sample.h5 → loader runs → DataType returned matches `SpikeData` (placeholder until Phase 19) or `MEATrace`.

**Commit**: `test(loaders): SpikeLab loader ports`. Tag `phase-18-complete`.

---

## Phase 19 — SpikeLab Port: Core Data Types

### [ ] Task 19.1 — New DataType entries

**Phase**: 19 · **Effort**: M · **Blocks**: 19.2

**References**: `SpikeLab-main/src/spikelab/spikedata/spikedata.py`, `ratedata.py`, `spikeslicestack.py`

**Files to modify**:
- `src/iris/engine/types.py` — add `SpikeData`, `RateData`, `SpikeSliceStack`, `RateSliceStack` dataclasses. Mirror SpikeLab API surface (per-unit times in ms, etc.).
- `src/iris/engine/type_system.py` — extend `DataType` enum + register in `TYPE_TRANSITIONS`.

**Commit**: `feat(types): SpikeData, RateData, slice stacks`

---

### [ ] Task 19.2 — Port SpikeData methods

**Phase**: 19 · **Effort**: L · **Blocks**: 19.3

**Files to modify**:
- `src/iris/engine/types.py` — port methods of `SpikeData` from SpikeLab one-by-one. Tests mirror SpikeLab's `test_spikedata.py` cases.

**Files to create**:
- `tests/test_spikedata.py`.

**Commit**: `feat(types): SpikeData methods + tests`

---

### [ ] Task 19.3 — Port RateData

Same pattern as 19.2. **Commit**: `feat(types): RateData methods + tests`

---

### [ ] Task 19.4 — Port slice stacks

Same pattern. **Commit**: `feat(types): slice stacks + tests`

---

### [ ] Task 19.5 — Phase 19 E2E

Validation: playwright load sample.h5 → assert returned object is `SpikeData` with expected unit count + total spike count.

**Commit**: `test(types): SpikeLab core types end-to-end`. Tag `phase-19-complete`.

---

## Phase 20 — SpikeLab Port: Stat + Plot + Numba Utils

### [ ] Task 20.1 — Port stat_utils

**Files to modify**:
- `src/iris/engine/helpers.py` (or new `src/iris/engine/stat_utils.py`) — port from `SpikeLab-main/src/spikelab/spikedata/stat_utils.py`.

**Commit**: `feat(engine): port stat_utils`

---

### [ ] Task 20.2 — Port plot_utils

**Files to create**:
- `src/iris/plot_backends/spike_plots.py` — port from `SpikeLab-main/src/spikelab/spikedata/plot_utils.py`.

**Commit**: `feat(plot): port spike plot utils`

---

### [ ] Task 20.3 — Port numba_utils (gated)

**What to build**: Check whether SpikeLab numba_utils is heavily used by ports already done. If yes, port and add `numba` as an optional dep. If no, defer indefinitely and document.

**Commit**: `feat(engine): port numba_utils (gated)`

---

### [ ] Task 20.4 — Tests

**Files to create**:
- `tests/test_stat_utils.py`, `tests/test_spike_plots.py`, `tests/test_numba_utils.py` (if 20.3 done).

**Commit**: `test(engine): SpikeLab utils ports`. Tag `phase-20-complete`.

---

## Phase 21 — SpikeLab Port: Pairwise + Population Analyses

### [ ] Task 21.1 — Port pairwise ops

**Files to create**:
- `src/iris/engine/ops/pairwise.py` — port cross-correlation, synchrony, STTC, etc. as IRIS ops.

**Commit**: `feat(ops): port SpikeLab pairwise analyses`

---

### [ ] Task 21.2 — Port population ops

**Files to create**:
- `src/iris/engine/ops/population.py` — network metrics, dimensionality-reduction prep.

**Commit**: `feat(ops): port SpikeLab population analyses`

---

### [ ] Task 21.3 — Register in factory + config defaults

**Files to modify**:
- `src/iris/engine/factory.py` — register all new ops.
- `configs/config.toml` — add `[engine.ops.pairwise]`, `[engine.ops.population]` defaults.

**Commit**: `feat(engine): register pairwise + population ops`

---

### [ ] Task 21.4 — Document new ops

**Files to modify**:
- `docs/operations.md` — add sections for each ported op (math + signature + params).

**Commit**: `docs: pairwise + population op math`

---

### [ ] Task 21.5 — Tests + Phase 21 E2E

**Files to create**:
- `tests/test_pairwise.py`, `tests/test_population.py`.

**Validation additions** (Phase 21 boundary): playwright run a pairwise op on sample.h5 → plot rendered → run recorded with correct lineage.

**Commit**: `test(ops): pairwise + population coverage`. Tag `phase-21-complete`.

---

## Phase 22 — SpikeLab Port: Curation + Data Export

### [ ] Task 22.1 — Port curation helpers (routed through memory proposals)

**Files to create**:
- `src/iris/engine/ops/curation.py` — manual unit curation. Marking a unit as bad creates a `memory_entries` proposal (memory_type='caveat', scope='dataset') instead of a SpikeLab-style standalone metadata file.

**Commit**: `feat(ops): port curation through memory proposals`

---

### [ ] Task 22.2 — Port data exporters

**Files to create**:
- `src/iris/engine/exporters/__init__.py`, `kilosort.py`, `nwb.py` — port `SpikeLab-main/src/spikelab/data_loaders/data_exporters.py`.

**Commit**: `feat(engine): port SpikeLab data exporters`

---

### [ ] Task 22.3 — Tests

**Files to create**:
- `tests/test_curation.py`, `tests/test_exporters.py`.

**Commit**: `test: curation + exporters`. Tag `phase-22-complete`.

---

## Phase 23 — SpikeLab Port: Spike Sorting (Kilosort2)

This phase is gated by MATLAB + Kilosort2 availability. Tasks must runtime-check and skip cleanly when missing.

### [ ] Task 23.1 — Port recording_io

**Files to create**:
- `src/iris/engine/spike_sorting/__init__.py`, `recording_io.py` — port from `SpikeLab-main/src/spikelab/spike_sorting/recording_io.py`.

**Commit**: `feat(sorting): port recording_io`

---

### [ ] Task 23.2 — Port Kilosort2 pipeline runner

**Files to create**:
- `src/iris/engine/spike_sorting/pipeline.py`, `kilosort2_runner.py` — port `pipeline.py`, `rt_sort_runner.py`. Runtime check for MATLAB; raise actionable error if missing. Add `[project.optional-dependencies] sorting = [...]` if any new pip deps.

**Commit**: `feat(sorting): port Kilosort2 runner (gated)`

---

### [ ] Task 23.3 — Port rt_sort algorithm + model

**Files to create**:
- `src/iris/engine/spike_sorting/rt_sort/` — port `_algorithm.py`, `model.py`, `__init__.py`.

**Commit**: `feat(sorting): port rt_sort algorithm`

---

### [ ] Task 23.4 — Register as ops

**Files to modify**:
- `src/iris/engine/factory.py` — register `spike_sort`, `rt_sort` ops, gated behind feature detection.

**Commit**: `feat(engine): register spike-sorting ops`

---

### [ ] Task 23.5 — Tests + Phase 23 E2E

**Files to create**:
- `tests/test_spike_sorting.py` — mock MATLAB layer for unit tests; integration test marked `@pytest.mark.matlab` for opt-in runs.

**Commit**: `test(sorting): coverage`. Tag `phase-23-complete`.

---

## Phase 24 — Final Cleanup + Docs Refresh

### [ ] Task 24.1 — Whole-repo gate

Run maximalist gate across the entire repo. Fix every finding.

**Commit**: `chore: final cleanup pass`

---

### [ ] Task 24.2 — docs/architecture.md final refresh

Reflects V1 + V2 + SpikeLab ops. **Commit**: `docs: architecture v2.0-spikelab`

---

### [ ] Task 24.3 — docs/operations.md full catalog

Original 17 ops + ~25 SpikeLab-port ops. **Commit**: `docs: full operations catalog`

---

### [ ] Task 24.4 — README.md refresh

Features, install (note MATLAB/Kilosort optional), quickstart. **Commit**: `docs: README v2.0-spikelab`

---

### [ ] Task 24.5 — Final E2E + tag

`iris-app/e2e/v2-spikelab-acceptance.spec.ts`: project create → upload MEA HDF5 → profile → spike sort (skip if MATLAB absent) → pairwise correlation → plot → memory write → approve → reflect → contradiction injection → staleness scan → restart → all state preserved.

**Commit**: `chore: V2-spikelab acceptance gate`. Tag `v2.0-spikelab`.

---

## Done

When `v2.0-spikelab` tag exists and the acceptance gate is green, this revamp is complete. Subsequent work (V3, full Appendix A frontend rebuild, large-scale collaborative features) belongs in a new REVAMP-V3.md.
