-- =============================================================
-- V005 — Promotions, Orders, Order Items and Returns
-- =============================================================
-- Promotions are evaluated and snapshotted at checkout time.
-- Order and return records are permanent — no deletes.
-- All monetary values are stored in pence (integer) to avoid
-- floating-point rounding errors.
-- =============================================================

-- =============================================================
-- Promotions
-- =============================================================

CREATE TYPE promotion_type AS ENUM (
    'percentage_discount',  -- e.g. 10% off
    'fixed_amount_off',     -- e.g. £1.00 off
    'buy_one_get_one',      -- BOGO
    'three_for_two',        -- 3 items, pay for 2
    'meal_deal',            -- grouped bundle price
    'category_markdown'     -- % off entire department/category
);

CREATE TABLE promotions (
    id                  SERIAL          PRIMARY KEY,
    name                VARCHAR(255)    NOT NULL,
    promotion_type      promotion_type  NOT NULL,
    -- Discount value: percentage (0-100) or fixed pence amount depending on type
    discount_value      NUMERIC(10,2)   NOT NULL CHECK (discount_value > 0),
    -- Scope: applies to specific products, or a whole department
    department_id       INTEGER         REFERENCES departments(id) ON DELETE CASCADE,
    -- For meal_deal: minimum spend to qualify (pence)
    min_spend_pence     INTEGER,
    starts_at           TIMESTAMPTZ     NOT NULL,
    ends_at             TIMESTAMPTZ     NOT NULL,
    is_active           BOOLEAN         NOT NULL DEFAULT TRUE,
    created_by          INTEGER,        -- FK added after staff table V007
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    CONSTRAINT promotion_dates_valid CHECK (ends_at > starts_at)
);

-- Which specific variants does this promotion apply to?
-- Empty = applies to all variants in the department (for category_markdown)
CREATE TABLE promotion_variants (
    promotion_id        INTEGER         NOT NULL REFERENCES promotions(id) ON DELETE CASCADE,
    variant_id          INTEGER         NOT NULL REFERENCES product_variants(id) ON DELETE CASCADE,
    PRIMARY KEY (promotion_id, variant_id)
);

CREATE INDEX idx_promotions_active_dates ON promotions(starts_at, ends_at) WHERE is_active = TRUE;

-- =============================================================
-- Orders
-- =============================================================

CREATE TYPE order_status AS ENUM (
    'open',         -- basket being built
    'confirmed',    -- items finalised, awaiting payment
    'paid',         -- payment received, stock deducted
    'voided'        -- cancelled before payment
);

CREATE TYPE payment_method AS ENUM (
    'cash',
    'card',
    'loyalty_points',
    'mixed'         -- partial cash + points etc.
);

CREATE TABLE orders (
    id                      BIGSERIAL       PRIMARY KEY,
    status                  order_status    NOT NULL DEFAULT 'open',
    customer_id             INTEGER         REFERENCES customers(id) ON DELETE SET NULL,
    -- Staff who processed this order
    cashier_id              INTEGER,        -- FK added after staff table V007
    payment_method          payment_method,
    -- All monetary values in pence
    subtotal_pence          INTEGER         NOT NULL DEFAULT 0,
    discount_total_pence    INTEGER         NOT NULL DEFAULT 0,
    tax_total_pence         INTEGER         NOT NULL DEFAULT 0,
    total_pence             INTEGER         NOT NULL DEFAULT 0,
    -- Cash handling
    cash_tendered_pence     INTEGER,
    change_given_pence      INTEGER,
    -- Loyalty
    loyalty_points_earned   INTEGER         NOT NULL DEFAULT 0,
    loyalty_points_redeemed INTEGER         NOT NULL DEFAULT 0,
    -- Age verification — set when any age-restricted item is in the basket
    age_verified            BOOLEAN         NOT NULL DEFAULT FALSE,
    age_verification_id_type VARCHAR(50),   -- e.g. 'passport', 'driving_licence'
    -- Receipt reference printed on paper receipt
    receipt_number          VARCHAR(50)     UNIQUE,
    notes                   TEXT,
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    paid_at                 TIMESTAMPTZ,
    voided_at               TIMESTAMPTZ
);

CREATE INDEX idx_orders_customer_id ON orders(customer_id);
CREATE INDEX idx_orders_cashier_id  ON orders(cashier_id);
CREATE INDEX idx_orders_status      ON orders(status);
CREATE INDEX idx_orders_created_at  ON orders(created_at DESC);
CREATE INDEX idx_orders_paid_at     ON orders(paid_at DESC) WHERE paid_at IS NOT NULL;

-- =============================================================

CREATE TABLE order_items (
    id                      BIGSERIAL       PRIMARY KEY,
    order_id                BIGINT          NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    variant_id              INTEGER         NOT NULL REFERENCES product_variants(id),
    -- Snapshot the name and prices at time of sale — products can change later
    variant_name_snapshot   VARCHAR(255)    NOT NULL,
    unit_price_pence        INTEGER         NOT NULL,
    -- For weight-based items
    weight_kg               NUMERIC(10,3),
    -- Quantity: 1 for fixed-price items; for weight-based items always 1
    quantity                INTEGER         NOT NULL DEFAULT 1 CHECK (quantity > 0),
    -- Promotion applied to this line (if any)
    promotion_id            INTEGER         REFERENCES promotions(id) ON DELETE SET NULL,
    discount_pence          INTEGER         NOT NULL DEFAULT 0,
    -- Line total after discount
    line_total_pence        INTEGER         NOT NULL,
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_order_items_order_id   ON order_items(order_id);
CREATE INDEX idx_order_items_variant_id ON order_items(variant_id);

-- =============================================================
-- Returns (linked to original order)
-- =============================================================

CREATE TYPE return_status AS ENUM ('pending', 'approved', 'rejected', 'completed');

CREATE TABLE returns (
    id                      BIGSERIAL       PRIMARY KEY,
    original_order_id       BIGINT          NOT NULL REFERENCES orders(id),
    status                  return_status   NOT NULL DEFAULT 'pending',
    -- Who authorised the return
    authorised_by           INTEGER,        -- FK added after staff table V007
    -- Reason is mandatory
    reason                  TEXT            NOT NULL,
    refund_method           payment_method,
    refund_total_pence      INTEGER         NOT NULL DEFAULT 0,
    -- Loyalty points to reverse
    loyalty_points_reversed INTEGER         NOT NULL DEFAULT 0,
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    completed_at            TIMESTAMPTZ
);

CREATE INDEX idx_returns_original_order ON returns(original_order_id);

CREATE TABLE return_items (
    id                      BIGSERIAL       PRIMARY KEY,
    return_id               BIGINT          NOT NULL REFERENCES returns(id) ON DELETE CASCADE,
    order_item_id           BIGINT          NOT NULL REFERENCES order_items(id),
    quantity_returned       INTEGER         NOT NULL DEFAULT 1 CHECK (quantity_returned > 0),
    weight_returned_kg      NUMERIC(10,3),
    refund_pence            INTEGER         NOT NULL,
    -- Does this item go back to stock or written off as waste?
    return_to_stock         BOOLEAN         NOT NULL DEFAULT TRUE,
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

-- =============================================================
-- Back-fill foreign keys that depended on this table existing
-- =============================================================

ALTER TABLE inventory_ledger
    ADD CONSTRAINT fk_ledger_order  FOREIGN KEY (order_id)  REFERENCES orders(id),
    ADD CONSTRAINT fk_ledger_return FOREIGN KEY (return_id) REFERENCES returns(id);

ALTER TABLE loyalty_transactions
    ADD CONSTRAINT fk_loyalty_tx_order FOREIGN KEY (order_id) REFERENCES orders(id);
