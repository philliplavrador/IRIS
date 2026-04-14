-- IRIS per-project SQLite schema (spec §7.1)
-- Transcribed from docs/memory-restructure.md.
-- Design inspired by event sourcing (append-only history), PROV-like
-- provenance edges, and content-addressed artifact separation (§7).
-- End of file sets PRAGMA user_version = 1 for migration tracking.

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
-- Rationale (§7.2): the events table is the general-purpose audit
-- trail; runs is a specialized derived index for provenance queries.
-- Hash chaining (prev_event_hash -> event_hash) provides a
-- tamper-evident chain: modifying any event breaks downstream hashes.

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
-- Rationale (§7.2): memory_type is a text enum so that structured
-- queries ("what are our open questions?", "what assumptions have
-- we made?") are cheap and reliable without semantic search.
-- evidence_json is JSON because evidence pointers are heterogeneous
-- (events, artifacts, dataset versions, runs); a typed-pointer array
-- avoids multiple FK columns and a junction table.

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
-- Rationale (§7.2): both code_hash and code_artifact_id are kept.
-- The hash enables quick equality checks and deduplication; the
-- artifact_id links to the full code stored on the filesystem.

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
-- RETRIEVAL EVENTS (V3 / Phase 17 — folded into the base schema
-- because the table is vec-free and useful for brand-new projects)
-- ============================================================
CREATE TABLE IF NOT EXISTS retrieval_events (
    retrieval_event_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    session_id TEXT,
    query TEXT NOT NULL,
    memory_ids_json TEXT NOT NULL,
    was_used_json TEXT,
    created_at TEXT NOT NULL,
    resolved_at TEXT,
    FOREIGN KEY (project_id) REFERENCES projects(project_id)
);

CREATE INDEX IF NOT EXISTS idx_retrieval_events_project
    ON retrieval_events(project_id, created_at DESC);

-- ============================================================
-- SCHEMA VERSION TRACKING
-- ============================================================
-- Use PRAGMA user_version for migration tracking.
-- Current schema version: 1
PRAGMA user_version = 1;
