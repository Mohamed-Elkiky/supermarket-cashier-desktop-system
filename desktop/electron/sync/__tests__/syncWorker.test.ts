// @vitest-environment node
import { describe, it, expect, beforeAll, afterAll, beforeEach } from "vitest";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const db = require("../../db/database.js");
const sync = require("../syncWorker.js");

interface MockClient {
  calls: {
    openOrder: string[];
    addItem: Array<{ orderId: number; item: unknown }>;
    confirm: number[];
    checkout: Array<{ client_uuid: string; estimatedTotalPence?: number }>;
  };
  openOrder(uuid: string): Promise<{ id: number }>;
  addItem(orderId: number, item: unknown): Promise<unknown>;
  confirm(orderId: number): Promise<unknown>;
  checkout(orderId: number, payload: { client_uuid: string }): Promise<{ total_pence: number }>;
  getProducts(): Promise<unknown>;
  getPromotions(): Promise<unknown>;
  health(): Promise<boolean>;
}

function makeClient(opts: { failCheckoutTimes?: number } = {}): MockClient {
  let failCheckoutTimes = opts.failCheckoutTimes ?? 0;
  const calls: MockClient["calls"] = { openOrder: [], addItem: [], confirm: [], checkout: [] };
  return {
    calls,
    async openOrder(uuid) {
      calls.openOrder.push(uuid);
      return { id: 1000 + calls.openOrder.length };
    },
    async addItem(orderId, item) {
      calls.addItem.push({ orderId, item });
      return {};
    },
    async confirm(orderId) {
      calls.confirm.push(orderId);
      return {};
    },
    async checkout(_orderId, payload) {
      calls.checkout.push(payload as { client_uuid: string });
      if (failCheckoutTimes > 0) {
        failCheckoutTimes -= 1;
        throw new Error("network down");
      }
      return { total_pence: 500 };
    },
    async getProducts() {
      return [
        { id: 1, department: 7, name: "P", variants: [{ id: 11, sku: "S", name: "V", pricing_mode: "fixed", sell_price: 120, unit_of_measure: "each", barcode: null }] },
      ];
    },
    async getPromotions() {
      return [{ id: 1, name: "BOGOF", promotion_type: "bogof", is_active: true }];
    },
    async health() {
      return true;
    },
  };
}

let tmpDir: string;

beforeAll(async () => {
  tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "pos-sync-test-"));
  await db.init({ dbPath: path.join(tmpDir, "sync.db"), showFirstRunDialog: false });
});

afterAll(() => {
  try {
    db.close();
  } catch {
    /* ignore */
  }
  fs.rmSync(tmpDir, { recursive: true, force: true });
});

beforeEach(() => {
  db.ensureReady().prepare("DELETE FROM pending_transactions").run();
});

function sale(uuid: string) {
  return {
    client_uuid: uuid,
    items: [{ variant_id: 11, quantity: 1 }],
    payment: { payment_method: "card", age_verified: false },
    estimatedTotalPence: 500,
  };
}

describe("offline queue + replay", () => {
  it("persists a sale enqueued while offline", () => {
    sync.enqueueSale(sale("aaaa-1"));
    const pending = db.listPendingTransactions();
    expect(pending).toHaveLength(1);
    expect(pending[0].client_uuid).toBe("aaaa-1");
  });

  it("replays and drains the queue, carrying client_uuid to the backend", async () => {
    sync.enqueueSale(sale("bbbb-1"));
    sync.enqueueSale(sale("bbbb-2"));
    const client = makeClient();

    const result = await sync.replayQueue(client);
    expect(result.drained).toBe(2);
    expect(db.listPendingTransactions()).toHaveLength(0);
    expect(client.calls.checkout.map((c) => c.client_uuid)).toEqual(["bbbb-1", "bbbb-2"]);
    expect(client.calls.confirm).toHaveLength(2);
  });

  it("does not double-apply the same client_uuid (idempotency)", async () => {
    sync.enqueueSale(sale("dup-1"));
    sync.enqueueSale(sale("dup-1")); // duplicate enqueue -> ignored by UNIQUE constraint
    expect(db.listPendingTransactions()).toHaveLength(1);

    const client = makeClient();
    await sync.replayQueue(client);
    await sync.replayQueue(client); // replay again after drain

    const forUuid = client.calls.checkout.filter((c) => c.client_uuid === "dup-1");
    expect(forUuid).toHaveLength(1); // applied exactly once
    expect(db.listPendingTransactions()).toHaveLength(0);
  });

  it("increments attempts and retries a failing replay without dropping the row", async () => {
    sync.enqueueSale(sale("retry-1"));
    const client = makeClient({ failCheckoutTimes: 1 });

    const first = await sync.replayQueue(client);
    expect(first.failed).toBe(1);
    const afterFail = db.listPendingTransactions();
    expect(afterFail).toHaveLength(1);
    expect(afterFail[0].attempts).toBe(1);
    expect(afterFail[0].last_error).toContain("network down");

    const second = await sync.replayQueue(client);
    expect(second.drained).toBe(1);
    expect(db.listPendingTransactions()).toHaveLength(0);
  });
});

describe("cache refresh", () => {
  it("populates the product + promotion cache from the backend", async () => {
    const client = makeClient();
    const res = await sync.refreshCache(client);
    expect(res.products).toBe(1);
    expect(res.promotions).toBe(1);
    expect(db.getCachedProducts().length).toBe(1);
    expect(db.getCachedPromotions().length).toBe(1);
    expect(db.getMeta("last_synced_at")).toBeTruthy();
  });
});
