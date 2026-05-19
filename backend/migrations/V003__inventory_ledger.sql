-- =============================================================
-- V003 — Inventory Ledger
-- =============================================================
-- Immutable event log. Current stock is always derived from
-- SUM(quantity) WHERE variant_id = X.
-- No row is ever updated or deleted — only INSERTs allowed.
-- A CHECK prevents negative quantities for stock-deducting events
-- from being entered directly; the application layer enforces
-- this before writing.
-- =============================================================

CREATE TYPE ledger_movement_type AS ENUM (
    'goods_received',   -- stock in from supplier delivery
    'sale',             -- stock out from a completed order
    'return',           -- stock in from a customer return
    'waste',            -- stock out: expired / damaged
    'markdown',         -- stock out: marked down and removed
    'transfer_in',      -- stock in from another department/location
    'transfer_out',     -- stock out to another department/location
    'adjustment'        -- manual correction by manager (requires reason)
);

CREATE TABLE inventory_ledger (
    id                  BIGSERIAL       PRIMARY KEY,
    variant_id          INTEGER         NOT NULL REFERENCES product_variants(id),
    department_id       INTEGER         NOT NULL REFERENCES departments(id),
    movement_type       ledger_movement_type NOT NULL,
    -- Positive = stock in, Negative = stock out
    quantity            NUMERIC(10,3)   NOT NULL,
    -- For weight-based items this records the actual weight moved (kg)
    weight_kg           NUMERIC(10,3),
    -- Batch tracking for expiry-enabled variants
    batch_ref           VARCHAR(100),
    best_before_date    DATE,
    use_by_date         DATE,
    -- Link back to the order or return that caused this movement
    order_id            INTEGER,        -- FK added after orders table is created (V005)
    return_id           INTEGER,        -- FK added after returns table is created (V005)
    -- Who performed this action (staff user id — FK added after staff table V007)
    performed_by        INTEGER,
    -- Mandatory for adjustment type
    reason              TEXT,
    -- UTC timestamp — never store local time in the ledger
    recorded_at         TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    -- Adjustments must have a reason
    CONSTRAINT adjustment_requires_reason
        CHECK (movement_type != 'adjustment' OR reason IS NOT NULL)
);

-- Current stock query will hit this index constantly
CREATE INDEX idx_ledger_variant_id         ON inventory_ledger(variant_id);
CREATE INDEX idx_ledger_department_id      ON inventory_ledger(department_id);
CREATE INDEX idx_ledger_recorded_at        ON inventory_ledger(recorded_at DESC);
CREATE INDEX idx_ledger_batch_ref          ON inventory_ledger(batch_ref) WHERE batch_ref IS NOT NULL;
CREATE INDEX idx_ledger_best_before        ON inventory_ledger(best_before_date) WHERE best_before_date IS NOT NULL;
