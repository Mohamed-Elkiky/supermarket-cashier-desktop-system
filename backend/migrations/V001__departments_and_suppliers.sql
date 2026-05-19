-- =============================================================
-- V001 — Departments and Suppliers
-- =============================================================
-- Departments are the top-level organisational unit of the store.
-- Suppliers are internal-only — cashiers and customers never see them.
-- =============================================================

CREATE TABLE departments (
    id                  SERIAL          PRIMARY KEY,
    name                VARCHAR(100)    NOT NULL UNIQUE,
    -- e.g. fresh_produce, bakery, deli, dairy, frozen, beverages, custom
    slug                VARCHAR(100)    NOT NULL UNIQUE,
    tax_rate            NUMERIC(5,4)    NOT NULL DEFAULT 0.0000,   -- e.g. 0.2000 = 20%
    is_active           BOOLEAN         NOT NULL DEFAULT TRUE,
    display_order       INTEGER         NOT NULL DEFAULT 0,
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

-- Pre-seed the standard supermarket departments
INSERT INTO departments (name, slug, display_order) VALUES
    ('Fresh Produce',   'fresh-produce',    1),
    ('Bakery',          'bakery',           2),
    ('Deli Counter',    'deli-counter',     3),
    ('Dairy',           'dairy',            4),
    ('Frozen',          'frozen',           5),
    ('Beverages',       'beverages',        6);

-- =============================================================

CREATE TABLE suppliers (
    id                  SERIAL          PRIMARY KEY,
    name                VARCHAR(200)    NOT NULL,
    contact_name        VARCHAR(200),
    contact_email       VARCHAR(254),
    contact_phone       VARCHAR(30),
    address             TEXT,
    notes               TEXT,
    is_active           BOOLEAN         NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);
