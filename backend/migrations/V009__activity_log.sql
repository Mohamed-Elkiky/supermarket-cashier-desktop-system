-- =============================================================
-- V009 — Activity Log
-- =============================================================
-- Tamper-proof audit trail of every write operation system-wide.
-- No role can UPDATE or DELETE from this table.
-- The application layer writes to it after every successful
-- write operation. The DB-level RULE below enforces immutability
-- at the database level as a second line of defence.
-- =============================================================

CREATE TABLE activity_log (
    id                      BIGSERIAL       PRIMARY KEY,
    -- Who performed the action (NULL only for system-automated actions)
    actor_staff_id          INTEGER         REFERENCES staff(id) ON DELETE SET NULL,
    actor_role              staff_role,
    -- What action was performed
    action                  VARCHAR(100)    NOT NULL,  -- e.g. 'order.create', 'product.update'
    -- What record was affected
    entity_type             VARCHAR(100)    NOT NULL,  -- e.g. 'order', 'product_variant'
    entity_id               VARCHAR(50)     NOT NULL,  -- stringified PK of affected record
    -- Full before/after snapshot stored as JSONB for queryability
    before_state            JSONB,
    after_state             JSONB,
    -- Device and location context
    device_identifier       VARCHAR(255),              -- Electron app instance ID
    ip_address              INET,
    -- UTC timestamp — immutable
    occurred_at             TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

-- Prevent any UPDATE or DELETE on this table at the database level
-- This is the second line of defence after application-layer enforcement
CREATE RULE activity_log_no_update AS ON UPDATE TO activity_log DO INSTEAD NOTHING;
CREATE RULE activity_log_no_delete AS ON DELETE TO activity_log DO INSTEAD NOTHING;

-- Indexes for the owner dashboard filters and audit queries
CREATE INDEX idx_activity_log_actor       ON activity_log(actor_staff_id);
CREATE INDEX idx_activity_log_entity      ON activity_log(entity_type, entity_id);
CREATE INDEX idx_activity_log_occurred_at ON activity_log(occurred_at DESC);
CREATE INDEX idx_activity_log_action      ON activity_log(action);
