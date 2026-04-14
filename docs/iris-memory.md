# IRIS — Memory Architecture

Five memory layers with distinct load-triggers, distinct write-gates, and storage picked per access pattern. See [`iris-behavior.md`](iris-behavior.md) for the behavior rules built on top.

## The five layers

| Layer | What it holds | Storage | Pinned? | Write gate |
|---|---|---|---|---|
| **L0 Conversation** | Raw turns (role, text, tool calls, tool results, timestamps) | JSONL — one file per session | no — tool fetch by id/slice | automatic |
| **L1 Event ledger** | Structured facts: op runs, plots, references added, cache entries | `ledger.sqlite` | no — tool: `recall`, `read_ledger` | automatic |
| **L2 Session digest** | Focus, decisions, surprises, open questions, next steps | `digests/<session_id>.json` | last one in slice | auto-draft → user-polish |
| **L3 Curated knowledge** | Goals, decisions, learned facts, declined suggestions, profile annotations | `knowledge.sqlite` | derived slice | user-confirmed via `propose` → `commit` |
| **L4 Semantic index** | Embeddings of L2/L3 rows and reference stubs | `memory.vec` (sqlite-vec, planned) | no — tool: `recall` | automatic on L2/L3 commit |

**Rule of thumb:** whatever IRIS needs to *query* lives in SQLite; whatever humans need to *read* gets a regenerated markdown view; nothing is both.

## The pinned slice

The "pinned slice" is a **derivation**, not a file. Each turn, `buildSystemPrompt()` assembles a fresh slice under a token budget (default 2000 tokens), composed in priority order:

1. Active goals (cap: `goals_active_max`)
2. Last session's digest `focus` + top-2 `next_steps`
3. Top decisions (status='active', by recency × reference_count)
4. Top learned facts (same scoring)
5. Confirmed data profile annotations (never raw stats)
6. User preferences (if `use_user_memory: true`)

Over-budget entries are skipped whole — never truncated mid-line. A cache copy is written to `.iris/pinned_slice.cache.md` for fast reload and human inspection.

## The retrieval primitive: `recall()`

All non-pinned retrieval goes through one function:

```python
recall(query: str, k: int = 5, filters: dict = {}) -> list[Hit]
```

Hybrid scoring (§14.3):

```
score = 0.6 * similarity + 0.3 * recency_decay + 0.1 * log(1 + ref_count)
```

- `similarity`: vector cosine if the embedding provider is configured, else normalized BM25
- `recency_decay`: `0.5 ** (age_days / halflife_days)`, halflife from project config
- Corpus: L3 decisions, L3 learned_facts, L2 digest entries, `claude_references/`

Hits include citation metadata (e.g. `decision#42` or `digest[s1].next_steps#abc`). Resolve back to the full row with `get(source, id)`.

## Lifecycle

Every L3 row has:
- `status ∈ {active, done, superseded, abandoned}`
- `supersedes` (nullable fk)
- `created_session`, `closed_session`
- `last_referenced_at` (bumped by `recall()` hits and pinned-slice inclusion)

A new decision with `supersedes: <old_id>` automatically flips the old row to `status='superseded'`. The old row remains queryable (audit trail) but is invisible to the pinned slice.

## Proposal flow

L3 writes are gated. During a session, IRIS stages proposals:

```python
propose_decision(text, rationale=None, supersedes=None, tags=None) -> pending_id
propose_goal(text) -> pending_id
propose_fact(key, value, confidence=None) -> pending_id
propose_declined(text) -> pending_id
propose_profile_annotation(field_path, annotation) -> pending_id
propose_digest_edit(session_id, patch) -> dict  # applies to draft
```

Pending rows live in `knowledge.sqlite::pending_writes`. At session end, the curation ritual flushes them atomically:

```python
commit_session_writes(session_id, approve_ids=None) -> report
```

`approve_ids=None` means approve all; passing a list cherry-picks. The commit is a single transaction; failure rolls back the whole batch.

## Archive / rollup

A nightly (or on-open-if-idle>24h) job rolls up finalized digests older than `digest_retention_days`:

- Digest content is compacted (focus + decisions + next_steps) and merged into `digests/monthly_rollups/<YYYY-MM>.json`
- The per-session file moves to `digests/archive/`
- It remains queryable via `get()` but drops from the hot vector index

## Regenerated views

Human-readable dumps, rebuilt from SQLite on demand. Never edit by hand.

- `views/history.md` — all L3 tables grouped by section, including superseded rows for audit
- `views/analysis_log.md` — L2 digests in reverse-chrono order

Regeneration is cheap; run via `POST /api/memory/regenerate_views` after any L3 commit (the curation ritual does this automatically).

## Configuration (`claude_config.yaml`)

```yaml
memory:
  pin_budget_tokens: 2000
  goals_active_max: 5
  digest_retention_days: 90
  recall_k_default: 5
  recall_recency_halflife_days: 30
  use_user_memory: false
```

## Embedding providers

`embeddings.py` ships with two providers, pluggable via env var `IRIS_EMBED_PROVIDER`:

- `disabled` (default) — returns `None` for every vector. `recall()` falls back to BM25 + recency. Zero extra deps.
- `sentence-transformers` — local `all-MiniLM-L6-v2`. Requires `uv add sentence-transformers`. Vectors are L2-normalized; cosine = dot product.

Additional providers (Voyage, Anthropic API) can be added by subclassing `EmbeddingProvider`.

## See also

- `IRIS_BEHAVIOR_PLAN.md` — full design rationale
- [`iris-behavior.md`](iris-behavior.md) — behavioral contract
- `src/iris/projects/` — module-level reference (ledger, knowledge, digest, slice_builder, recall, embeddings, archive, views, conversation, tools, profile)
