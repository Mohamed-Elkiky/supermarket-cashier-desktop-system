-- =============================================================
-- V007 — Expenses
-- =============================================================
-- Every expense entry is permanent — no updates, no deletes.
-- The description field is mandatory and must be a full body
-- of text explaining who, what, why, and amount.
-- =============================================================

CREATE TYPE expense_category AS ENUM (
    'staff_wages',
    'supplier_payment',
    'utilities',
    'rent',
    'maintenance',
    'equipment',
    'marketing',
    'insurance',
    'other'
);

CREATE TABLE expenses (
    id                      BIGSERIAL       PRIMARY KEY,
    category                expense_category NOT NULL,
    -- Mandatory full description: who, what, why, amount context
    description             TEXT            NOT NULL CHECK (LENGTH(TRIM(description)) >= 20),
    amount_pence            INTEGER         NOT NULL CHECK (amount_pence > 0),
    -- Who is this expense paid to?
    payee_name              VARCHAR(255),
    -- Link to supplier if this is a supplier payment
    supplier_id             INTEGER         REFERENCES suppliers(id) ON DELETE SET NULL,
    -- Who recorded this expense
    recorded_by             INTEGER         NOT NULL REFERENCES staff(id),
    -- Date the expense actually occurred (may differ from recorded_at)
    expense_date            DATE            NOT NULL,
    -- Supporting reference (invoice number, receipt ref etc.)
    reference               VARCHAR(100),
    -- Expenses are permanent — no updated_at column intentionally
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_expenses_category    ON expenses(category);
CREATE INDEX idx_expenses_expense_date ON expenses(expense_date DESC);
CREATE INDEX idx_expenses_recorded_by ON expenses(recorded_by);
CREATE INDEX idx_expenses_supplier_id ON expenses(supplier_id) WHERE supplier_id IS NOT NULL;
