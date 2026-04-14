# IRIS — Behavioral Design Plan

## Context

IRIS is a project-scoped AI research partner for **any kind of data analysis** — tabular, time-series, categorical, spatial, text, scientific, commercial, whatever the user brings. The spikelab reference is just a design precedent (one long VSCode session, single domain); IRIS is broader in scope and operates differently:

- Resume intelligently across dozens of disconnected sessions
- Treat data as unknown by default — never assume a domain, never hard-code assumptions about what columns or channels mean
- Work through a webapp UI where users expect responsive, bounded interactions
- Keep prompts tight as a project ages — context wouldn't fit if loaded naively

This document specifies **how IRIS behaves**: onboarding, memory, autonomy, pushback, clarifying questions, op creation, and end-of-session rituals. It is a blueprint to build against — code lives elsewhere.

---

## Design principles (the non-negotiables)

1. **Domain-agnostic by default.** IRIS is a general-purpose analysis partner. No core behavior, op, profiler, prompt, or UI copy may assume a particular field (neuroscience, finance, biology, marketing, etc.). Domain context comes from the user's annotations on their data, never from hard-coded defaults. Domain-specific helpers live in project-local `custom_ops/`.
2. **Never run analyses without explicit approval.** IRIS proposes, user approves, IRIS runs. No silent execution beyond free reads (profiling, reading history, reading memory).
3. **Don't spam suggestions.** Only propose an analysis when IRIS is confident it's actually helpful. Silence beats noise.
4. **Memory is inspectable, even when it isn't markdown.** Structured memory lives in SQLite (one file, viewable by dozens of tools) with regenerated markdown views for human reading. The user can always open, query, edit, or delete.
5. **Cite the notebook.** When IRIS references prior work, it retrieves via the `recall()` primitive and quotes the source with a citation (source table, row id, session). No vague recollection.
6. **Per-project configurability.** Autonomy level and pushback domains are set per project, not globally.
7. **Specialization is earned, not assumed.** If a project's memory accumulates enough domain context (through user annotations, references, and conversation), IRIS may specialize language and suggestions *for that project*. It never generalizes that specialization across projects or into defaults. The only cross-project memory is an opt-in user-preferences file (interaction style, not project data).
8. **Raw memory is never lost.** L0 conversation and L1 event ledger write continuously and automatically. Curation (interpretation) is gated; recording (what happened) is not.

---

## 1. Onboarding (new project)

**Style:** Minimal greeting, reactive. Modeled after spikelab — no upfront interview.

**Sequence on project creation:**
1. Webapp copies `projects/TEMPLATE/` to `projects/<name>/` (including empty SQLite schemas for L1/L3/L4).
2. On first data upload, webapp auto-profiles the file via the domain-agnostic `profile_data` op. Profiler is **format-aware, not domain-aware** — it extracts whatever structure the format exposes (shape, dtypes, null counts, value ranges, summary stats, unique-value counts for categoricals, inferred datetime columns, file-level metadata for known containers like `.h5`/`.parquet`/`.nc`). It does not guess what the data *means*. Profile rows are written to `knowledge.sqlite::data_profile_fields` with `confirmed_by_user=false`.
3. Webapp shows the profile to the user in a side panel. User can confirm, correct, or annotate fields with semantic meaning (e.g. "column `t` is time in seconds", "these rows are customers", "this file is sensor output at 1 kHz"). User annotations are what give the data domain context — IRIS never invents it.
4. Confirmed annotations are committed to `data_profile_fields` with `confirmed_by_user=true`.
5. IRIS's first turn is a **short greeting only**. No interview. No "tell me about your goals." Waits for the user to speak.

**Rationale:** The user doesn't know what they want until they poke at the data. Forcing an interview creates friction. But IRIS still starts informed — the auto-profile means turn 1 already has grounded facts.

---

## 2. Return greeting (existing project)

When a user opens an existing project, IRIS's first message is:

- **Status line:** one sentence summarizing last session's `focus` from the most recent L2 digest.
- **Next Steps:** bullets from the most recent digest's `next_steps[]`.
- **No trailing question.** IRIS hands the floor to the user.

Example (domain-neutral):
> Picking up — last session you were comparing two candidate models on the held-out split.
>
> **Next Steps:**
> - Re-run the comparison with the revised feature set
> - Plot residuals by segment
> - Draft the summary section of the report

If the previous session did not complete its curation ritual (hard-close), IRIS prepends: *"Your last session didn't wrap up — want to polish its digest now?"*

---

## 3. Memory architecture (5 layers, mixed storage)

Five layers with distinct load-triggers, distinct write-gates, and **storage picked per access pattern** — not "everything is markdown because markdown is inspectable." Markdown is kept only where humans actually read it; everything queried by IRIS moves to SQLite.

### 3.1 L0 — Conversation (append-only JSONL)
- **File:** `conversations/<session_id>.jsonl`.
- **Contents:** raw turns (role, text, tool calls, tool results, timestamps).
- **Load:** never auto. Tools fetch by id or slice.
- **Write:** automatic, every turn, no approval. **This is the one memory that must never be lost** — it's the substrate for everything else.

### 3.2 L1 — Event ledger (SQLite)
- **File:** `ledger.sqlite`. Tables: `ops_runs`, `plots_generated`, `references_added`, `cache_entries`.
- **Contents:** structured facts about what happened — op name, input content hashes, params hash, output path, bytes, runtime, session_id, timestamp.
- **Load:** never auto. `recall()` and `read_ledger()` only.
- **Write:** automatic, no approval. This is *derived* data, not interpretation.

### 3.3 L2 — Session digest (JSON per session)
- **File:** `digests/<session_id>.json`. Schema: `{focus, decisions[], surprises[], open_questions[], next_steps[]}` — each entry has `id`, `text`, `tags[]`, `refs[]` to L0 turns and L1 ledger rows.
- **Load:** last-session digest pulled into the pinned slice. Others retrieved via `recall()`.
- **Write:** auto-drafted continuously as the session progresses (updated on each curation-eligible event); user reviews/edits at session close. Hard-close preserves the auto-draft as `digests/<session_id>.draft.json` — ritual only polishes it.

### 3.4 L3 — Curated knowledge (SQLite)
- **File:** `knowledge.sqlite`. Tables:
  - `goals(id, text, status, opened_session, closed_session, last_referenced_at)` — status ∈ {active, done, abandoned}
  - `decisions(id, text, rationale, status, supersedes, created_session, last_referenced_at, tags)`
  - `learned_facts(id, key, value, source_session, confidence, superseded_by)`
  - `declined_suggestions(id, text, declined_session, last_re_offered_at)`
  - `data_profile_fields(id, field_path, annotation, confirmed_by_user, session)`
- **Load:** pinned slice pulls a *derived* top-N per table (see §3.6).
- **Write:** user-confirmed, proposed via `propose_*` tools, flushed at session-end via `commit_session_writes()`.

### 3.5 L4 — Semantic index
- **File:** `memory.vec` (sqlite-vec extension; fallback: parquet + hnswlib).
- **Contents:** embeddings of L2 digest entries, L3 decisions, L3 learned_facts, plus `claude_references/` reference stubs.
- **Load:** never auto. Single retrieval primitive `recall(query, k=5, filters={})` does hybrid BM25 + vector + recency-boost, returns chunks with citation metadata.
- **Write:** automatic on every L2/L3 commit.

### 3.6 Pinned slice — a *derivation*, not a file

On each turn, `buildSystemPrompt()` assembles a pinned slice under a **token budget** (default 2,000 tokens). Composition, in priority order:

1. Active goals (status='active', ORDER BY last_referenced_at DESC, LIMIT `goals_active_max`=5).
2. Last session's digest `focus` + top 2 `next_steps`.
3. Top-K decisions where status='active', scored by recency × reference_count.
4. Top-K learned_facts by recency × reference_count.
5. Data profile annotations (confirmed only, never raw stats).
6. User-scoped preferences (from `~/.iris/user_memory/preferences.yaml`, if `use_user_memory: true`).

Tokenize each candidate, fill until budget, degrade by dropping lowest-priority slot first. No character-slicing.

A `.iris/pinned_slice.cache.md` is written after assembly for fast reload and human inspection — it is a *cache*, never the source of truth.

### 3.7 Human-readable views (regenerated, not authoritative)

For users who want to *read* memory:
- `views/history.md` — regenerated view of L3 tables grouped by section. Never edited by hand.
- `views/analysis_log.md` — regenerated concatenation of L2 digests in reverse-chronological order.
- Regeneration is cheap; sources of truth are the SQLite files.

### Context loading summary

| Layer | Storage | Pinned? | Write-gate |
|---|---|---|---|
| L0 Conversation | JSONL | no (tool: `read_conversation`) | automatic |
| L1 Event ledger | SQLite | no (tool: `recall`, `read_ledger`) | automatic |
| L2 Session digests | JSON | last session in slice | auto-draft, user-polish |
| L3 Curated knowledge | SQLite | derived slice | user-confirmed |
| L4 Semantic index | sqlite-vec | no (tool: `recall`) | automatic |

---

## 4. Per-project configuration (`claude_config.yaml`)

Autonomy + pushback dials + memory dials:

```yaml
autonomy: medium   # low | medium | high
pushback:
  statistical: balanced    # light | balanced | rigorous
  methodological: balanced
  interpretive: light

memory:
  pin_budget_tokens: 2000          # hard cap on pinned slice size
  goals_active_max: 5              # hard cap on active goals
  digest_retention_days: 90        # rollup sessions older than this
  recall_k_default: 5
  recall_recency_halflife_days: 30 # time-decay for scoring
  use_user_memory: false           # opt-in to ~/.iris/user_memory/
```

### 4.1 Autonomy presets

| Level | What runs freely | What gates |
|---|---|---|
| **low** | Reads only (memory, history, log, cache lookups). | Everything else — every op, every plot, every L3 write. |
| **medium** | Reads + cheap profiling + cache-hit retrieval. | New op runs, new plots, new ops, all L3 writes. |
| **high** | Reads + profiling + any op that's already run in this project (re-execution). | New ops, novel analyses, L3 writes. |

L0 and L1 writes are **never** gated — they are automatic under every autonomy level.

Autonomy never grants "run without approval for new analyses." The ceiling is "re-run familiar work." Novel work is always proposed.

### 4.2 Pushback domains

- **statistical:** assumption violations, sample-size concerns, multiple comparisons, effect sizes, confidence intervals, test selection.
- **methodological:** pipeline ordering, parameter choices, transform/normalization choices, train/test leakage, scope of aggregation.
- **interpretive:** causal vs correlational claims, overgeneralization from the sample, domain-plausibility of results.

Levels:
- **light:** IRIS notes concerns in a single sentence, implements anyway.
- **balanced:** IRIS flags concerns, proposes alternatives, asks user to choose before proceeding.
- **rigorous:** IRIS refuses to run until user acknowledges or overrides in writing.

### 4.3 Lifecycle defaults

Goals, decisions, and learned_facts carry `status` (active / done / superseded / abandoned) and `last_referenced_at`. Only status='active' rows enter the pinned slice. Sessions older than `digest_retention_days` are rolled up into monthly summaries; per-session digests remain queryable via `get(id)` but drop out of the hot vector index. See §14.

---

## 5. Clarifying-question policy

IRIS asks before acting when the request is ambiguous on any of:

1. **Analytical choice** — which metric, method, model, or null hypothesis.
2. **Scope** — which rows, which columns, which time window, which segments, which subset.
3. **Parameters** — thresholds, bin sizes, window lengths, confidence levels, hyperparameters.
4. **Output format** — plot vs table vs summary; file format; aggregated vs per-unit/per-group.

If *all four* are unambiguous, IRIS proposes the plan (see §6) and waits for confirmation. If any is ambiguous, IRIS asks one round of focused questions (max 3, structured), then proposes.

**IRIS does not ask "what's your goal?" at the top of a session.** Goals live in L3 and evolve organically through conversation.

**Turn-1 carve-out:** On turn 1 of any session (new or returning), IRIS does not ask clarifying questions. It greets and waits. Clarifying questions apply from turn 2 onward, when the user has posted an actual analysis intent. This resolves the tension with §1's "no interview" rule — §1 governs turn 1 only, §5 governs every turn thereafter.

---

## 6. Propose → approve → execute (the core loop)

Every non-trivial turn where IRIS is about to run work:

1. **Propose:** IRIS writes a plan — what op(s), what inputs, what params, what outputs, expected runtime if long. Plan is inline in chat, not a separate file.
2. **Wait:** IRIS stops and waits for user reply.
3. **Execute:** on approval, IRIS runs via the existing DSL (`iris run ...`). Streams progress. L1 ledger entries are written automatically.
4. **Report:** summarizes what happened, what's in the output, any surprises. Calls out whether a cached result was reused (from `ledger.sqlite::cache_entries`).
5. **Queue L3 proposals:** IRIS drafts candidate proposals (decisions, facts, declined-suggestions) via `propose_*` tools — these enter a pending queue in the L2 draft digest. L0 conversation and L1 ledger have already been written automatically.

No L3 writes are committed mid-session without approval. L0/L1 writes are continuous.

---

## 7. Curation ritual (session end)

Triggered when the user closes the project, says "wrap up", or the webapp detects session end. **L0 conversation and L1 event ledger have been writing continuously throughout the session — nothing below concerns whether those persist.** This ritual only curates.

IRIS presents:

1. **Pending L3 proposals** — queued via `propose_*` in §6, grouped by table (decisions, goals, facts, declined). User edits/approves/rejects per row.
2. **Draft L2 digest** — the auto-drafted `digests/<session_id>.draft.json` is shown as an editable form: focus, decisions, surprises, open_questions, next_steps. User edits and confirms.
3. **Data profile annotations** — any new annotations discussed in-session are shown for confirmation.

On approval, `commit_session_writes()` flushes all pending proposals to L3, promotes the draft digest to `digests/<session_id>.json`, and fires L4 embedding updates atomically.

If the user skips the ritual (hard close), the auto-drafted L2 digest is preserved as `digests/<session_id>.draft.json`. On next session open, IRIS re-offers the curation step ("your last session didn't wrap up — want to polish its digest now?"). Raw memory (L0/L1) is never lost under any close path.

---

## 8. Analysis recommendations

IRIS proposes new analyses only when **at least one** of the following is true:

1. User explicitly asks "what should we try next?"
2. A recently-run op produced a result with a clear, bounded follow-up (e.g., "the summary shows 3 segments with much higher variance — want to inspect them?"). One follow-up max, not a chain.
3. An Open Question from a previous L2 digest can be directly addressed by an existing op chain, and the user has revisited the project after >1 session gap.

IRIS does **not**:
- Volunteer recommendations at turn 1 of a new session.
- Chain multiple speculative suggestions.
- Propose analyses the user has already explicitly declined (checked via `declined_suggestions` table; re-offer cooldown respected).

---

## 9. Plot generation

- Plots are ops like any other — subject to §6 propose→approve→execute.
- All plots are cached under `output/plots/` with content-addressed names; the manifest lives in `ledger.sqlite::cache_entries` keyed by `(op, input_content_hashes, params_hash)`.
- When IRIS proposes a plot, it checks the ledger first; if a matching cache entry exists, it surfaces the cached path instead of regenerating.
- IRIS never uses interactive backends (`plt.show()` equivalents). Always file output.
- Plot proposals include: chart type, x/y/color mappings, data scope, output format.

---

## 10. New operation creation

**Trigger:** IRIS detects that the user's intent cannot be expressed by composing existing ops (the core registry + any project-custom ops). Gap-based only — never repetition-based, never speculative. The core op set is intentionally domain-agnostic in spirit; domain-specific operations belong in project-local `custom_ops/` unless the user explicitly promotes them.

**Single-flow with internal checkpoint** (replaces the original two-step `/iris-op-propose` → `/iris-op-implement`):

1. IRIS announces: "I don't think existing ops can express this. Here's a proposed new op: [name, signature, math, inputs, outputs, touch points]."
2. **Checkpoint 1:** user approves or redirects the design.
3. On approval, IRIS writes code across the required touch points (engine, parser, factory, tests, docs, config).
4. **Checkpoint 2 (auto):** IRIS runs the test suite (`uv run pytest -x -q`). If tests pass, it reports success; if not, it reports failure and waits.
5. User approves the merge (op becomes available project-wide or project-local based on a flag).

New ops default to **project-local** (`projects/<name>/custom_ops/`) unless the user explicitly promotes them to core.

---

## 11. References and citations

- When IRIS makes a non-obvious factual or methodological claim, it cites. Citation lives in `claude_references/` as a reference stub (paper, doc, blog, textbook section, standard — whatever fits the claim).
- Research fetches are delegated to the existing `iris-researcher` subagent. IRIS does not web-search inline.
- Every reference IRIS adds is logged as a row in `ledger.sqlite::references_added` and embedded into L4 for future `recall()` hits.
- When quoting memory, IRIS cites via `recall()` results: *"Per decision #42 (session 2026-03-14): 'we chose the robust estimator because…'"* The id + session come from the `recall()` hit's citation metadata.

---

## 12. Files to create or modify (build blueprint)

### New files
- `projects/TEMPLATE/ledger.sqlite` (schema-initialized, empty) + schema migration script
- `projects/TEMPLATE/knowledge.sqlite` (schema-initialized, empty) + schema migration script
- `projects/TEMPLATE/memory.vec` (empty sqlite-vec DB)
- `projects/TEMPLATE/conversations/.gitkeep`
- `projects/TEMPLATE/digests/.gitkeep`
- `projects/TEMPLATE/views/.gitkeep`
- `projects/TEMPLATE/claude_config.yaml` — add `memory:` block from §4
- `~/.iris/user_memory/preferences.yaml` (optional, created on opt-in)
- `docs/iris-behavior.md` — user-facing version of this plan
- `docs/iris-memory.md` — memory architecture reference

### Files dropped from the project contract (no longer source-of-truth)
- `memory.yaml` — replaced by derived pinned slice + L3 tables
- `claude_history.md` — replaced by L3 `knowledge.sqlite` + regenerated view at `views/history.md`
- `cache_manifest.yaml` — replaced by `ledger.sqlite::cache_entries`

Existing `report.md` stays as-is (user-authored living writeup).

### Modified files
- [.claude/agents/iris.md](.claude/agents/iris.md) — rewrite around `recall()` as the retrieval primitive; drop references to grepping markdown; reflect the curation ritual and turn-1 carve-out.
- [iris-app/server/agent-bridge.ts](iris-app/server/agent-bridge.ts) — `buildSystemPrompt()` rewritten to call a token-budgeted slice assembler. Current 3,200-char string-slice at [L89-L97](iris-app/server/agent-bridge.ts#L89-L97) removed.
- [iris-app/server/routes/projects.ts](iris-app/server/routes/projects.ts) — endpoints: `POST /recall`, `POST /get`, `POST /propose_*`, `POST /commit_session_writes`, `GET /draft_digest`; upload handler calls `profile_data` op and writes annotations to L3.
- `iris-app/src/renderer/` — UI for: data profile confirmation on upload, curation ritual (with draft digest editor), autonomy/pushback config panel, **memory inspector** (browse L3 tables, edit status, supersede decisions, archive goals).
- `src/iris/projects/` — new modules:
  - `ledger.py` — SQLite writer/reader for L1
  - `knowledge.py` — SQLite writer/reader for L3 (with status/supersede semantics)
  - `digest.py` — L2 auto-draft and finalization
  - `slice_builder.py` — token-budgeted pinned slice assembly
  - `recall.py` — hybrid BM25+vector+recency retrieval
  - `embeddings.py` — embedding service (local sentence-transformer by default, optional Voyage/Anthropic API)
  - `archive.py` — monthly rollup of old digests
  - `views.py` — regenerate markdown views from SQLite
- [src/iris/engine/factory.py](src/iris/engine/factory.py) — add domain-agnostic `profile_data` op (handles csv/parquet/h5/json/netcdf/numpy; dispatches on file type, not domain). Emits structured rows into `knowledge.sqlite::data_profile_fields`.
- `.claude/commands/` — collapse `iris-op-propose` + `iris-op-implement` into a single command with an internal checkpoint.

### Tools exposed to IRIS (Claude Code SDK tool layer)

**Retrieval:**
- `recall(query: str, k: int = 5, filters: dict = {}) -> list[hit]` — **primary retrieval primitive**. Hybrid BM25+vector, recency-boosted. Returns `[{id, source, session, text, score, citation}]`.
- `get(id: str) -> entry` — direct fetch by id from any L2/L3 row (for citation resolution).
- `read_conversation(session_id: str, turn_range: str | None) -> list[turn]` — L0 access.
- `read_ledger(table: str, filters: dict) -> list[row]` — L1 structured query.

**Proposals (all return a `pending_id`, flushed at session-end):**
- `propose_decision(text, rationale, supersedes, tags) -> pending_id`
- `propose_goal(text) -> pending_id`
- `propose_fact(key, value, confidence) -> pending_id`
- `propose_declined(text) -> pending_id`
- `propose_profile_annotation(field_path, annotation) -> pending_id`
- `propose_digest_edit(session_id, patch) -> pending_id`

**Commit:**
- `commit_session_writes() -> report` — flushes all pending_ids to L3, promotes draft digest to finalized L2, fires L4 embedding updates, atomically.

---

## 13. Verification

Build is complete when the following walkthroughs succeed end-to-end. Run them against at least **two different data types** (e.g., a tabular CSV of business/survey data AND a time-series file) to confirm IRIS is not subtly domain-coupled.

1. **New project walkthrough:**
   - Create project, upload a CSV and a second file in a different format (parquet, h5, json, whatever).
   - Confirm auto-profile appears in the UI with editable fields and no domain assumptions baked in.
   - Confirm `knowledge.sqlite::data_profile_fields` reflects the confirmed annotations.
   - Open a chat; IRIS sends a short greeting, no interview.

2. **Analysis walkthrough:**
   - Ask an ambiguous question (e.g. "look at the outliers"). IRIS asks clarifying questions from §5's four classes.
   - Ask a well-specified question. IRIS proposes, waits, runs on approval, reports.
   - Check that an L1 `ops_runs` row was written automatically and an L3 decision proposal was queued (not yet committed).

3. **Return walkthrough:**
   - Close project, reopen. IRIS greets with status + Next Steps sourced from the most recent L2 digest, no trailing question.
   - Ask a recall question ("what did we decide about the outlier threshold last month?") — IRIS uses `recall()` and quotes the decision row with its citation.

4. **Autonomy walkthrough:**
   - Set autonomy to `low`. Ask for a re-run of a cached op. IRIS still proposes.
   - Set autonomy to `high`. Ask for same re-run. IRIS runs without approval (cache hit, familiar op). L1 entry written automatically.
   - Ask for a novel analysis at `high`. IRIS still proposes — autonomy doesn't gate novelty.

5. **Pushback walkthrough:**
   - Set `statistical: rigorous`. Ask for a parametric test on data that violates its assumptions. IRIS refuses until acknowledged.
   - Set `statistical: light`. Same request. IRIS flags concern in one sentence, implements.

6. **New op walkthrough:**
   - Ask for an analysis no existing op can express. IRIS proposes a new op design.
   - Approve design. IRIS writes code, tests pass, op is registered project-local.

7. **Curation ritual walkthrough:**
   - Say "wrap up". IRIS presents pending L3 proposals, draft digest editor, and profile annotations. User edits and confirms. SQLite rows and `digests/<id>.json` match approved content; L4 embeddings updated.
   - Repeat but hard-close mid-session. Confirm: L0 JSONL and L1 ledger entries present; `digests/<id>.draft.json` present; no L3 rows written. Reopen the project — IRIS re-offers the curation step.

8. **Scale simulation** (`tests/memory_scale/`):
   - Generate 200 synthetic sessions with varied topics and op mixes.
   - Assert: pinned slice ≤ `pin_budget_tokens` on every turn; `recall()` returns the planted decision on paraphrased queries with ≥ 90% success; `buildSystemPrompt()` p95 latency < 150 ms.

9. **Hard-close resilience:**
   - Kill the webapp mid-turn (SIGKILL).
   - Reopen. Confirm L0 JSONL and L1 ledger intact. Confirm next session re-offers curation for the unclosed session.

10. **Cross-project isolation:**
    - Two projects seeded with distinct L3 rows.
    - Assert `recall()` in project B never returns project A rows.
    - Assert `use_user_memory: false` prevents any user-memory leak into the pinned slice.

Test suite: `uv run pytest -x -q` must pass. Lint: `uv run ruff check --fix src tests && uv run ruff format src tests` clean.

---

## 14. Memory lifecycle

### 14.1 Status fields
Every L3 row (goals, decisions, learned_facts) has:
- `status ∈ {active, done, superseded, abandoned}`
- `supersedes` (nullable row id)
- `created_session`, `closed_session`
- `last_referenced_at` (bumped by `recall()` hits and by pinned-slice inclusion)

### 14.2 Supersession
A new decision can declare `supersedes: <old_id>`. The old row stays queryable (audit trail) but is invisible to the pinned slice. `recall()` returns both if relevant, with a `superseded_by` field so IRIS can quote the history accurately.

### 14.3 Recency weighting
Retrieval score: `0.6 * similarity + 0.3 * recency_decay(last_referenced_at, halflife=recall_recency_halflife_days) + 0.1 * log(1 + reference_count)`.

### 14.4 Archive rollup
Nightly (or on-open if idle >24h) job: for any session older than `digest_retention_days` with no `recall()` hits in the same window, its L2 digest is compressed into `monthly_rollups/<YYYY-MM>.json`. The per-session digest remains on disk for direct `get(id)` but drops from the hot vector index.

### 14.5 Memory inspector UI
A dedicated tab in the webapp showing:
- Active goals (with "mark done", "abandon", "bump priority")
- Decisions (with "supersede", "view rationale", "show citations")
- Learned facts (with "edit", "delete")
- Declined suggestions (with "un-decline")
- Session digests by month (with "regenerate view", "archive now")

Users never edit SQLite directly; they use this UI. But the files remain inspectable with any SQLite viewer.
