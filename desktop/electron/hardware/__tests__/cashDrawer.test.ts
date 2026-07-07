// @vitest-environment node
import { describe, it, expect, afterAll } from "vitest";
import fs from "node:fs";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const drawer = require("../cashDrawer.js");

const KICK = Buffer.from([0x1b, 0x70]); // ESC p
const created: string[] = [];
afterAll(() => created.forEach((f) => fs.rmSync(f, { force: true })));

describe("drawer pulse bytes", () => {
  it("emits the exact standard kick sequence by default", () => {
    expect([...drawer.drawerPulseBytes()]).toEqual([0x1b, 0x70, 0x00, 0x19, 0xfa]);
  });

  it("supports pin 5 and configurable on/off durations", () => {
    expect([...drawer.drawerPulseBytes({ pin: 5, onTime: 50, offTime: 100 })]).toEqual([
      0x1b, 0x70, 0x01, 50, 100,
    ]);
  });
});

describe("shouldOpenDrawer predicate", () => {
  it("opens for cash", () => {
    expect(drawer.shouldOpenDrawer({ payment_method: "cash" })).toBe(true);
  });

  it("opens for mixed only when cash was tendered", () => {
    expect(drawer.shouldOpenDrawer({ payment_method: "mixed", cash_tendered_pence: 500 })).toBe(true);
    expect(drawer.shouldOpenDrawer({ payment_method: "mixed", cash_tendered_pence: 0 })).toBe(false);
  });

  it("does NOT open for card or loyalty", () => {
    expect(drawer.shouldOpenDrawer({ payment_method: "card" })).toBe(false);
    expect(drawer.shouldOpenDrawer({ payment_method: "loyalty_points" })).toBe(false);
  });
});

describe("dry-run drawer open", () => {
  it("writes the kick bytes to a dry-run file", async () => {
    process.env.POS_PRINTER_DRYRUN = "1";
    try {
      const res = await drawer.open();
      expect(res.opened).toBe(true);
      expect(res.dryRun).toBe(true);
      created.push(res.outputPath);
      const bytes = fs.readFileSync(res.outputPath);
      expect(bytes.indexOf(KICK)).toBeGreaterThanOrEqual(0);
    } finally {
      delete process.env.POS_PRINTER_DRYRUN;
    }
  });

  it("openAfterPayment opens for cash and skips for card", async () => {
    process.env.POS_PRINTER_DRYRUN = "1";
    try {
      const cash = await drawer.openAfterPayment({ payment_method: "cash", cash_tendered_pence: 1000 });
      expect(cash.opened).toBe(true);
      if (cash.outputPath) created.push(cash.outputPath);

      const card = await drawer.openAfterPayment({ payment_method: "card" });
      expect(card.opened).toBe(false);
    } finally {
      delete process.env.POS_PRINTER_DRYRUN;
    }
  });
});
