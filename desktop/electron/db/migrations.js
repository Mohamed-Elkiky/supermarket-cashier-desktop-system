"use strict";

/**
 * Local cache / offline-queue schema for the encrypted SQLite database.
 *
 * All statements are idempotent (CREATE TABLE IF NOT EXISTS) so they can run on
 * every launch. Tables are defined now even where later tasks fill them:
 *   - products_cache / promotions_cache : offline catalogue (Task 12)
 *   - pending_transactions              : offline sale queue w/ idempotency key (Task 12)
 *   - pending_clock_events              : offline clock in/out queue (Task 13)
 *   - kv_meta                           : small key/value store (flags, sync markers)
 */

const STATEMENTS = [
  `CREATE TABLE IF NOT EXISTS kv_meta (
     key   TEXT PRIMARY KEY,
     value TEXT NOT NULL
   )`,

  `CREATE TABLE IF NOT EXISTS products_cache (
     variant_id       INTEGER PRIMARY KEY,
     product_id       INTEGER,
     sku              TEXT,
     barcode          TEXT,
     name             TEXT,
     pricing_mode     TEXT,
     sell_price_pence INTEGER,
     department_id    INTEGER,
     unit_of_measure  TEXT,
     payload_json     TEXT,
     updated_at       TEXT
   )`,

  `CREATE INDEX IF NOT EXISTS idx_products_cache_department
     ON products_cache (department_id)`,

  `CREATE INDEX IF NOT EXISTS idx_products_cache_barcode
     ON products_cache (barcode)`,

  `CREATE TABLE IF NOT EXISTS promotions_cache (
     id              INTEGER PRIMARY KEY,
     name            TEXT,
     promotion_type  TEXT,
     payload_json    TEXT,
     is_active       INTEGER NOT NULL DEFAULT 1,
     updated_at      TEXT
   )`,

  `CREATE TABLE IF NOT EXISTS pending_transactions (
     id           INTEGER PRIMARY KEY AUTOINCREMENT,
     client_uuid  TEXT UNIQUE NOT NULL,
     payload_json TEXT NOT NULL,
     created_at   TEXT NOT NULL,
     status       TEXT NOT NULL DEFAULT 'pending',
     attempts     INTEGER NOT NULL DEFAULT 0,
     last_error   TEXT
   )`,

  `CREATE INDEX IF NOT EXISTS idx_pending_transactions_status
     ON pending_transactions (status, id)`,

  `CREATE TABLE IF NOT EXISTS pending_clock_events (
     id           INTEGER PRIMARY KEY AUTOINCREMENT,
     client_uuid  TEXT UNIQUE NOT NULL,
     event_type   TEXT NOT NULL,
     occurred_at  TEXT NOT NULL,
     payload_json TEXT,
     created_at   TEXT NOT NULL,
     status       TEXT NOT NULL DEFAULT 'pending',
     attempts     INTEGER NOT NULL DEFAULT 0,
     last_error   TEXT
   )`,

  `CREATE INDEX IF NOT EXISTS idx_pending_clock_events_status
     ON pending_clock_events (status, id)`,
];

/** Apply every migration statement to an open better-sqlite3 database handle. */
function runMigrations(db) {
  for (const sql of STATEMENTS) {
    db.exec(sql);
  }
}

module.exports = { STATEMENTS, runMigrations };
