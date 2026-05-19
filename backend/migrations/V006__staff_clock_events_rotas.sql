-- =============================================================
-- V006 — Staff, Clock Events and Rotas
-- =============================================================
-- Staff are separate from Django auth users but linked by
-- auth_user_id. The auth layer (V008) will add the users table;
-- this table stores retail-specific staff attributes.
-- =============================================================

CREATE TYPE staff_role AS ENUM (
    'cashier',
    'department_manager',
    'store_manager',
    'admin',
    'owner'
);

CREATE TABLE staff (
    id                      SERIAL          PRIMARY KEY,
    -- Linked to Django auth user (FK added in V008 after users table exists)
    auth_user_id            INTEGER         UNIQUE,
    first_name              VARCHAR(100)    NOT NULL,
    last_name               VARCHAR(100)    NOT NULL,
    email                   VARCHAR(254)    NOT NULL UNIQUE,
    phone                   VARCHAR(30),
    role                    staff_role      NOT NULL DEFAULT 'cashier',
    -- Primary department assignment (staff can work across departments but have a home dept)
    department_id           INTEGER         REFERENCES departments(id) ON DELETE SET NULL,
    -- Commission rate as a decimal — e.g. 0.01 = 1%
    commission_rate         NUMERIC(5,4)    NOT NULL DEFAULT 0.0000,
    -- Hourly wage for payroll export
    hourly_wage             NUMERIC(8,2)    NOT NULL DEFAULT 0.00,
    is_active               BOOLEAN         NOT NULL DEFAULT TRUE,
    hired_at                DATE,
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_staff_role          ON staff(role);
CREATE INDEX idx_staff_department_id ON staff(department_id);

-- =============================================================

CREATE TYPE clock_event_type AS ENUM ('clock_in', 'clock_out');

CREATE TABLE staff_clock_events (
    id                      BIGSERIAL       PRIMARY KEY,
    staff_id                INTEGER         NOT NULL REFERENCES staff(id),
    event_type              clock_event_type NOT NULL,
    -- Recorded in UTC always
    event_at                TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    -- Was this recorded while offline and synced later?
    was_offline             BOOLEAN         NOT NULL DEFAULT FALSE,
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_clock_events_staff_id  ON staff_clock_events(staff_id);
CREATE INDEX idx_clock_events_event_at  ON staff_clock_events(event_at DESC);

-- =============================================================

CREATE TABLE rotas (
    id                      SERIAL          PRIMARY KEY,
    staff_id                INTEGER         NOT NULL REFERENCES staff(id),
    department_id           INTEGER         REFERENCES departments(id) ON DELETE SET NULL,
    -- Week commencing Monday (used to group the rota grid)
    week_commencing         DATE            NOT NULL,
    shift_date              DATE            NOT NULL,
    shift_start             TIME            NOT NULL,
    shift_end               TIME            NOT NULL,
    notes                   TEXT,
    created_by              INTEGER         REFERENCES staff(id) ON DELETE SET NULL,
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    CONSTRAINT rota_shift_times_valid CHECK (shift_end > shift_start)
);

CREATE INDEX idx_rotas_staff_id         ON rotas(staff_id);
CREATE INDEX idx_rotas_week_commencing  ON rotas(week_commencing);

-- =============================================================
-- Back-fill foreign keys that depended on staff table
-- =============================================================

ALTER TABLE inventory_ledger
    ADD CONSTRAINT fk_ledger_performed_by FOREIGN KEY (performed_by) REFERENCES staff(id);

ALTER TABLE loyalty_transactions
    ADD CONSTRAINT fk_loyalty_tx_performed_by FOREIGN KEY (performed_by) REFERENCES staff(id);

ALTER TABLE orders
    ADD CONSTRAINT fk_orders_cashier FOREIGN KEY (cashier_id) REFERENCES staff(id);

ALTER TABLE returns
    ADD CONSTRAINT fk_returns_authorised_by FOREIGN KEY (authorised_by) REFERENCES staff(id);

ALTER TABLE promotions
    ADD CONSTRAINT fk_promotions_created_by FOREIGN KEY (created_by) REFERENCES staff(id);
