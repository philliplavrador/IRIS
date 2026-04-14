-- V2 schema migration (REVAMP Task 11.2, spec §14.2)
--
-- Adds sqlite-vec virtual tables for vector retrieval. The embedding
-- dimension matches the V2 default provider (all-MiniLM-L6-v2, 384-dim);
-- projects using a different provider can re-create these with the
-- correct dimension before embedding.
--
-- Prerequisite: sqlite-vec extension loaded on the connection (see
-- iris.projects.db._try_load_vec). If VEC_AVAILABLE is False, running
-- this migration will fail at the CREATE VIRTUAL TABLE steps.

CREATE VIRTUAL TABLE IF NOT EXISTS memory_entries_vec USING vec0(
    embedding float[384]
);

CREATE VIRTUAL TABLE IF NOT EXISTS operations_vec USING vec0(
    embedding float[384]
);

PRAGMA user_version = 2;
