-- =============================================================
-- V010 — Final Wiring: Composite Indexes and Integrity Checks
-- =============================================================
-- This migration runs last and adds:
--   1. Composite indexes that span multiple tables (query-driven)
--   2. Any remaining cross-table integrity constraints
--   3. A DB-level function to compute current stock for a variant
-- =============================================================

-- =============================================================
-- Composite indexes for common POS and dashboard queries
-- =============================================================

-- "Show me all active variants in department X with their current stock"
CREATE INDEX idx_variants_department_active
    ON product_variants(product_id)
    INCLUDE (sku, barcode, pricing_mode, sell_price, is_active)
    WHERE is_active = TRUE;

-- "Show me all orders for cashier X on date Y" (end-of-day report)
CREATE INDEX idx_orders_cashier_date
    ON orders(cashier_id, paid_at)
    WHERE status = 'paid';

-- "Show me expiring batches within the next N days"
CREATE INDEX idx_ledger_expiry_window
    ON inventory_ledger(best_before_date, variant_id)
    WHERE best_before_date IS NOT NULL;

-- "Show me all temperature log failures in date range" (EHO export)
CREATE INDEX idx_temp_logs_fail_date
    ON food_safety_temperature_logs(checked_at DESC)
    WHERE result = 'fail';

-- =============================================================
-- Helper function: get current stock for a variant
-- Used by the application layer to check stock before sale
-- =============================================================

CREATE OR REPLACE FUNCTION get_variant_stock(p_variant_id INTEGER)
RETURNS NUMERIC AS $$
    SELECT COALESCE(SUM(quantity), 0)
    FROM   inventory_ledger
    WHERE  variant_id = p_variant_id;
$$ LANGUAGE SQL STABLE;

-- =============================================================
-- Helper function: get current loyalty points balance
-- Recalculates from the transaction log — prevents drift
-- =============================================================

CREATE OR REPLACE FUNCTION get_loyalty_balance(p_account_id INTEGER)
RETURNS INTEGER AS $$
    SELECT COALESCE(SUM(points), 0)
    FROM   loyalty_transactions
    WHERE  loyalty_account_id = p_account_id;
$$ LANGUAGE SQL STABLE;

-- =============================================================
-- Schema version record
-- =============================================================

CREATE TABLE schema_migrations (
    version     VARCHAR(20)     PRIMARY KEY,
    description VARCHAR(255)    NOT NULL,
    applied_at  TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

INSERT INTO schema_migrations (version, description) VALUES
    ('V001', 'Departments and suppliers'),
    ('V002', 'Products, variants and allergens'),
    ('V003', 'Inventory ledger'),
    ('V004', 'Customers and loyalty'),
    ('V005', 'Promotions, orders and returns'),
    ('V006', 'Staff, clock events and rotas'),
    ('V007', 'Expenses'),
    ('V008', 'Food safety logs'),
    ('V009', 'Activity log'),
    ('V010', 'Final wiring: indexes and helper functions');
