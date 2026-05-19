-- =============================================================
-- V008 — Food Safety Logs
-- =============================================================
-- Two log types: temperature checks and cleaning sign-offs.
-- Both are permanent records — no updates, no deletes.
-- Formatted for Environmental Health Officer (EHO) export.
-- =============================================================

CREATE TYPE temperature_check_result AS ENUM ('pass', 'fail');

CREATE TABLE food_safety_temperature_logs (
    id                      BIGSERIAL       PRIMARY KEY,
    -- The unit being checked: fridge name, freezer name etc.
    unit_name               VARCHAR(100)    NOT NULL,
    department_id           INTEGER         NOT NULL REFERENCES departments(id),
    -- Temperature in Celsius (stored as decimal for precision)
    temperature_celsius     NUMERIC(5,2)    NOT NULL,
    -- Pass/fail determined against configured thresholds per unit
    result                  temperature_check_result NOT NULL,
    -- If failed, corrective action taken
    corrective_action       TEXT,
    -- Who performed the check
    performed_by            INTEGER         NOT NULL REFERENCES staff(id),
    -- When the check was performed (may differ from recorded_at if offline)
    checked_at              TIMESTAMPTZ     NOT NULL,
    was_offline             BOOLEAN         NOT NULL DEFAULT FALSE,
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_temp_logs_department_id ON food_safety_temperature_logs(department_id);
CREATE INDEX idx_temp_logs_checked_at    ON food_safety_temperature_logs(checked_at DESC);
CREATE INDEX idx_temp_logs_result        ON food_safety_temperature_logs(result);

-- =============================================================

CREATE TYPE cleaning_result AS ENUM ('completed', 'missed', 'partial');

CREATE TABLE food_safety_cleaning_logs (
    id                      BIGSERIAL       PRIMARY KEY,
    -- Description of what was cleaned: "deli slicer", "bakery prep area" etc.
    area_name               VARCHAR(200)    NOT NULL,
    department_id           INTEGER         NOT NULL REFERENCES departments(id),
    -- Scheduled interval in hours — e.g. 4 means "every 4 hours"
    scheduled_interval_hours INTEGER        NOT NULL DEFAULT 4,
    result                  cleaning_result NOT NULL,
    notes                   TEXT,
    -- Who signed off the cleaning
    performed_by            INTEGER         REFERENCES staff(id),
    -- Manager who was alerted if missed
    alerted_manager_id      INTEGER         REFERENCES staff(id),
    cleaned_at              TIMESTAMPTZ     NOT NULL,
    was_offline             BOOLEAN         NOT NULL DEFAULT FALSE,
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_cleaning_logs_department_id ON food_safety_cleaning_logs(department_id);
CREATE INDEX idx_cleaning_logs_cleaned_at    ON food_safety_cleaning_logs(cleaned_at DESC);
CREATE INDEX idx_cleaning_logs_result        ON food_safety_cleaning_logs(result);
