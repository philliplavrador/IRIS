# IRIS Memory System Design: Definitive Reference

## Document Purpose and How to Use This

This document is the single authoritative reference for designing, implementing, and evolving the project-scoped memory management system in IRIS, a local AI-powered data analysis web application. It synthesizes findings from three independent research reports, a cross-report comparison analysis, and primary source literature into one durable specification.

**How this document is structured:**

- **Part 1 (Sections 1-3)** establishes the problem space, constraints, and design principles. Read this to understand *why* decisions were made.
- **Part 2 (Sections 4-7)** defines the architecture: memory layers, storage model, schemas, and filesystem layout. Read this to understand *what* to build.
- **Part 3 (Sections 8-11)** specifies runtime behavior: retrieval strategy, context assembly, lifecycle management, and pathology prevention. Read this to understand *how* the system behaves.
- **Part 4 (Sections 12-14)** covers the skill library, scaling considerations, and a phased implementation roadmap. Read this to understand *when* to build what.
- **Part 5 (Section 15)** provides the bibliography and source assessment.

**For future conversations referencing this document:** when making implementation decisions, cite the specific section number. The section numbering is stable and designed for long-term reference.

---

## Part 1: Problem Space, Constraints, and Principles

---

## 1. What IRIS's Memory System Must Accomplish

IRIS is not a general-purpose chatbot. It is a persistent, project-scoped research collaborator where users create projects, upload datasets, and work with Claude to perform analyses, generate plots, write reports, and build slide decks. The memory system's job is **decision support and continuity**, not conversational convenience. Specifically, it must answer questions like:

- What did we learn so far in this project?
- What is still uncertain or unresolved?
- What have we already tried, and what failed?
- What should we try next?
- How exactly did we produce this plot/report/finding?
- What assumptions are we relying on?

This framing, consistent across all source reports, means the memory system is the core differentiator between "a Claude wrapper with tools" and "a genuine research collaborator." Every design decision flows from this.

### 1.1 The Four Governing Constraints

Four constraints dominate the design space. Every architectural choice must satisfy all four simultaneously.

**Constraint 1: Context windows are finite and fragile.**

Long-context models do not reliably use all information in very long prompts. The "Lost in the Middle" paper (Liu et al., 2023) demonstrates that performance degrades when relevant information is buried mid-context. This makes "stuff the whole project history into the prompt" an unstable strategy as projects grow. IRIS must externalize most of its memory and retrieve selectively.

**Constraint 2: Tool-heavy workflows create token bloat.**

Data analysis tools return large tables, logs, plots, and intermediate outputs. These pile up in context and consume tokens long after they are useful. Anthropic explicitly recommends tool-result clearing (dropping old, re-fetchable tool outputs while keeping the record that the call happened) as the "lightest touch" compaction strategy. This is the single most common practical problem for a data analysis assistant and must be addressed from V1.

**Constraint 3: Reproducibility and trust require provenance.**

IRIS supports reproducible research workflows. Every artifact (plot, report, slide deck, derived dataset) must be traceable to the exact dataset version, transformation, parameters, code, and model configuration that produced it. The W3C PROV-DM standard provides the vocabulary: Entities (data), Activities (transformations/runs), and Agents (user + IRIS + specific LLM model). Without provenance, memory is just unverifiable assertion, which is the same problem as LLM hallucination but more insidious because it masquerades as the system's own learned knowledge.

**Constraint 4: Local-first requirements amplify everything else.**

IRIS runs entirely on the user's machine. All data, memories, conversation history, and generated code stay local. The only network calls are to the Claude API for inference. Ink & Switch's "Local-first software" essay frames local-first as user control + long-term preservation + privacy, with collaboration as an extension rather than a prerequisite. This means: no cloud databases, no external embedding APIs in the default configuration, no telemetry, and the storage format must be portable, inspectable, and durable.

### 1.2 What "Memory" Means for IRIS (Not Just Chat History)

Memory in IRIS encompasses six distinct categories of information, each with different write patterns, retrieval patterns, and lifecycle needs:

1. **Project memory**: Goals, hypotheses, working definitions, constraints, the evolving research plan, key conclusions, and decision history.
2. **Dataset memory**: Schema/column semantics, known data quality issues, transformations applied, derived versions, and critical caveats.
3. **Session memory**: Conversation transcripts, tool calls, intermediate results, and what happened in each work session.
4. **Artifact memory**: Every plot, report, slide deck, code file, and cached intermediate, linked to provenance.
5. **User preference memory**: Style, plotting defaults, reporting tone, statistical thresholds, and workflow preferences (typically cross-project).
6. **Tool/skill memory**: The catalog of hardcoded analysis skills plus any dynamically generated project-specific operations, with versioning and validation metadata.

These six categories must be stored and managed differently. Treating them as "one database of everything" is a documented failure mode.

---

## 2. Foundational Research and External Validation

This section summarizes the primary sources that collectively support the architecture. Understanding these prevents future conversations from relitigating settled questions.

### 2.1 Memory Hierarchies and Virtual Context (MemGPT/Letta)

MemGPT (Packer et al., 2023, arXiv:2310.08560) frames LLM memory as an operating-system-level problem: a small "main context" (analogous to RAM) with external storage (analogous to disk), and a paging mechanism to move relevant information in and out. It distinguishes three tiers:

- **Core memory blocks**: Always in context, agent-editable via tool calls like `core_memory_append` and `core_memory_replace`.
- **Recall memory**: A searchable database of conversation history.
- **Archival memory**: A vector-database-backed long-term store.

Letta (the production system built on MemGPT) persists all state in PostgreSQL with pgvector for production or SQLite for development.

**IRIS implication**: The project workspace is the external memory. IRIS should behave like a virtual-memory manager: retrieve what is relevant now, avoid dragging everything forward. The three-tier model (always-on + searchable history + long-term store) maps directly to IRIS's needs.

**Key tradeoff noted**: MemGPT's self-directed memory (where the LLM decides what to save/retrieve) costs inference tokens for every memory operation and makes memory quality dependent on model judgment. Cognition AI's engineering team found that when approaching context limits, models exhibit "context anxiety," proactively summarizing and losing important details. IRIS should use deterministic rules for most memory management and reserve agent-directed memory for high-value operations.

### 2.2 Episodic Streams, Retrieval Scoring, and Reflection (Generative Agents)

Park et al. (2023, arXiv:2304.03442) introduced the "memory stream" architecture: natural-language records with timestamps, retrieved by combining three weighted factors:

- **Relevance**: Semantic similarity to the current query.
- **Recency**: Exponential decay based on time since last access.
- **Importance**: An LLM-assigned score (1-10) reflecting salience.

Ablation studies showed the triple-weighted combination outperforms any single factor.

The architecture also introduces **reflection memories**: periodically synthesized higher-level conclusions, triggered when accumulated importance exceeds a threshold, stored with links back to supporting memories.

**IRIS implication**: The memory stream becomes an append-only event history of research actions. "Importance" maps to research salience (decisions, anomalies, key results). "Reflection" maps to periodic synthesis: conclusions, open questions, why attempts failed, and next-step plans, with provenance links.

### 2.3 Retrieval Gating and the Danger of Indiscriminate Retrieval (Self-RAG)

Self-RAG (Asai et al., 2023, arXiv:2310.11511) demonstrates that retrieving and injecting a fixed amount of material regardless of necessity or relevance can reduce model versatility and lead to worse responses. Retrieval should be gated (decide whether to retrieve at all) and critiqued (evaluate whether retrieved content is actually relevant).

**IRIS implication**: Not every user message should trigger memory retrieval. The system needs explicit rules for when retrieval is warranted (e.g., the user references prior work, asks about a dataset, or requests a similar analysis) versus when it is not (e.g., a simple follow-up question, a formatting request).

### 2.4 Structured Memory Blocks with Token Budgets (LlamaIndex, LangGraph)

LlamaIndex describes short-term memory as a FIFO message queue that flushes into long-term "memory blocks" (fact extraction, vector blocks), with block priorities that determine what gets truncated when token limits are exceeded.

LangGraph's persistence layer stores checkpoints at each step and supports "time travel" for replay and forking from prior states.

**IRIS implication**: Context must be assembled from explicit blocks with priorities and budgets. Without budgeting, heterogeneous context (project goals + dataset schema + dialogue + code + conclusions) becomes unpredictable and unstable.

### 2.5 Tool-Result Compaction (Anthropic Engineering)

Anthropic's context engineering cookbook explicitly recommends clearing old tool_result blocks while keeping tool_use records as the cheapest context-management primitive (zero inference cost). It also highlights structured note-taking where agents persist notes outside the context window and pull them back later.

**IRIS implication**: Data analysis tools produce large outputs (dataframes, statistical summaries, error logs). These must be externalized immediately after use. The record that a tool was called (and what it returned) is kept in the event log, but the actual output content is dropped from the active prompt and stored as a re-fetchable artifact.

### 2.6 File-Based Memory in Shipping Products

The strongest practice-based confirmation comes from tools that ship today:

- **Claude Code** uses `CLAUDE.md` + `.claude/rules/` + auto-memory (`MEMORY.md` entrypoint, first 200 lines/25KB loaded at startup). This is a concrete "pinned index + lazy details" strategy.
- **Cursor** uses `.cursor/rules/` MDC files. The community-driven "Memory Bank" pattern uses structured Markdown files (`projectbrief.md`, `systemPatterns.md`, `activeContext.md`, `progress.md`), achieving roughly 70% token reduction.
- **Windsurf** stores auto-generated memories locally in `~/.codeium/windsurf/memories/`, scoped to workspaces, and recommends `rules/AGENTS.md` for reliable reuse.
- **GitHub Copilot** uses `.github/copilot-instructions.md` and an Agentic Memory system with citation-backed, auto-expiring memories (28-day default expiry unless validated and renewed).

**IRIS implication**: Durable context should be stored as human-readable files. Startup context should be bounded. Details should be lazy-loaded. This is not theoretical; it is how the most successful AI tools actually work.

### 2.7 Passive Memory Extraction (Mem0)

Mem0 (arXiv:2504.19413) implements passive extraction with intelligent consolidation: a two-phase pipeline (Extraction + Update) automatically identifies salient facts, deduplicates against existing memories, resolves conflicts, and merges related entries. On the LOCOMO benchmark, Mem0 achieves 26% higher accuracy than OpenAI's memory with 91% lower p95 latency and 90% token cost savings.

**IRIS implication**: Memory extraction should be largely passive (the system extracts candidate memories after substantive analysis steps) rather than requiring the user or agent to explicitly save things.

### 2.8 Skill Libraries (Voyager)

Voyager (Wang et al., 2023, arXiv:2305.16291) demonstrated that storing executable code with natural language descriptions and embedding-based retrieval creates a compositional, ever-growing capability library, achieving 3.3x more unique items and 15.3x faster milestone completion than baselines. The skill library also transferred to new environments.

**IRIS implication**: Dynamically generated data analysis operations should be stored as versioned, validated code artifacts with descriptions and retrieval metadata, following the Voyager pattern adapted for data analysis.

### 2.9 Episodic Self-Reflection (Reflexion)

Reflexion (Shinn et al., NeurIPS 2023, arXiv:2303.11366) demonstrated that storing verbal self-reflection as memory adds 8% absolute improvement over episodic-memory-only learning on coding benchmarks. The key insight is that storing *why* something failed, not just *that* it failed, enables the agent to avoid repeating mistakes.

**IRIS implication**: Failed analyses must be stored with LLM-generated reflections on what went wrong and what to try differently. These should be retrieved alongside successful analyses when similar work is attempted.

---

## 3. Design Principles

These principles are non-negotiable across all versions of IRIS. They synthesize the strongest reasoning from all source reports.

### Principle 1: Record Everything, Load Little

Persist full-fidelity artifacts and transcripts, but only load a token-budgeted subset into the model context at any given time. This directly addresses both long-context degradation and tool-result bloat. The event log captures everything; the prompt contains only what is relevant to the current turn.

### Principle 2: Memory Writes Must Be Grounded

Every long-term memory that influences future conclusions (findings, decisions, assumptions, dataset descriptions) must be stored with explicit provenance links: event IDs, dataset version hashes, artifact IDs, session IDs. This is aligned with PROV-DM (entities/activities/agents) and with audit-driven architectures like event sourcing. A memory without provenance is an unsupported claim.

### Principle 3: Memory Reads Must Be Validated

Retrieved memories are necessary but not sufficient for correctness. Empirical evaluations (e.g., Stanford's Legal RAG study) show hallucinations persist and can be substantial even with retrieval. IRIS must surface provenance when presenting remembered information and flag stale, contradicted, or low-confidence memories explicitly.

### Principle 4: Tool Catalogs Must Remain Navigable

Ambiguous or bloated tool sets degrade model performance. Anthropic's tool design guidance emphasizes minimizing overlap and ambiguity. IRIS should retrieve a small relevant tool subset per turn rather than exposing the entire catalog. As the skill library grows, tool routing (retrieve top-k tools by description similarity) becomes essential.

### Principle 5: Raw Records and Curated Memory Are Separate

This distinction is fundamental:

- **Raw records** (immutable): events, messages, tool calls, dataset snapshots, artifacts. Never edited; always appended and addressed by IDs/hashes.
- **Curated memory** (editable but provenance-linked): project briefs, conclusions, dataset cards, open questions, tool documentation. Can evolve, but each update must link back to raw evidence.

This preserves auditability (events as facts) and prevents silent overwrites of knowledge when summaries evolve.

### Principle 6: Simplicity Until Complexity Earns Its Keep

SQLite + FTS5 handles 90% of the memory workload for typical research projects. Vector search, knowledge graphs, reflection cycles, and automatic consolidation should be added only when the simpler approach demonstrably falls short. Every additional memory layer adds retrieval latency, maintenance burden, and failure modes. Start simple. Layer intelligence on top only when the foundation is solid and the need is clear.

### Principle 7: Explicit Uncertainty Over Confident Recall

The system should surface what it does not know as aggressively as what it does. Open questions, failed attempts, caveats, and assumptions are as valuable as confirmed findings. When a memory is stale, say so. When two memories contradict, present both. When confidence is low, say so. Research integrity demands epistemic honesty from tools as much as from researchers.

---

## Part 2: Architecture, Storage, and Schema

---

## 4. The Five Memory Layers

IRIS implements a structured hybrid architecture with five memory layers, each serving a distinct cognitive function. This structure is derived from the CoALA cognitive science taxonomy (working, episodic, semantic, procedural memory) adapted for project-scoped research.

### Layer 1: Project Core Memory (Always in Context)

**Cognitive function**: Working memory. The project's current state.

**What it contains**: A structured Markdown document per project containing: project objectives, dataset descriptions (brief), key findings to date, active hypotheses, open questions, important caveats and assumptions, and user preferences relevant to the project.

**How it behaves**: Always injected into the system prompt. Updated semi-automatically: after significant analyses, IRIS proposes updates that the user can accept, modify, or reject. Never silently overwritten.

**Target size**: 1,500-3,000 tokens. This budget is firm. If the core memory grows beyond this, it needs consolidation, not expansion.

**Implementation**: Stored both as a row in the database (for programmatic access) and as a human-readable `memory/PROJECT.md` file on disk (for inspection and manual editing). Kept in sync bidirectionally.

**Why this layer matters most**: It grounds every interaction in the project's current state. Without it, each session starts from scratch. With it, IRIS can say "last time we found X and left question Y open" from the very first message of a new session.

### Layer 2: Session Memory (Conversation Buffer with Summarization)

**Cognitive function**: Short-term episodic memory. What happened recently.

**What it contains**: The current conversation's messages plus compressed summaries of previous sessions. Session summaries capture: what was asked, what was found, what decisions were made, what remains unresolved.

**How it behaves**: Recent messages stay verbatim in context. Older sessions are summarized via progressive summarization (summarize when a session closes; when older summaries accumulate, summarize the summaries). Previous session summaries are retrieved only when semantically relevant to the current query, not injected by default.

**Target size**: 2,000-4,000 tokens of recent context plus selective retrieval from older sessions.

**Implementation**: Full conversation history stored in SQLite with FTS5 indexing. Session metadata (start time, end time, topic summary) generated at session close.

### Layer 3: Semantic Memory (Findings, Facts, and Knowledge)

**Cognitive function**: Long-term semantic memory. What we know.

**What it contains**: Atomic facts extracted from analyses and conversations. Each entry carries:
- The fact text itself.
- `memory_type`: one of finding, assumption, caveat, open_question, decision, preference, failure_reflection.
- `confidence`: 0.0-1.0.
- `importance_score`: LLM-assigned 1-10.
- `source_analysis_id` and `source_session_id`: foreign keys for provenance.
- `evidence_json`: array of pointers to events, artifacts, and dataset versions.
- `created_at`, `last_validated_at`, `last_accessed_at`, `access_count`.
- `tags`: JSON array for structured filtering.
- `status`: active, superseded, archived, contradicted.

**How it behaves**: Searched by relevance (vector similarity) combined with recency and importance scoring, following the Generative Agents triple-weighted retrieval. Also queryable by structured filters (e.g., "show me all open questions," "what assumptions have we made about dataset X"). The `memory_type` enum enables structured queries without relying on semantic search.

**Implementation**: Stored in SQLite with both FTS5 (for lexical search) and vector embeddings (for semantic search, added in V2 via sqlite-vec or ChromaDB).

### Layer 4: Episodic Memory (Analysis History and Provenance)

**Cognitive function**: Long-term episodic memory. What happened, in full detail.

**What it contains**: Two complementary structures:

1. **Append-only event log**: Every state change in the project: messages sent, tool calls made, datasets imported, transformations run, artifacts created, memories written or updated. Each event has a type, timestamp, payload, and hash. This is the canonical source of truth for "what happened when."

2. **Analysis/runs index (DAG)**: A derived view optimized for lineage queries: what analysis produced what output from what input, using what code and parameters, with what findings. Implements a directed acyclic graph where analyses can branch from earlier analyses.

**Why both**: The event log provides the unified audit trail for everything (including events that are not "analyses," like memory writes or preference changes). The analysis DAG provides the ergonomic provenance exploration interface for research artifacts (dataset A was transformed by operation B to produce dataset C, which was analyzed by operation D to produce plot E). The event log is the source of truth; the DAG is a derived index that can be rebuilt from events.

**How it behaves**: Queried by structured filters (date ranges, operation types, dataset references, success/failure status) more than by semantic similarity. This is the reproducibility backbone.

**Implementation**: Both the event log and the analysis index live in SQLite. The event log is append-only with hash chaining for integrity. The analysis index uses parent-child foreign keys for DAG structure.

### Layer 5: Procedural Memory (Skill/Operation Library)

**Cognitive function**: Procedural memory. How to do things.

**What it contains**: Dynamically generated code operations stored with:
- Executable Python code.
- A natural language description (for human readability and retrieval).
- A JSON parameter schema.
- Optional validation code (for verifying correctness).
- Version history via parent_operation_id chains.
- Usage statistics: use_count, success_rate, last_used_at.

**How it behaves**: Retrieved via hybrid FTS5 + vector search when the user's request matches a previously successful operation. The LLM can reuse operations directly, adapt them with modified parameters, or compose them with other operations.

**Implementation**: Operations stored in SQLite with code artifacts on the filesystem (versioned directories with schema.json, tests, and README). Details in Section 12.

### Layer Summary Table

| Layer | Cognitive Type | Retrieval Pattern | Update Frequency | Always in Context? |
|-------|---------------|-------------------|------------------|--------------------|
| 1. Core Memory | Working | Read every turn | After significant analyses | Yes |
| 2. Session Memory | Short-term episodic | Sequential + recency | Every message | Current session yes; older sessions selectively |
| 3. Semantic Memory | Long-term semantic | Triple-weighted search | After analysis steps | No, retrieved selectively |
| 4. Episodic Memory | Long-term episodic | Structured filters | Every state change | No, retrieved selectively |
| 5. Procedural Memory | Procedural | Task-description similarity | When operations are created/modified | No, retrieved when relevant |

---

## 5. Storage Architecture

### 5.1 The Hybrid Storage Model

IRIS uses three canonical stores, each optimized for its role:

**Store 1: SQLite database (metadata, events, FTS, indices)**

The single source of structured truth. Contains: projects, sessions, messages, events, datasets, dataset_versions, artifacts (metadata only), memory_entries, operations, contradictions, and user_preferences. Uses WAL mode for read-heavy workloads with concurrent write safety. Uses FTS5 virtual tables for fast lexical search over messages, memory entries, and operation descriptions.

Why SQLite: it is local-first by design, requires no server process, produces a single portable file, supports WAL for concurrent reads during writes, has mature FTS5 for full-text search, and has the sqlite-vec extension for vector search. It is the storage backend used by Letta (development mode), Cognee (default stack), and Claude Code (memory storage).

**Store 2: Filesystem artifact store (content-addressed files)**

Stores the "heavy" objects: dataset files (raw + derived), plot images, HTML/PDF reports, slide decks, generated code modules, and caches. Uses content-addressable storage (SHA-256 hash as filename/path), following the Git internals model: immutable content identified by hash key. This ensures deduplication and immutable snapshotting.

Why filesystem: binary artifacts (PNG plots, PDF reports, Parquet files) should not be stored as BLOBs in SQLite. Keeping them as files makes them directly accessible to tools, previewable by the user, and easy to back up or share. The database stores metadata and hash references; the filesystem stores content.

**Store 3: Curated Markdown documents (human-auditable memory)**

The "memory surface" that is always loaded and always inspectable: `PROJECT.md`, `DATASETS/<id>.md`, `DECISIONS.md`, `OPEN_QUESTIONS.md`. These are the files that make IRIS's memory transparent to the user.

Why separate files: this mirrors the pattern proven in Claude Code, Cursor, Windsurf, and Copilot. Human-readable, version-controllable, always loaded at session start, and editable by the user without touching the database.

**Store 4 (V2+): Vector index**

Embeddings for semantic memories, operation descriptions, and artifact summaries. Implemented via sqlite-vec (keeping everything in one file) or ChromaDB with PersistentClient (if richer vector operations are needed). Not required for V1, where FTS5 BM25 ranking provides adequate retrieval for keyword-oriented research queries.

### 5.2 What This Architecture Does NOT Include (And Why)

- **No knowledge graph in V1 or V2.** Knowledge graphs (Neo4j, KuzuDB, GraphRAG) add significant complexity: entity extraction is noisy, ontology design is required, and the engineering overhead is substantial. The PROV-like lineage tracking needed for IRIS is handled by the analysis DAG in SQLite. A lightweight knowledge graph (entity-relationship triples stored in SQLite tables, traversed via recursive CTEs) is a V3 consideration for multi-hop reasoning across many datasets.

- **No cloud storage.** All stores are local. The only network calls are to the Claude API for inference.

- **No separate FTS database.** FTS5 virtual tables live inside the main SQLite database. A separate `fts.sqlite` is unnecessary unless the FTS index grows very large (unlikely for single-project use).

---

## 6. Filesystem Layout

The project directory is self-contained and portable: copy/move the folder to back up, archive, or share a project.

```
~/iris/
├── config.toml                          # Global user preferences
├── projects/
│   └── <project-id>/
│       ├── iris.sqlite                  # SQLite database (WAL mode)
│       ├── memory/
│       │   ├── PROJECT.md               # Project core memory (human-readable)
│       │   ├── DATASETS/
│       │   │   └── <dataset-id>.md      # Dataset cards
│       │   ├── DECISIONS.md             # Decision & conclusion register
│       │   └── OPEN_QUESTIONS.md        # Open questions register
│       ├── datasets/
│       │   ├── raw/
│       │   │   └── <dataset-id>/
│       │   │       └── <sha256>.<ext>   # Original uploaded files
│       │   └── derived/
│       │       └── <dataset-id>/
│       │           └── <sha256>.<ext>   # Transformed/derived versions
│       ├── artifacts/
│       │   └── <sha256>/                # Content-addressed outputs
│       │       └── ...                  # Plots, reports, exports, caches
│       ├── ops/
│       │   └── <op-name>/
│       │       └── v<semver>/
│       │           ├── op.py            # Operation code
│       │           ├── schema.json      # Input/output schema
│       │           ├── tests/           # Validation tests
│       │           └── README.md        # Human-readable description
│       └── indexes/
│           └── embeddings.<format>      # Vector index (V2+)
└── global/
    ├── user_preferences.db              # Cross-project user preferences
    ├── global_operations.db             # Global skill library
    └── embeddings_cache/                # Cached embeddings for common terms
```

**Key separation principles:**
- Immutable "heavy objects" (datasets, artifacts) are separate from mutable curated notes (memory/ markdown) and from executable versioned skills (ops/).
- Each project is a self-contained folder. No cross-project file dependencies.
- The SQLite database is the programmatic interface. The Markdown files are the human interface. Both are kept in sync.

---

## 7. Database Schema

This schema is designed for V1 with clear extension points for V2+. It is inspired by event sourcing (append-only history), PROV-like provenance edges, and content-addressed artifact separation.

### 7.1 Core Tables

```sql
-- ============================================================
-- PROJECTS AND SESSIONS
-- ============================================================

CREATE TABLE projects (
    project_id    TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    created_at    TEXT NOT NULL,       -- ISO 8601
    updated_at    TEXT NOT NULL
);

CREATE TABLE sessions (
    session_id         TEXT PRIMARY KEY,
    project_id         TEXT NOT NULL REFERENCES projects(project_id),
    started_at         TEXT NOT NULL,
    ended_at           TEXT,
    model_provider     TEXT,           -- e.g., "anthropic"
    model_name         TEXT,           -- e.g., "claude-sonnet-4-20250514"
    system_prompt_hash TEXT,           -- SHA-256 of the system prompt used
    summary            TEXT            -- LLM-generated session summary (written at session end)
);

-- ============================================================
-- APPEND-ONLY EVENT LOG (Source of Truth)
-- ============================================================
-- Every state change is recorded here. This enables:
-- - Full audit trail
-- - Replay and reconstruction of state at any point in time
-- - Temporal queries ("what happened between date X and date Y")
-- - Rollback by replaying events up to a checkpoint
--
-- Events are NEVER edited or deleted. They are the facts.

CREATE TABLE events (
    event_id        TEXT PRIMARY KEY,
    project_id      TEXT NOT NULL REFERENCES projects(project_id),
    session_id      TEXT REFERENCES sessions(session_id),
    ts              TEXT NOT NULL,     -- ISO 8601 timestamp
    type            TEXT NOT NULL,     -- message | tool_call | tool_result |
                                      -- dataset_import | transform_run |
                                      -- artifact_created | memory_write |
                                      -- memory_update | memory_delete |
                                      -- operation_created | preference_changed
    payload_json    TEXT NOT NULL,     -- Canonical event payload (varies by type)
    prev_event_hash TEXT,             -- Hash of the previous event (chain integrity)
    event_hash      TEXT NOT NULL      -- SHA-256 of (type + payload + prev_event_hash)
);

CREATE INDEX idx_events_project_ts ON events(project_id, ts);
CREATE INDEX idx_events_type ON events(type);

-- ============================================================
-- CONVERSATION RECORDS
-- ============================================================
-- These CAN be regenerated from the event log, but are stored
-- separately for fast querying and FTS indexing.

CREATE TABLE messages (
    message_id   TEXT PRIMARY KEY,
    session_id   TEXT NOT NULL REFERENCES sessions(session_id),
    event_id     TEXT REFERENCES events(event_id),  -- Link to canonical event
    role         TEXT NOT NULL,       -- user | assistant | tool
    content      TEXT NOT NULL,
    ts           TEXT NOT NULL,
    token_count  INTEGER
);

CREATE VIRTUAL TABLE messages_fts USING fts5(content, content=messages, content_rowid=rowid);

CREATE TABLE tool_calls (
    tool_call_id      TEXT PRIMARY KEY,
    session_id        TEXT NOT NULL REFERENCES sessions(session_id),
    event_id          TEXT REFERENCES events(event_id),
    tool_name         TEXT NOT NULL,
    input_json        TEXT NOT NULL,
    output_artifact_id TEXT,          -- Points to artifacts table if output was stored
    output_summary    TEXT,           -- Brief text summary of the result (for retrieval)
    success           INTEGER NOT NULL, -- 0 or 1
    error_text        TEXT,
    ts                TEXT NOT NULL,
    execution_time_ms INTEGER
);

-- ============================================================
-- DATASETS AND VERSIONS (Lineage-Friendly)
-- ============================================================

CREATE TABLE datasets (
    dataset_id        TEXT PRIMARY KEY,
    project_id        TEXT NOT NULL REFERENCES projects(project_id),
    name              TEXT NOT NULL,
    original_filename TEXT,
    created_at        TEXT NOT NULL
);

CREATE TABLE dataset_versions (
    dataset_version_id              TEXT PRIMARY KEY,
    dataset_id                      TEXT NOT NULL REFERENCES datasets(dataset_id),
    created_at                      TEXT NOT NULL,
    content_hash                    TEXT NOT NULL,   -- SHA-256 of file content
    storage_path                    TEXT NOT NULL,   -- Relative path within project folder
    derived_from_dataset_version_id TEXT,            -- NULL for raw imports
    transform_run_id                TEXT,            -- Links to the analysis/run that produced this
    schema_json                     TEXT,            -- Column names, types, stats
    row_count                       INTEGER,
    description                     TEXT             -- Human-readable notes
);

-- ============================================================
-- ARTIFACTS (Metadata Only; Content on Filesystem)
-- ============================================================

CREATE TABLE artifacts (
    artifact_id    TEXT PRIMARY KEY,
    project_id     TEXT NOT NULL REFERENCES projects(project_id),
    type           TEXT NOT NULL,     -- plot_png | plot_svg | report_html | report_pdf |
                                     -- slide_deck | code_file | cache_object |
                                     -- data_export | notebook
    created_at     TEXT NOT NULL,
    content_hash   TEXT NOT NULL,     -- SHA-256 of file content
    storage_path   TEXT NOT NULL,     -- Relative path within project folder
    metadata_json  TEXT,             -- Type-specific metadata (e.g., plot title, axis labels)
    description    TEXT              -- Brief description for retrieval
);

-- ============================================================
-- ANALYSIS RUNS (DAG Index for Provenance)
-- ============================================================
-- This is a DERIVED VIEW over the event log, optimized for
-- lineage queries. It can be rebuilt from events if needed.

CREATE TABLE runs (
    run_id              TEXT PRIMARY KEY,
    parent_run_id       TEXT,           -- NULL for root analyses; enables branching DAG
    project_id          TEXT NOT NULL REFERENCES projects(project_id),
    session_id          TEXT NOT NULL REFERENCES sessions(session_id),
    event_id            TEXT REFERENCES events(event_id),
    operation_type      TEXT NOT NULL,  -- e.g., "correlation_analysis", "data_cleaning",
                                       -- "plot_generation", "statistical_test"
    operation_id        TEXT,           -- FK to operations table if a stored op was used
    input_data_hash     TEXT,           -- SHA-256 of input dataset(s)
    input_versions_json TEXT,           -- Array of dataset_version_ids used
    output_data_hash    TEXT,           -- SHA-256 of output (if applicable)
    output_artifact_ids TEXT,           -- JSON array of artifact IDs produced
    parameters_json     TEXT,           -- All parameters used
    code_executed       TEXT,           -- The actual code that ran
    llm_prompt_hash     TEXT,           -- Hash of prompt sent to Claude
    llm_model           TEXT,           -- Model identifier
    findings_text       TEXT,           -- LLM-generated summary of findings
    status              TEXT NOT NULL,  -- running | completed | failed
    error_text          TEXT,           -- Error message if failed
    failure_reflection  TEXT,           -- LLM-generated reflection on why it failed
                                       -- and what to try differently
    created_at          TEXT NOT NULL,
    execution_time_ms   INTEGER
);

CREATE INDEX idx_runs_project ON runs(project_id);
CREATE INDEX idx_runs_status ON runs(status);
CREATE INDEX idx_runs_parent ON runs(parent_run_id);

-- ============================================================
-- SEMANTIC MEMORY ENTRIES (Long-Term Knowledge with Grounding)
-- ============================================================

CREATE TABLE memory_entries (
    memory_id          TEXT PRIMARY KEY,
    project_id         TEXT NOT NULL REFERENCES projects(project_id),
    scope              TEXT NOT NULL,   -- project | dataset | user | tool
    dataset_id         TEXT,            -- Non-null when scope = "dataset"
    memory_type        TEXT NOT NULL,   -- finding | assumption | caveat |
                                       -- open_question | decision | preference |
                                       -- failure_reflection | reflection
    text               TEXT NOT NULL,
    importance         REAL DEFAULT 5.0,  -- LLM-assigned 1-10
    confidence         REAL DEFAULT 0.5,  -- 0.0-1.0
    status             TEXT NOT NULL DEFAULT 'active',
                                       -- active | superseded | archived |
                                       -- contradicted | stale
    created_at         TEXT NOT NULL,
    last_validated_at  TEXT,
    last_accessed_at   TEXT,
    access_count       INTEGER DEFAULT 0,
    evidence_json      TEXT,           -- Array of pointers: event_ids, artifact_ids,
                                      -- dataset_version_ids, run_ids
    tags               TEXT,           -- JSON array for structured filtering
    superseded_by      TEXT,           -- FK to the memory that replaced this one
    embedding          BLOB            -- V2+: vector embedding for semantic search
);

CREATE VIRTUAL TABLE memory_entries_fts USING fts5(
    text, tags, content=memory_entries, content_rowid=rowid
);

CREATE INDEX idx_memories_project_type ON memory_entries(project_id, memory_type);
CREATE INDEX idx_memories_status ON memory_entries(status);
CREATE INDEX idx_memories_importance ON memory_entries(importance DESC);

-- ============================================================
-- CONTRADICTION LOG
-- ============================================================
-- When a new finding contradicts an existing memory, both are
-- recorded here with evidence. The user must resolve contradictions.

CREATE TABLE contradictions (
    contradiction_id  TEXT PRIMARY KEY,
    project_id        TEXT NOT NULL REFERENCES projects(project_id),
    memory_id_a       TEXT NOT NULL REFERENCES memory_entries(memory_id),
    memory_id_b       TEXT NOT NULL REFERENCES memory_entries(memory_id),
    evidence_json     TEXT,           -- Evidence supporting each side
    resolved          INTEGER DEFAULT 0,
    resolution_text   TEXT,           -- How it was resolved
    created_at        TEXT NOT NULL,
    resolved_at       TEXT
);

-- ============================================================
-- DYNAMICALLY GENERATED OPERATIONS / SKILLS
-- ============================================================

CREATE TABLE operations (
    op_id               TEXT PRIMARY KEY,
    project_id          TEXT,          -- NULL = global (available across all projects)
    name                TEXT NOT NULL,
    version             TEXT NOT NULL, -- Semantic versioning: "1.0.0", "1.1.0", etc.
    description         TEXT NOT NULL,
    input_schema_json   TEXT NOT NULL,
    output_schema_json  TEXT,
    code_hash           TEXT NOT NULL, -- SHA-256 of the code artifact
    code_artifact_id    TEXT NOT NULL REFERENCES artifacts(artifact_id),
    test_artifact_id    TEXT REFERENCES artifacts(artifact_id),
    parent_op_id        TEXT,          -- Previous version (version chain)
    validation_status   TEXT NOT NULL DEFAULT 'draft',
                                      -- draft | validated | rejected | deprecated
    use_count           INTEGER DEFAULT 0,
    success_rate        REAL,          -- 0.0-1.0, updated after each use
    created_at          TEXT NOT NULL,
    validated_at        TEXT,
    last_used_at        TEXT,
    embedding           BLOB           -- V2+: vector embedding of description
);

CREATE VIRTUAL TABLE operations_fts USING fts5(
    name, description, content=operations, content_rowid=rowid
);

CREATE INDEX idx_ops_project ON operations(project_id);
CREATE INDEX idx_ops_validation ON operations(validation_status);

-- ============================================================
-- OPERATION EXECUTION HISTORY
-- ============================================================

CREATE TABLE operation_executions (
    execution_id    TEXT PRIMARY KEY,
    op_id           TEXT NOT NULL REFERENCES operations(op_id),
    run_id          TEXT REFERENCES runs(run_id),
    input_hash      TEXT,
    output_hash     TEXT,
    success         INTEGER NOT NULL,
    error_text      TEXT,
    execution_time_ms INTEGER,
    ts              TEXT NOT NULL
);

-- ============================================================
-- USER PREFERENCES (Cross-Project)
-- ============================================================

CREATE TABLE user_preferences (
    key          TEXT PRIMARY KEY,
    value_json   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

-- ============================================================
-- SCHEMA VERSION TRACKING
-- ============================================================
-- Use PRAGMA user_version for migration tracking.
-- Current schema version: 1
```

### 7.2 Schema Design Rationale

**Why an events table AND a runs table?** The events table is the general-purpose audit trail. The runs table is a specialized index for research provenance queries. Many state changes (preference updates, memory writes, session starts) are not "analyses" and do not belong in a runs DAG, but they must be auditable. The events table handles this. The runs table is a derived view that can be rebuilt from events, but keeping it materialized avoids expensive replay for common lineage queries.

**Why evidence_json as a JSON column?** Evidence pointers are heterogeneous (they can reference events, artifacts, dataset versions, or runs). A JSON array of typed pointers (`[{"type": "run", "id": "..."}, {"type": "artifact", "id": "..."}]`) is more flexible than multiple foreign key columns and avoids the need for a separate junction table. Queried via `json_extract()` with generated column indexes for frequently filtered paths.

**Why memory_type as a text enum?** This enables structured queries like `SELECT * FROM memory_entries WHERE memory_type = 'open_question' AND status = 'active'` without relying on semantic search. It is the cheapest, most reliable way to answer "what are our open questions?" or "what assumptions have we made?"

**Why both code_hash and code_artifact_id on operations?** The hash enables quick equality checks and deduplication. The artifact_id links to the full code stored on the filesystem. Both are needed: the hash for integrity verification, the artifact_id for content retrieval.

**Why hash chaining on the event log?** Optional but valuable: `event_hash = SHA-256(type + payload + prev_event_hash)` creates a tamper-evident chain. If any event is modified or deleted, downstream hashes break. This provides strong integrity guarantees for audit and reproducibility.

---

## Part 3: Runtime Behavior

---

## 8. Retrieval Strategy

### 8.1 The Three-Stage Retrieval Pipeline

Not every user message should trigger memory retrieval. The system uses a three-stage pipeline:

**Stage 1: Decide whether to retrieve.**

Following Self-RAG's critique of indiscriminate retrieval, IRIS gates retrieval based on signals:
- **Retrieve**: User references prior work ("what did we find?"), asks about a dataset ("what is column X?"), requests reproduction/modification of an artifact, asks to do something similar to a prior analysis, or explicitly asks IRIS to remember/recall something.
- **Do not retrieve**: Simple follow-up questions, formatting requests, clarifications of the current turn, or requests that are fully answerable from the current conversation context.

This gating can be implemented as a simple classifier (rule-based in V1, LLM-assisted in V2) that examines the user's message for retrieval-triggering patterns.

**Stage 2: Candidate retrieval (hybrid search).**

When retrieval is triggered:
1. **Structured filter first**: project_id, dataset_id, memory_type, status=active. This eliminates irrelevant candidates before any expensive search.
2. **Lexical search (FTS5)**: Pull obvious hits for column names, variable labels, error messages, operation names. Fast, predictable, and excellent for exact-match queries.
3. **Vector search (V2+)**: Semantic similarity for queries that do not match lexically but are conceptually related. Uses sqlite-vec or ChromaDB with metadata filters to avoid cross-contamination.
4. **Deduplicate**: Near-duplicate memories (>0.92 cosine similarity) are collapsed, keeping the higher-scored entry.

**Stage 3: Rerank, compress, and inject.**

Apply the triple-weighted scoring model from Generative Agents:

```
score = α * relevance + β * recency + γ * importance
```

Default weights: α=0.5, β=0.2, γ=0.3 (tunable per project).

- **Relevance**: Cosine similarity between query embedding and memory embedding (V2+), or FTS5 BM25 score (V1).
- **Recency**: Exponential decay based on time since last access, with configurable half-life.
- **Importance**: The LLM-assigned 1-10 score stored on the memory entry.

Select the top N memories (default max: 10) that fit within the token budget for the retrieval segment. Compress long entries by extracting key sentences. Keep evidence pointers visible in the injected context so the LLM can cite its sources.

**Important caveat about the scoring weights**: The α/β/γ defaults are initial heuristics, not research-proven constants. They should be tuned based on retrieval-to-usage metrics (Section 11.5).

### 8.2 Conditional Retrieval Triggers (Specific Patterns)

Beyond the general pipeline, IRIS should recognize specific retrieval patterns:

| User intent | What to retrieve |
|-------------|-----------------|
| "What did we conclude about X?" | Active conclusions + supporting evidence pointers |
| "What is column Y?" / dataset question | Dataset card + latest dataset version schema |
| "Reproduce/modify that plot" | Artifact record + the run that produced it (code + parameters) |
| "Do something similar to what we did before" | Prior analyses with highest similarity + importance + recency |
| "What have we tried?" | Episodic log filtered by topic, including failed attempts |
| "What assumptions are we making?" | All memory_entries where memory_type = 'assumption' AND status = 'active' |
| "What's still unresolved?" | All memory_entries where memory_type = 'open_question' AND status = 'active' |
| Starting a new session | Open questions from prior sessions + stale-flagged items needing revalidation |

---

## 9. Context Assembly

### 9.1 Segment-Based Context Structure

Every LLM call assembles context as ordered segments. The ordering is designed for both relevance and **prompt cache efficiency** (Anthropic's prompt caching requires exact prefix matches, so stable content goes first and changes are pushed to the end):

**Segment 1 -- System prompt (~800 tokens, stable, cached)**

IRIS identity, capabilities, output format specifications, tool definitions (or tool router if catalog is large). This never changes within a session and benefits maximally from prompt caching.

**Segment 2 -- Project core memory (~1,500-3,000 tokens, semi-stable, cached)**

The always-on `PROJECT.md` content. Updated only when the user approves changes, so it remains cacheable for most of a session.

**Segment 3 -- Dataset context (~500-1,500 tokens, semi-stable)**

Current active dataset schema, column descriptions, summary statistics (row count, data types, value ranges, missing data percentages). Regenerated when a new dataset is loaded or transformed.

**Segment 4 -- Retrieved memories (~1,000-2,000 tokens, dynamic)**

Selected via the three-stage retrieval pipeline (Section 8). Only included when retrieval is triggered.

**Segment 5 -- Relevant prior analyses (~500-1,000 tokens, dynamic)**

When the current query relates to a previously performed analysis, a compressed summary of that analysis: what was done, what was found, what code was used.

**Segment 6 -- Relevant operations (~300-500 tokens, conditional)**

When the user's request involves a data operation and a matching skill exists in the library with >80% similarity and >70% success rate, include its description and code.

**Segment 7 -- Conversation history (remaining budget, dynamic)**

Recent messages from the current session stay verbatim. Tool calls: keep the tool_use record but **clear bulky tool_result bodies** when the output is re-fetchable (read the file again, re-run the query). This is the single most important compaction rule for data analysis. Previous session summaries are retrieved only when semantically relevant.

### 9.2 Token Budget Management

Assuming Claude's 200K context window, approximate allocation:

| Segment | Tokens | Notes |
|---------|--------|-------|
| 1. System prompt | ~800 | Fully stable, cached |
| 2. Core memory | ~2,500 | Semi-stable |
| 3. Dataset context | ~1,000 | Changes with dataset |
| 4. Retrieved memories | ~1,500 | Dynamic per query |
| 5. Prior analyses | ~750 | Dynamic, conditional |
| 6. Operations | ~400 | Conditional |
| 7. Conversation + response | ~193,000 | Remaining budget |

These are maximums, not targets. Most conversations will use far less. The key principle is that **segments 1-3 are always present** (analogous to MemGPT's core memory), while **segments 4-6 are retrieved selectively** (analogous to archival memory). This creates a predictable, debuggable context assembly process.

### 9.3 Tool-Result Clearing (Critical for Data Analysis)

This deserves special emphasis because it is the most common practical problem for a data analysis assistant:

**Rule**: After a tool call's output has been used by the assistant to formulate a response, the full tool_result content should be replaced with a compact stub: `[Tool result for {tool_name}: {brief summary}. Full output available as artifact {artifact_id}.]`

**Why**: A single pandas describe() output can be 2,000+ tokens. A correlation matrix for 20 columns is 5,000+ tokens. Ten tool calls in a session can consume 30,000+ tokens of stale output that is easily re-fetchable by re-reading the file or re-running the computation.

**When to clear**: After the assistant has responded to the turn that used the tool result. Keep the stub for the remainder of the session (for context), but do not carry full tool output bodies across turns.

**What to preserve**: The tool_use record (what tool was called, with what parameters) is always kept. The event log has the full output if it is ever needed.

---

## 10. Memory Lifecycle

### 10.1 Memory Creation

New semantic memories are created through two pathways:

**Passive extraction (the default)**

After each assistant response that contains substantive analysis results, the system runs a lightweight extraction pass. This follows Mem0's pattern: an LLM call examines the conversation turn and identifies candidate memories (findings, assumptions, caveats, open questions, decisions). Each candidate is:
1. Compared against existing memories using similarity (FTS5 in V1, embedding similarity in V2).
2. If a match above 0.85 similarity exists, the existing memory is updated rather than duplicated.
3. If no match, a new memory is created with the LLM-assigned importance score.
4. An importance threshold (default: 4 on the 1-10 scale) filters out trivial observations ("the data loaded successfully").

**Active creation**

The user or assistant explicitly marks something as worth remembering (e.g., "Remember that column X has a known data quality issue"). This creates a memory with higher importance and explicit user attribution.

**Episodic creation (always-on)**

Analysis records (runs) are created automatically for every analysis operation, capturing full provenance. This is deterministic, not LLM-dependent. Every tool call, dataset import, transformation, and artifact creation is logged in the event table. Significant analyses are indexed in the runs table.

### 10.2 Consolidation and Reflection

**Session-end consolidation (every session)**

When a session closes:
1. The conversation is summarized by the LLM.
2. Key memories are extracted via passive extraction if not already done.
3. The analysis DAG (runs) is finalized.
4. The core memory document (`PROJECT.md`) is checked for staleness and an update is proposed if warranted.
5. Open questions from the session are extracted and stored.

**Importance-based reflection (periodic)**

Following the Generative Agents model, IRIS triggers a reflection cycle when accumulated importance scores of new memories since the last reflection exceed a threshold (default: triggered after roughly every 5-8 substantive analyses). The reflection process:
1. Retrieves the most recent memories and analyses.
2. Prompts the LLM: "Given these recent findings and analyses, what are the most important high-level insights, updated conclusions, and remaining open questions?"
3. Stores the resulting reflections as new memory entries of type "reflection" with high importance scores.
4. Proposes core memory updates that the user can accept or modify.

**Compaction-based consolidation (when needed)**

When context pressure forces summarization of older conversation history, this is also a good time to consolidate memory. Letta's documentation describes this as "dreaming/reflection" triggered by compaction events.

**Consolidation after major artifacts**

When a report, slide deck, or significant analysis product is completed, trigger a consolidation step: what did we learn? What decisions were made? What remains open?

### 10.3 Staleness Detection and Management

Memories degrade over time. IRIS implements four staleness mechanisms:

**Temporal decay**

Memories not accessed for a configurable period are flagged:
- Findings: 90 days default.
- Assumptions: 30 days default.
- Open questions: 60 days default.

Unlike GitHub Copilot's hard 28-day deletion, IRIS marks memories as "stale" rather than deleting them, since research conclusions may remain valid for extended periods. Stale memories are still retrievable but are prefixed with `[Finding from {date}, may need revalidation]` when injected into context.

**Contradiction detection**

When a new finding contradicts an existing memory (detected by the LLM during extraction), both the old and new memory are flagged. The old memory's status changes to "contradicted" with a pointer to the contradicting evidence. Both are recorded in the contradictions table. The user is notified and must resolve the contradiction before either memory is used as a "promoted" conclusion.

**Source invalidation**

If a run that sourced a memory is later found to be flawed (user marks it as incorrect, or a rerun with different data produces different results), downstream memories are flagged for review. This follows the PROV-DM derivation model: if an activity is invalidated, its output entities are suspect.

**Periodic consolidation (memify)**

A background process (run at session start or on user request) reviews the memory store:
- Merges near-duplicate memories (>0.85 similarity in V2+).
- Updates confidence scores based on corroborating evidence.
- Prunes memories with zero access count after a threshold period (default: 180 days).
- Produces a consolidation report the user can review.

### 10.4 Deletion

Users can delete any memory explicitly. Deleted memories are soft-deleted (status set to "archived" with timestamp) rather than hard-deleted, preserving the audit trail. A purge operation hard-deletes soft-deleted records older than a configurable retention period (default: 365 days). The event log records all deletions.

---

## 11. Preventing Memory Pathologies

Poor memory behavior is the greatest risk to a research assistant's trustworthiness. This section catalogs specific failure modes and their defenses.

### 11.1 Hallucinated Memories

**Risk**: The LLM generates a claim not backed by any stored memory or evidence, and it gets stored as a "finding."

**Defense**: Provenance linking. Every semantic memory traces back to a source_analysis_id and evidence_json. Memories without evidence pointers are flagged as "ungrounded" and given lower retrieval priority. The extraction pipeline should require the LLM to cite specific evidence (message IDs, tool output, dataset observations) when proposing new memories.

### 11.2 Stale Conclusions

**Risk**: A finding from an early analysis persists in memory even after the data has changed, the methodology has been refined, or a contradicting result has been found.

**Defense**: Temporal decay + contradiction detection + source invalidation (Section 10.3). Additionally, every memory carries both `created_at` and `last_validated_at` timestamps. When a stale memory is retrieved, it is explicitly marked in context.

### 11.3 Contradictory Summaries

**Risk**: Reflection or consolidation produces a summary that contradicts existing memories, and the old memory is silently overwritten.

**Defense**: Never silently overwrite. The contradictions table records both sides with evidence. The user is presented with both the old and new understanding and must resolve the contradiction. Core memory updates always require user approval.

### 11.4 Low-Signal Accumulation

**Risk**: Trivial observations pile up in memory, diluting the signal-to-noise ratio and consuming retrieval budget.

**Defense**: Importance threshold (minimum 4/10 for storage). The extraction pipeline filters out trivial observations. The periodic memify consolidation merges near-duplicates and prunes zero-access memories.

### 11.5 Over-Retrieval and Context Pollution

**Risk**: Retrieving too many memories wastes context tokens, confuses the model, and can actually degrade response quality (per Self-RAG's findings).

**Defense**: Hard token budget per retrieval segment (Section 9.2). Maximum memory count per query (default: 10). Semantic deduplication (>0.92 threshold). Retrieval gating (Section 8.1). Additionally, track **retrieval-to-usage ratio**: if retrieved memories are consistently ignored by the model (detected by analyzing whether the response references them), the retrieval parameters should be tightened. This is a V2+ metric.

### 11.6 Tool-Result Bloat

**Risk**: Data analysis tool outputs (tables, stats, logs) accumulate in context and crowd out more useful information.

**Defense**: Tool-result clearing (Section 9.3). This is the single most impactful anti-pollution measure for IRIS specifically.

---

## Part 4: Skills, Scaling, and Roadmap

---

## 12. Dynamically Generated Operations (Skill Library)

### 12.1 Design Philosophy

IRIS wraps Claude and a catalog of hardcoded data-analysis skills. When the existing catalog is insufficient, Claude can generate new project-specific operations on the fly. These generated operations should not be ephemeral prompt snippets. They should be treated as versioned, validated, provenance-linked software artifacts, following the Voyager skill library pattern adapted for data analysis.

### 12.2 Operation Lifecycle

```
Proposal → Generation → Sandbox Tests → Validation Run → Semver Release
    → Retrieval + Monitoring → Deprecation (never deletion)
```

**Step 1: Proposal.** When Claude determines the hardcoded catalog is insufficient, it proposes a tool specification: name, description, input schema, output schema, invariants, and examples.

**Step 2: Generation.** Claude writes the Python code for the operation, following the parameter schema.

**Step 3: Sandbox testing.** Before the operation enters the library:
- Static checks (imports, type hints, syntax).
- Unit tests on small synthetic inputs.
- Sandbox execution to verify no side effects.

**Step 4: Validation run.** Execute the operation on a sample of the actual input data. Check output against validation criteria (schema conformance, expected output ranges, absence of NaN values, plausibility checks). Only operations that pass are promoted to "validated" status. Failed validations are stored with status "draft" and can be manually reviewed and fixed.

**Step 5: Semver release.** The validated operation is stored in `ops/<name>/v<semver>/` with its code, schema, tests, and README. It is registered in the operations table with a new version number. When modified, a new version is created as a child of the original (via parent_op_id), preserving the complete evolution history.

**Step 6: Retrieval and monitoring.** Operations are retrieved during context assembly (Segment 6) when the user's request matches a stored operation. Each use increments use_count and updates last_used_at and success_rate, creating a natural signal of which operations are most valuable.

**Step 7: Deprecation.** When an operation is found buggy or superseded, it is marked "deprecated" but never deleted. Old versions remain accessible for reproducibility (any artifact produced by version X can still reference and re-execute version X).

### 12.3 Operation Retrieval

When IRIS generates code to handle a user request, it first queries the skill library:

1. **Hard filter**: project_id match (or global) + validation_status = 'validated'.
2. **FTS5 search**: Keyword matching on name + description.
3. **Vector search (V2+)**: Embedding similarity on description.
4. **Rerank**: Boost operations with higher success rates, higher use counts, and more recent use.

If a match scoring above 0.8 combined similarity is found, the operation's code is included in context as a starting point. The LLM can reuse it directly, adapt it, or compose it with other operations.

### 12.4 Cross-Project Sharing

Operations with `project_id = NULL` are global, available across all projects. Project-specific operations can be promoted to global status when the user determines they are generally useful. This two-tier scoping prevents operations designed for one dataset's quirks from polluting retrieval in unrelated projects.

### 12.5 Workflow Templates (V3)

When a multi-step analysis pattern recurs (e.g., "load CSV, clean missing values, compute correlations, generate heatmap"), the entire sequence can be stored as a reusable workflow template. A 2025 paper on agentic plan caching (arXiv:2506.14852) demonstrated 46.62% cost reduction by extracting reusable plan templates from successful agent execution logs. This is a V3 capability.

---

## 13. Scaling Across Project Sizes

The architecture is designed for graceful scaling: the same code runs at all sizes, with components activating as complexity demands.

### 13.1 Small Personal Projects (1-3 datasets, <20 sessions, single user)

**What matters most**: Pinned Project Brief, Dataset Card, Decision Register, and reliable artifact provenance.

**What can be simpler**: Retrieval can use FTS5 only (no vector search). Reflection cycles may not trigger at all if the importance threshold is not reached. The skill library starts empty and grows slowly. Vector search over <1,000 memories is instantaneous with brute-force.

**What to watch for**: Aggressive tool-result clearing matters a lot because token budgets are easily blown by tables and logs.

### 13.2 Medium Multi-Dataset Projects (3-10 datasets, 20-100 sessions, single user)

**What matters most**: This is the sweet spot for the architecture. Core memory needs regular updating. The skill library becomes genuinely useful. Cross-dataset memories provide real value. Reflection cycles trigger regularly.

**What should be added**: Stronger dataset versioning and transformation lineage. A richer "open questions" workflow. Vector retrieval becomes valuable because there are many prior analyses to rediscover, but must be filtered and curated to avoid low-signal accumulation.

### 13.3 Large Long-Running Projects (10+ datasets, 100+ sessions, potentially collaborative)

**What matters most**: Provenance and reproducibility features become essential. Memory consolidation and pruning are critical to prevent context pollution. The analysis DAG grows deep with many branches.

**What should be added**: User attribution on memories and analyses. Conflict resolution for shared core memory. Tool routing (retrieve subsets) for large skill libraries. Consider upgrading sqlite-vec to ChromaDB or LanceDB for better approximate nearest neighbor performance. Lightweight knowledge graph (entity-relationship triples in SQLite, traversed via recursive CTEs) for multi-hop reasoning across datasets.

**Collaboration considerations**: Start with "collaboration via version control" (portable project folders + sync). If multi-user editing becomes necessary, Ink & Switch's local-first literature suggests CRDTs as a foundation for conflict resolution while preserving local ownership.

---

## 14. Implementation Roadmap

### 14.1 V1: Practical Foundation

**Goal**: Get core memory, basic episodic tracking, event logging, and the skill library working reliably. No vector search. No reflection cycles. No continuous extraction.

**Storage**:
- SQLite with WAL mode, FTS5 for text search, JSON columns for flexible metadata.
- Filesystem artifact store with content hashes.
- Curated Markdown memory docs (PROJECT.md, DATASETS/, DECISIONS.md, OPEN_QUESTIONS.md).

**Core memory**: Structured Markdown document always injected in the system prompt. Updated via explicit user edits or LLM-proposed revisions after significant analyses. Stored in both the database and a human-readable file.

**Session memory**: Full conversation history stored in SQLite. Most recent N messages (fitting a token budget) included in context. No summarization in V1, just truncation with a "previous session" marker. Session metadata generated at session close.

**Event log**: All events recorded with type, timestamp, payload. Hash chaining optional in V1 but schema should support it.

**Analysis tracking**: Every analysis logged in runs table with input hash, code, parameters, output hash, findings. Simple parent-child linking for sequential analyses. No branching DAG yet, just a linear sequence per session with cross-session references.

**Skill library**: Operations stored with name, description, code, parameters, and basic usage statistics. Retrieval via FTS5 text search on description + name. Self-verification deferred to V2.

**Memory extraction**: At session end, the LLM extracts key findings, decisions, and open questions from the conversation. Stored as semantic memories with manually assigned importance. No continuous extraction during the session.

**Retrieval**: FTS5 only. Structured filter + lexical search + token budget. No vector search. Hybrid reranking deferred to V2.

**Tool-result clearing**: Implemented from day one. This is non-negotiable.

**Cold start**: When a new project is created, generate an initial PROJECT.md scaffold (goal, datasets, constraints) from the user's first message. Refine via user-approved diffs after early analyses.

**What V1 deliberately omits**: Vector embeddings, knowledge graphs, automatic importance scoring, continuous extraction, reflection cycles, contradiction detection, background consolidation, branching DAG, workflow templates. These add complexity without providing value until the foundation is solid.

### 14.2 V2: Intelligence Layer

Build after V1 is proven reliable.

**Add vector search**: Integrate sqlite-vec or ChromaDB. Compute embeddings for all semantic memories and operation descriptions using `all-MiniLM-L6-v2` (384 dimensions, ~80MB model, fast local inference). Implement triple-weighted retrieval (relevance + recency + importance). For users with more compute, `nomic-embed-text` (768 dimensions, 8K context window) via Ollama provides better quality.

**Add continuous extraction**: During conversations, not just at session end, extract and store significant facts. Implement the Mem0-style extraction-update pipeline with deduplication.

**Add reflection cycles**: When accumulated importance crosses a threshold, trigger reflection. Store reflections as high-importance memories. Propose core memory updates.

**Add progressive summarization**: Older sessions compressed into summaries. Summaries retrievable by semantic similarity.

**Add operation validation**: Before promoting a generated operation to the skill library, run it on sample data and verify output against validation criteria.

**Add contradiction detection**: When a new memory contradicts an existing one, flag both and notify the user. Populate the contradictions table.

**Add the analysis DAG**: Enable branching analyses, rollback to any previous state, and cross-session lineage tracking.

**Add citation-validation hooks**: Implement Copilot-inspired evidence validation, where memories are checked against current data state before being used.

**Add retrieval-to-usage metrics**: Track which retrieved memories the model actually uses in its responses. Use this signal to tune retrieval weights.

### 14.3 V3: Advanced Capabilities

Build when V2 is stable and project complexity demands it.

**Lightweight knowledge graph**: Extract entities and relationships from analyses, store as triples in SQLite, traverse via recursive CTEs. Use LightRAG-style dual-level retrieval (specific entities + broader themes). This enables multi-hop reasoning: "What findings from the marketing dataset are relevant to the patterns we found in sales data?"

**Workflow templates**: Detect recurring multi-step analysis patterns and store as reusable templates (the plan caching pattern).

**Collaborative features**: User attribution on memories and analyses, conflict resolution for core memory, shared skill libraries, CRDT-backed shared state for curated memory docs.

**Adaptive retrieval**: Use retrieval-to-usage metrics to automatically tune retrieval weights per project.

**Tool routing**: For large skill libraries, embed tool/skill descriptions and retrieve top-k tools per turn rather than exposing all tools.

**Programmatic tool orchestration**: For multi-step analysis workflows, prefer code-orchestrated tool calling where intermediate results stay in the sandbox and only distilled results enter the model context.

---

## Part 5: References and Assessment

---

## 15. Bibliography and Source Assessment

### 15.1 Primary Sources (High Confidence)

These are peer-reviewed papers, official documentation, or established engineering references. Claims sourced to these are well-supported.

1. **MemGPT** (Packer et al., 2023). "MemGPT: Towards LLMs as Operating Systems." arXiv:2310.08560. https://arxiv.org/pdf/2310.08560
2. **Generative Agents** (Park et al., 2023). "Generative Agents: Interactive Simulacra of Human Behavior." arXiv:2304.03442. https://3dvar.com/Park2023Generative.pdf
3. **Self-RAG** (Asai et al., 2023). "Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection." arXiv:2310.11511. https://arxiv.org/abs/2310.11511
4. **Reflexion** (Shinn et al., NeurIPS 2023). "Reflexion: Language Agents with Verbal Reinforcement Learning." arXiv:2303.11366. https://arxiv.org/abs/2303.11366
5. **Voyager** (Wang et al., 2023). "Voyager: An Open-Ended Embodied Agent with Large Language Models." arXiv:2305.16291. https://voyager.minedojo.org/
6. **CoALA** (Sumers et al., 2023). "Cognitive Architectures for Language Agents." arXiv:2309.02427. https://arxiv.org/html/2309.02427v3
7. **Mem0** (Chhablani et al., 2025). "Mem0: Building Production-Ready AI Agents with Scalable Long-Term Memory." arXiv:2504.19413. https://arxiv.org/abs/2504.19413
8. **Lost in the Middle** (Liu et al., 2023). "Lost in the Middle: How Language Models Use Long Contexts." https://cs.stanford.edu/~nfliu/papers/lost-in-the-middle.arxiv2023.pdf
9. **Legal RAG Hallucinations** (Stanford, 2024). Evidence that hallucinations persist even with retrieval. https://law.stanford.edu/wp-content/uploads/2024/05/Legal_RAG_Hallucinations.pdf
10. **Agentic Plan Caching** (2025). "Cost-Efficient Serving of LLM Agents via Test-Time Plan Caching." arXiv:2506.14852. https://arxiv.org/html/2506.14852v1
11. **Memory Survey** (2026). "Memory for Autonomous LLM Agents: Mechanisms, Evaluation, and Emerging Frontiers." arXiv:2603.07670.

### 15.2 Official Documentation (High Confidence)

12. **W3C PROV-DM**. "The PROV Data Model." https://www.w3.org/TR/prov-dm/
13. **Anthropic Context Engineering**. "Effective context engineering for AI agents." https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
14. **Anthropic Tool-Result Clearing**. Context engineering cookbook. https://platform.claude.com/cookbook/tool-use-context-engineering-context-engineering-tools
15. **Anthropic Prompt Caching**. https://platform.claude.com/docs/en/build-with-claude/prompt-caching
16. **Anthropic Tool Use**. https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview
17. **Anthropic Advanced Tool Use**. https://www.anthropic.com/engineering/advanced-tool-use
18. **Claude Code Memory**. https://code.claude.com/docs/en/memory
19. **GitHub Copilot Memory**. https://docs.github.com/en/copilot/concepts/agents/copilot-memory
20. **Windsurf Cascade Memories**. https://docs.windsurf.com/windsurf/cascade/memories
21. **SQLite WAL**. https://sqlite.org/wal.html
22. **SQLite FTS5**. https://www.sqlite.org/fts5.html
23. **Event Sourcing** (Martin Fowler). https://martinfowler.com/eaaDev/EventSourcing.html
24. **Git Internals**. Content-addressable storage. https://git-scm.com/book/en/v2/Git-Internals-Git-Objects
25. **Local-First Software** (Ink & Switch). https://www.inkandswitch.com/essay/local-first/

### 15.3 Framework Documentation (Medium Confidence)

These describe specific tools' implementations. Useful for patterns but subject to change.

26. **LangGraph Persistence**. https://docs.langchain.com/oss/python/langgraph/persistence
27. **LangMem Conceptual Guide**. https://langchain-ai.github.io/langmem/concepts/conceptual_guide/
28. **LlamaIndex Memory**. https://developers.llamaindex.ai/python/framework/module_guides/deploying/agents/memory/
29. **Letta/MemGPT Docs**. https://docs.letta.com/concepts/memgpt/
30. **Cognee Architecture**. https://www.cognee.ai/blog/fundamentals/how-cognee-builds-ai-memory
31. **Mem0 Graph Memory**. https://docs.mem0.ai/open-source/graph_memory/overview

### 15.4 Disputed or Uncertain Claims

**ChatGPT's memory implementation**: One source report claims "ChatGPT injects all saved memories into every single prompt with no selective retrieval." OpenAI's own documentation states that relevant information from past conversations "may be added to new ones," without asserting deterministic inclusion of all memories. Treat proprietary implementations as partially unknown. IRIS should be designed around transparent, debuggable retrieval rather than mimicking any closed-system behavior.

**Specific retrieval weight values** (α=0.5, β=0.2, γ=0.3): These are initial heuristics proposed in one source report, not empirically validated constants. The Generative Agents paper demonstrates the value of combining relevance, recency, and importance but does not prescribe specific weights for production systems. Treat these as starting points to be tuned with metrics.

---

## Appendix A: Memory UX Requirements (Critical Gap)

All source reports identified memory UX as a gap. These requirements are essential but were not fully specified in any source. They are included here as design constraints for implementation.

### A.1 User Inspection

Users must be able to:
- View all stored memories for a project, filtered by type and status.
- See the evidence chain for any memory (which analysis, session, and data produced it).
- See which memories were loaded into the current conversation's context.

### A.2 User Control

Users must be able to:
- Edit any memory's text, importance, or status.
- Delete any memory (soft-delete with audit trail).
- Accept or reject proposed core memory updates.
- Lock important memories to prevent automatic consolidation or pruning.
- Trigger a consolidation/reflection cycle manually.

### A.3 Cold Start

When a new project is created:
1. Generate an initial `PROJECT.md` scaffold from the user's first message (goal, datasets, constraints).
2. Generate initial dataset cards when datasets are uploaded (schema, column descriptions, basic stats).
3. Refine both via user-approved diffs after early analyses.
4. The system should acknowledge its empty state: "This is a new project. I'll build up context as we work together."

### A.4 Memory Quality Metrics

Instrument these metrics from V2 onward:
- **Retrieval-to-usage ratio**: How often retrieved memories are actually referenced in the response.
- **Stale-memory hit rate**: How often stale-flagged memories are retrieved.
- **Contradiction rate**: How often new findings contradict existing memories.
- **Reproducibility success rate**: Can logged runs be replayed successfully?
- **User correction rate**: How often users edit or delete system-generated memories.

### A.5 Cost Awareness

Memory extraction and reflection are extra LLM calls. For cost optimization:
- Use prompt caching (stable prefixes first in context assembly).
- Use plan/template caching for recurring multi-step workflows (V3).
- Batch memory extraction (end-of-session rather than per-turn in V1).
- Track per-project memory-system token usage separately from analysis token usage.

---

## Appendix B: Decision Log

This appendix records key architectural decisions and their rationale for future reference.

| Decision | Chosen | Alternatives Considered | Rationale |
|----------|--------|------------------------|-----------|
| Primary store | SQLite (WAL) | PostgreSQL, DuckDB | Local-first requirement; no server process; single portable file; proven in Letta dev mode and Cognee default stack |
| Event log design | Append-only table in SQLite with hash chaining | Separate event files, external event store | Unified with metadata store; simpler ops; hash chain provides integrity |
| Provenance model | Event log (source of truth) + runs DAG (derived index) | Event log only, runs DAG only | Events capture everything (including non-analysis state changes); DAG provides ergonomic lineage queries |
| Core memory format | Dual: DB row + Markdown file | DB only, file only | DB for programmatic access; file for human inspection and editing; sync required but proven pattern |
| Memory extraction approach | Passive (system extracts) with active override | Agent-directed (LLM chooses), user-only | Passive reduces user burden; agent-directed costs tokens and is unreliable per Cognition findings |
| Retrieval gating | Explicit (decide whether to retrieve) | Always retrieve, never retrieve | Self-RAG evidence that indiscriminate retrieval harms quality |
| Vector search in V1 | Deferred to V2 | Include from V1 | FTS5 BM25 is adequate for V1; avoids embedding model dependency; reduces complexity |
| Tool-result clearing | From V1, non-negotiable | Defer to V2 | Most impactful anti-pollution measure; zero inference cost; critical for data analysis |
| Operation versioning | Semver with parent chain | Git-backed, append-only | Simpler than git integration; parent chain preserves history; immutable versions enable reproducibility |
| Memory deletion policy | Soft-delete (365-day retention) | Hard-delete, never delete | Preserves audit trail; eventual purge prevents unbounded growth |
| Contradiction handling | Log both sides, require user resolution | Auto-resolve (newer wins), ignore | Research integrity requires human judgment on conflicting findings |
| Staleness policy | Flag + revalidation (not auto-delete) | Hard expiry (Copilot's 28 days), no expiry | Research conclusions may remain valid longer than code patterns; flagging surfaces uncertainty without data loss |

---

*Document version: 1.0*
*Created: April 2026*
*Source materials: Claude Research Report, ChatGPT Research Report, Synthesis Report, Cross-Report Comparison Analysis*
*Intended audience: IRIS development team (Phillip)*
*Next review: After V1 implementation is complete*
