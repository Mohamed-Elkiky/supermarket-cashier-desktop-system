// @vitest-environment node
import { describe, it, expect, beforeAll, afterAll } from "vitest";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
// CommonJS main-process module under test.
const db = require("../database.js");

describe("db pure helpers (no native binary required)", () => {
  it("generates a 64-char hex key", () => {
    const key = db.generateKeyHex();
    expect(key).toMatch(/^[0-9a-f]{64}$/);
    expect(db.generateKeyHex()).not.toBe(key); // random
  });

  it("validates key hex", () => {
    expect(db.isValidKeyHex(db.generateKeyHex())).toBe(true);
    expect(db.isValidKeyHex("nope")).toBe(false);
    expect(db.isValidKeyHex("AB".repeat(32))).toBe(false); // uppercase not allowed
    expect(db.isValidKeyHex(123)).toBe(false);
  });

  it("detects a plaintext SQLite header", () => {
    // Real 16-byte magic: "SQLite format 3" followed by a NUL (0x00).
    const plaintext = Buffer.concat([
      Buffer.from("SQLite format 3", "latin1"),
      Buffer.from([0x00]),
      Buffer.from("rest of file", "latin1"),
    ]);
    const encrypted = Buffer.from("fb5cad211727a16c767ee05be742775c", "hex");
    expect(db.looksLikePlaintextSqlite(plaintext)).toBe(true);
    expect(db.looksLikePlaintextSqlite(encrypted)).toBe(false);
  });
});

describe("encrypted database operations", () => {
  let tmpDir: string;
  let dbFile: string;

  beforeAll(async () => {
    tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "pos-db-test-"));
    dbFile = path.join(tmpDir, "test.db");
    await db.init({ dbPath: dbFile, showFirstRunDialog: false });
  });

  afterAll(() => {
    try {
      db.close();
    } catch {
      /* ignore */
    }
    fs.rmSync(tmpDir, { recursive: true, force: true });
  });

  it("created all cache/queue tables", () => {
    const conn = db.ensureReady();
    const names = conn
      .prepare("SELECT name FROM sqlite_master WHERE type='table'")
      .all()
      .map((r: { name: string }) => r.name);
    expect(names).toEqual(
      expect.arrayContaining([
        "kv_meta",
        "products_cache",
        "promotions_cache",
        "pending_transactions",
        "pending_clock_events",
      ]),
    );
  });

  it("writes an encrypted file (not a plaintext SQLite db)", () => {
    const bytes = fs.readFileSync(dbFile);
    expect(bytes.length).toBeGreaterThan(0);
    expect(db.looksLikePlaintextSqlite(bytes)).toBe(false);
  });

  it("round-trips kv_meta", () => {
    expect(db.getMeta("missing")).toBeNull();
    db.setMeta("greeting", "hello");
    expect(db.getMeta("greeting")).toBe("hello");
    db.setMeta("greeting", "updated");
    expect(db.getMeta("greeting")).toBe("updated"); // upsert
  });

  it("caches products and filters by department", () => {
    db.replaceProductsCache([
      { variant_id: 1, name: "Milk", department_id: 10, sell_price_pence: 120 },
      { variant_id: 2, name: "Bread", department_id: 20, sell_price_pence: 90 },
    ]);
    expect(db.getCachedProducts().length).toBe(2);
    const dept10 = db.getCachedProducts(10);
    expect(dept10.length).toBe(1);
    expect(dept10[0].name).toBe("Milk");
  });

  it("caches only active promotions", () => {
    db.replacePromotionsCache([
      { id: 1, name: "BOGOF", is_active: true },
      { id: 2, name: "Old", is_active: false },
    ]);
    const active = db.getCachedPromotions();
    expect(active.length).toBe(1);
    expect(active[0].name).toBe("BOGOF");
  });

  it("enqueues transactions idempotently by client_uuid", () => {
    const uuid = "11111111-1111-1111-1111-111111111111";
    db.enqueueTransaction({ client_uuid: uuid, total_pence: 500 });
    db.enqueueTransaction({ client_uuid: uuid, total_pence: 500 }); // duplicate
    const pending = db.listPendingTransactions();
    expect(pending.filter((t: { client_uuid: string }) => t.client_uuid === uuid).length).toBe(1);
  });

  it("records failures with incrementing attempts, then completes", () => {
    const uuid = "22222222-2222-2222-2222-222222222222";
    db.enqueueTransaction({ client_uuid: uuid, total_pence: 100 });
    db.recordTransactionFailure(uuid, "network down");
    db.recordTransactionFailure(uuid, "still down");
    const row = db
      .listPendingTransactions()
      .find((t: { client_uuid: string }) => t.client_uuid === uuid);
    expect(row.attempts).toBe(2);
    expect(row.last_error).toContain("still down");
    db.markTransactionDone(uuid);
    expect(
      db.listPendingTransactions().find((t: { client_uuid: string }) => t.client_uuid === uuid),
    ).toBeUndefined();
  });

  it("enqueues clock events idempotently and reports queue depth", () => {
    const uuid = "33333333-3333-3333-3333-333333333333";
    db.enqueueClockEvent({ client_uuid: uuid, event_type: "clock_in" });
    db.enqueueClockEvent({ client_uuid: uuid, event_type: "clock_in" });
    expect(db.listPendingClockEvents().length).toBe(1);
    const status = db.getQueueStatus();
    expect(status.pendingClockEvents).toBe(1);
    expect(typeof status.pendingTransactions).toBe("number");
  });
});
