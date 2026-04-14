-- V3 schema migration (REVAMP Task 17.1, spec Appendix A.4).
--
-- Adds the retrieval_events table used to track which memories the
-- retrieval layer surfaced per slice, and whether the subsequent
-- assistant turn actually cited/used them. Closes the loop on retrieval
-- quality so Task 17.2 can compute usage ratios.

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

PRAGMA user_version = 3;
