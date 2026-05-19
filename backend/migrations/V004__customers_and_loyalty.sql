-- =============================================================
-- V004 — Customers and Loyalty
-- =============================================================
-- Customer PII is stored here. Columns containing PII are
-- encrypted at rest using pgcrypto / application-level encryption
-- before insert (handled by the Django service layer).
-- Loyalty points and tier are derived from loyalty_transactions.
-- =============================================================

CREATE TABLE customers (
    id                      SERIAL          PRIMARY KEY,
    -- PII — encrypted at rest by application layer
    first_name              VARCHAR(100)    NOT NULL,
    last_name               VARCHAR(100)    NOT NULL,
    email                   VARCHAR(254)    UNIQUE,
    phone                   VARCHAR(30),
    date_of_birth           DATE,
    address_line1           VARCHAR(255),
    address_line2           VARCHAR(255),
    city                    VARCHAR(100),
    postcode                VARCHAR(20),
    -- Allergen preferences for basket conflict warnings at POS
    -- Stored as an array of allergen IDs the customer wants flagged
    allergen_preferences    INTEGER[]       NOT NULL DEFAULT '{}',
    -- GDPR consent
    marketing_consent       BOOLEAN         NOT NULL DEFAULT FALSE,
    marketing_consent_at    TIMESTAMPTZ,
    is_active               BOOLEAN         NOT NULL DEFAULT TRUE,
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_customers_email    ON customers(email);
CREATE INDEX idx_customers_phone    ON customers(phone);
CREATE INDEX idx_customers_postcode ON customers(postcode);

-- =============================================================

CREATE TYPE loyalty_tier AS ENUM ('bronze', 'silver', 'gold');

CREATE TABLE loyalty_accounts (
    id                      SERIAL          PRIMARY KEY,
    customer_id             INTEGER         NOT NULL UNIQUE REFERENCES customers(id) ON DELETE CASCADE,
    -- Current tier — recalculated on every order completion
    tier                    loyalty_tier    NOT NULL DEFAULT 'bronze',
    -- Cumulative lifetime spend in pence/cents (integer avoids float rounding)
    lifetime_spend_pence    BIGINT          NOT NULL DEFAULT 0,
    -- Current redeemable point balance (derived from loyalty_transactions SUM)
    -- Stored here as a cache — always recalculated on redemption to prevent drift
    points_balance          INTEGER         NOT NULL DEFAULT 0,
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

-- =============================================================

CREATE TYPE loyalty_transaction_type AS ENUM (
    'earn',         -- points added on order completion
    'redeem',       -- points spent at POS
    'adjustment',   -- manual manager adjustment (requires reason)
    'expire'        -- periodic expiry run
);

CREATE TABLE loyalty_transactions (
    id                      BIGSERIAL       PRIMARY KEY,
    loyalty_account_id      INTEGER         NOT NULL REFERENCES loyalty_accounts(id),
    transaction_type        loyalty_transaction_type NOT NULL,
    points                  INTEGER         NOT NULL,   -- positive = earn, negative = redeem/expire
    -- Order that triggered this transaction (nullable for manual adjustments)
    order_id                INTEGER,        -- FK added after orders table V005
    -- Mandatory for adjustment type
    reason                  TEXT,
    performed_by            INTEGER,        -- FK added after staff table V007
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    CONSTRAINT adjustment_requires_reason
        CHECK (transaction_type != 'adjustment' OR reason IS NOT NULL)
);

CREATE INDEX idx_loyalty_tx_account_id ON loyalty_transactions(loyalty_account_id);
CREATE INDEX idx_loyalty_tx_order_id   ON loyalty_transactions(order_id) WHERE order_id IS NOT NULL;
