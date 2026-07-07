// @vitest-environment node
import { describe, it, expect, beforeEach, vi } from "vitest";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const notifier = require("../notifier.js");

beforeEach(() => notifier.resetDedupe());

describe("category -> route mapping", () => {
  it("maps each category to the right screen", () => {
    expect(notifier.routeForCategory("low_stock")).toBe("inventory");
    expect(notifier.routeForCategory("expiry")).toBe("inventory");
    expect(notifier.routeForCategory("food_safety_due")).toBe("food_safety");
    expect(notifier.routeForCategory("new_order")).toBe("checkout");
    expect(notifier.routeForCategory("unknown")).toBe("checkout");
  });
});

describe("dedupe / throttle", () => {
  it("fires a new key, suppresses repeats within cooldown, then fires after cooldown", () => {
    const cooldown = 1000;
    expect(notifier.shouldNotify("k1", 0, cooldown)).toBe(true);
    expect(notifier.shouldNotify("k1", 500, cooldown)).toBe(false); // within cooldown
    expect(notifier.shouldNotify("k1", 1500, cooldown)).toBe(true); // after cooldown
    expect(notifier.shouldNotify("k2", 1500, cooldown)).toBe(true); // different key
  });
});

describe("pollAlerts", () => {
  function makeClient(low: unknown[], opts: { lowStatus?: number } = {}) {
    return {
      async getLowStock() {
        if (opts.lowStatus) {
          const err = new Error("forbidden") as Error & { status?: number };
          err.status = opts.lowStatus;
          throw err;
        }
        return low;
      },
      async getExpiry() {
        return [];
      },
    };
  }

  const lowRows = [{ variant_id: 1, name: "Milk", current_stock: 2, low_stock_threshold: 5 }];

  it("fires a toast for a new low-stock alert and deep-links to inventory", async () => {
    const notifyFn = vi.fn();
    const res = await notifier.pollAlerts(makeClient(lowRows), {
      departmentIds: [10],
      now: 0,
      cooldownMs: 1000,
      notifyFn,
    });
    expect(res.fired).toEqual(["low_stock:1"]);
    expect(notifyFn).toHaveBeenCalledTimes(1);
    const [category, payload] = notifyFn.mock.calls[0];
    expect(category).toBe("low_stock");
    expect(payload.deepLink.route).toBe("inventory");
  });

  it("suppresses the same alert on a second poll within cooldown", async () => {
    const notifyFn = vi.fn();
    const client = makeClient(lowRows);
    await notifier.pollAlerts(client, { departmentIds: [10], now: 0, cooldownMs: 1000, notifyFn });
    const res2 = await notifier.pollAlerts(client, { departmentIds: [10], now: 500, cooldownMs: 1000, notifyFn });
    expect(res2.fired).toEqual([]);
    expect(notifyFn).toHaveBeenCalledTimes(1); // only the first poll fired
  });

  it("skips silently when the session is not a manager (403)", async () => {
    const notifyFn = vi.fn();
    const res = await notifier.pollAlerts(makeClient([], { lowStatus: 403 }), {
      departmentIds: [10],
      notifyFn,
    });
    expect(res.skipped).toBe(true);
    expect(res.reason).toBe("not_manager");
    expect(notifyFn).not.toHaveBeenCalled();
  });
});
