-- ============================================================
-- Primary NOC Database Schema (Instance 1)
-- Implements Transactional Outbox, HOT Tuning, Flap Tracking
-- ============================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 1. Main Alerts Table
CREATE TABLE IF NOT EXISTS alerts (
    id BIGSERIAL PRIMARY KEY,
    identifier VARCHAR(255) UNIQUE NOT NULL,
    node VARCHAR(255) NOT NULL,
    alert_key VARCHAR(255) NOT NULL,
    severity VARCHAR(32) NOT NULL,       -- CRITICAL, WARNING, INFO, CLEAR
    status VARCHAR(32) NOT NULL DEFAULT 'OPEN', -- OPEN, ACKNOWLEDGED, RESOLVED, PURGED
    summary TEXT NOT NULL,
    tally INT NOT NULL DEFAULT 1,
    version BIGINT NOT NULL DEFAULT 1,  -- Monotonic version counter for optimistic locking
    first_occurrence TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_occurrence TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_state_change TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Flap Detection / Anti-Jitter
    is_flapping BOOLEAN NOT NULL DEFAULT FALSE,
    flap_count INT NOT NULL DEFAULT 0,
    last_flap_time TIMESTAMPTZ NULL,

    -- Dynamic Metadata Bag (Envelope Pattern)
    custom_fields JSONB NOT NULL DEFAULT '{}'::jsonb,
    deleted_at TIMESTAMPTZ NULL
);

-- ============================================================
-- Performance & Anti-Bloat Optimizations
-- ============================================================

-- HOT (Heap-Only Tuples) Update optimization: Leave 30% page space free
-- so frequent deduplication UPDATEs (tally, last_occurrence) avoid B-Tree index writes!
ALTER TABLE alerts SET (fillfactor = 70);

-- Table-level aggressive autovacuum tuning for high-churn NOC events
ALTER TABLE alerts SET (
    autovacuum_vacuum_scale_factor = 0.01,
    autovacuum_vacuum_threshold = 100,
    autovacuum_vacuum_cost_delay = 2,
    autovacuum_vacuum_cost_limit = 1000
);

-- Partial Index: Only index active (unresolved) alerts to keep index microscopic in memory
CREATE INDEX IF NOT EXISTS idx_alerts_active 
ON alerts (identifier, severity) 
WHERE status != 'RESOLVED' AND deleted_at IS NULL;

-- Index for node-level lookups
CREATE INDEX IF NOT EXISTS idx_alerts_node ON alerts (node);

-- 2. Transactional Outbox Table
CREATE TABLE IF NOT EXISTS alerts_outbox (
    id BIGSERIAL PRIMARY KEY,
    alert_id VARCHAR(255) NOT NULL,
    operation VARCHAR(32) NOT NULL,     -- INSERT, UPDATE, DELETE
    payload JSONB NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'PENDING', -- PENDING, PROCESSING, FAILED
    retry_count INT NOT NULL DEFAULT 0,
    last_error TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Partial index for instantaneous outbox worker polling
CREATE INDEX IF NOT EXISTS idx_outbox_pending 
ON alerts_outbox (id) 
WHERE status = 'PENDING';

-- 3. Dead Letter Queue (DLQ) Table for Poison Pills
CREATE TABLE IF NOT EXISTS alerts_dlq (
    id BIGSERIAL PRIMARY KEY,
    outbox_id BIGINT NOT NULL,
    alert_id VARCHAR(255) NOT NULL,
    payload JSONB NOT NULL,
    reason TEXT NOT NULL,
    failed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================
-- Outbox Triggers (Captures All State Changes Automatically)
-- ============================================================

CREATE OR REPLACE FUNCTION notify_outbox_trigger()
RETURNS TRIGGER AS $$
DECLARE
    json_data JSONB;
BEGIN
    -- Construct the standardized JSON Envelope required by the Security Gateway
    json_data := jsonb_build_object(
        'operation', TG_OP,
        'identifier', NEW.identifier,
        'node', NEW.node,
        'alert_key', NEW.alert_key,
        'severity', NEW.severity,
        'status', NEW.status,
        'summary', NEW.summary,
        'tally', NEW.tally,
        'version', NEW.version,
        'first_occurrence', NEW.first_occurrence,
        'last_occurrence', NEW.last_occurrence,
        'last_state_change', NEW.last_state_change,
        'is_flapping', NEW.is_flapping,
        'custom_fields', NEW.custom_fields,
        'deleted_at', NEW.deleted_at
    );

    -- Insert into transactional outbox
    INSERT INTO alerts_outbox (alert_id, operation, payload)
    VALUES (NEW.identifier, TG_OP, json_data);

    -- Instantly notify listening worker processes (<5ms latency)
    PERFORM pg_notify('alert_outbox_channel', 'new_record');

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_alerts_to_outbox ON alerts;
CREATE TRIGGER trg_alerts_to_outbox
AFTER INSERT OR UPDATE ON alerts
FOR EACH ROW EXECUTE FUNCTION notify_outbox_trigger();

-- Tombstone Trigger for physical deletes
CREATE OR REPLACE FUNCTION notify_tombstone_trigger()
RETURNS TRIGGER AS $$
DECLARE
    json_data JSONB;
BEGIN
    json_data := jsonb_build_object(
        'operation', 'DELETE',
        'identifier', OLD.identifier,
        'node', OLD.node,
        'alert_key', OLD.alert_key,
        'severity', OLD.severity,
        'status', 'PURGED',
        'summary', OLD.summary,
        'tally', OLD.tally,
        'version', OLD.version + 1,
        'deleted_at', NOW()
    );

    INSERT INTO alerts_outbox (alert_id, operation, payload)
    VALUES (OLD.identifier, 'DELETE', json_data);

    PERFORM pg_notify('alert_outbox_channel', 'new_record');

    RETURN OLD;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_alerts_tombstone ON alerts;
CREATE TRIGGER trg_alerts_tombstone
AFTER DELETE ON alerts
FOR EACH ROW EXECUTE FUNCTION notify_tombstone_trigger();
