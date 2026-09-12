-- ============================================================
-- Secondary NOC Database Schema (Instance 2)
-- Unidirectional Replica Target with Optimistic Lock Protection
-- ============================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 1. Mirrored Alerts Table
CREATE TABLE IF NOT EXISTS alerts (
    id BIGSERIAL PRIMARY KEY,
    identifier VARCHAR(255) UNIQUE NOT NULL,
    node VARCHAR(255) NOT NULL,
    alert_key VARCHAR(255) NOT NULL,
    severity VARCHAR(32) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'OPEN',
    summary TEXT NOT NULL,
    tally INT NOT NULL DEFAULT 1,
    version BIGINT NOT NULL DEFAULT 1,
    first_occurrence TIMESTAMPTZ NOT NULL,
    last_occurrence TIMESTAMPTZ NOT NULL,
    last_state_change TIMESTAMPTZ NOT NULL,
    is_flapping BOOLEAN NOT NULL DEFAULT FALSE,
    custom_fields JSONB NOT NULL DEFAULT '{}'::jsonb,
    deleted_at TIMESTAMPTZ NULL,
    replicated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Partial Index for active alerts on secondary site
CREATE INDEX IF NOT EXISTS idx_sec_alerts_active 
ON alerts (identifier, severity) 
WHERE status != 'RESOLVED' AND deleted_at IS NULL;

-- 2. Audit Trail of Replicated Modifications
CREATE TABLE IF NOT EXISTS alerts_replication_log (
    id BIGSERIAL PRIMARY KEY,
    identifier VARCHAR(255) NOT NULL,
    operation VARCHAR(32) NOT NULL,
    version BIGINT NOT NULL,
    severity VARCHAR(32) NOT NULL,
    status VARCHAR(32) NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
