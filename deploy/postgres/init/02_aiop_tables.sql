-- AIOperator initial schema (Week 1 Day 1)
-- Single projection table mirroring RequirementWorkflow state for easy SQL queries / dashboards.
-- Temporal remains the source of truth; this table is rebuildable from workflow history.

CREATE SCHEMA IF NOT EXISTS aiop;

CREATE TABLE IF NOT EXISTS aiop.requirement (
    req_id              TEXT PRIMARY KEY,
    workflow_id         TEXT NOT NULL,
    title               TEXT NOT NULL,
    project             TEXT NOT NULL,
    created_by          TEXT NOT NULL,
    chat_id             TEXT,
    lifecycle_state     TEXT NOT NULL DEFAULT 'draft',
    current_phase       TEXT NOT NULL DEFAULT 'P0',
    current_phase_substate TEXT,
    priority            TEXT,
    risk_level          TEXT,
    suggested_risk      TEXT,
    cost_cap_usd        NUMERIC(10,4) NOT NULL DEFAULT 20.0,
    cost_used_usd       NUMERIC(10,4) NOT NULL DEFAULT 0.0,
    cost_reserved_usd   NUMERIC(10,4) NOT NULL DEFAULT 0.0,
    is_paused           BOOLEAN NOT NULL DEFAULT FALSE,
    summary             TEXT,
    user_story          TEXT,
    prd_path            TEXT,
    prd_doc_url         TEXT,
    code_pr_url         TEXT,
    last_commit_sha     TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_req_lifecycle ON aiop.requirement (lifecycle_state, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_req_project ON aiop.requirement (project, lifecycle_state);
