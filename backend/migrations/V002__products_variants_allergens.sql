-- =============================================================
-- V002 — Products, Variants and Allergens
-- =============================================================
-- A product is the base item (e.g. "Whole Milk").
-- A variant is a specific sellable SKU (e.g. "Whole Milk 2L").
-- Allergens are stored on the variant because a 500g and 1kg
-- version of the same product can have different allergen profiles
-- (e.g. if produced in different facilities).
-- =============================================================

CREATE TABLE products (
    id                  SERIAL          PRIMARY KEY,
    department_id       INTEGER         NOT NULL REFERENCES departments(id),
    supplier_id         INTEGER         REFERENCES suppliers(id) ON DELETE SET NULL,
    name                VARCHAR(255)    NOT NULL,
    description         TEXT,
    is_age_restricted   BOOLEAN         NOT NULL DEFAULT FALSE,
    -- age_restriction_years: 18 for alcohol/tobacco, 16 for knives etc.
    age_restriction_years INTEGER,
    is_active           BOOLEAN         NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

-- =============================================================

CREATE TABLE product_variants (
    id                  SERIAL          PRIMARY KEY,
    product_id          INTEGER         NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    sku                 VARCHAR(100)    NOT NULL UNIQUE,
    barcode             VARCHAR(100)    UNIQUE,
    name                VARCHAR(255)    NOT NULL,   -- e.g. "Whole Milk 2L"
    -- Pricing mode: fixed or weight_based
    -- fixed:        sell_price is the price for one unit
    -- weight_based: sell_price is price-per-kg; line total = weight * sell_price
    pricing_mode        VARCHAR(20)     NOT NULL DEFAULT 'fixed'
                            CHECK (pricing_mode IN ('fixed', 'weight_based')),
    sell_price          NUMERIC(10,2)   NOT NULL CHECK (sell_price >= 0),
    cost_price          NUMERIC(10,2)   NOT NULL CHECK (cost_price >= 0),
    -- For weight-based items, this is the unit of measure displayed on labels
    unit_of_measure     VARCHAR(20)     NOT NULL DEFAULT 'unit'
                            CHECK (unit_of_measure IN ('unit', 'kg', 'g', 'litre', 'ml')),
    -- Low-stock threshold — triggers alert when stock_ledger sum falls below this
    low_stock_threshold INTEGER         NOT NULL DEFAULT 0,
    -- Best-before / use-by tracking is per batch in inventory_ledger
    -- This flag enables the tracking for this variant
    track_expiry        BOOLEAN         NOT NULL DEFAULT FALSE,
    expiry_alert_days   INTEGER         NOT NULL DEFAULT 3,
    is_active           BOOLEAN         NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_product_variants_product_id  ON product_variants(product_id);
CREATE INDEX idx_product_variants_barcode     ON product_variants(barcode);
CREATE INDEX idx_product_variants_sku         ON product_variants(sku);

-- =============================================================
-- EU mandatory allergens (14 as defined in Regulation 1169/2011)
-- =============================================================

CREATE TABLE allergens (
    id                  SERIAL          PRIMARY KEY,
    name                VARCHAR(100)    NOT NULL UNIQUE,
    -- EU-standardised code for exports / EHO reports
    eu_code             VARCHAR(10)     NOT NULL UNIQUE
);

INSERT INTO allergens (name, eu_code) VALUES
    ('Celery',              'CEL'),
    ('Cereals containing gluten', 'GLU'),
    ('Crustaceans',         'CRU'),
    ('Eggs',                'EGG'),
    ('Fish',                'FSH'),
    ('Lupin',               'LUP'),
    ('Milk',                'MLK'),
    ('Molluscs',            'MOL'),
    ('Mustard',             'MUS'),
    ('Nuts',                'NUT'),
    ('Peanuts',             'PNT'),
    ('Sesame seeds',        'SES'),
    ('Soya',                'SOY'),
    ('Sulphur dioxide and sulphites', 'SUL');

-- Junction: which allergens does each variant contain?
CREATE TABLE product_variant_allergens (
    variant_id          INTEGER         NOT NULL REFERENCES product_variants(id) ON DELETE CASCADE,
    allergen_id         INTEGER         NOT NULL REFERENCES allergens(id),
    -- may_contain: true = "may contain" trace, false = "contains"
    may_contain         BOOLEAN         NOT NULL DEFAULT FALSE,
    PRIMARY KEY (variant_id, allergen_id)
);
