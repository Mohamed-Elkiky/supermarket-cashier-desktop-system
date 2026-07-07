// @vitest-environment node
import { describe, it, expect, afterAll } from "vitest";
import fs from "node:fs";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const layout = require("../receiptLayout.js");
const printer = require("../receiptPrinter.js");

const SAMPLE_RECEIPT = {
  receipt_number: "R-2026-000123",
  paid_at: "2026-07-06T10:30:00Z",
  cashier: "Alice",
  items: [
    {
      name: "Organic Bananas Loose",
      sku: "BAN-001",
      quantity: 1,
      weight_kg: 0.734,
      unit_price_display: "£1.20",
      discount_display: null,
      promotion_name: null,
      line_total_display: "£0.88",
    },
    {
      name: "Cheddar Cheese Block 400g",
      sku: "CHE-400",
      quantity: 2,
      weight_kg: null,
      unit_price_display: "£3.50",
      discount_display: "-£0.50",
      promotion_name: "Cheese Weekend",
      line_total_display: "£6.50",
    },
  ],
  subtotal_display: "£7.88",
  discount_total_display: "-£0.50",
  tax_total_display: "£0.00",
  total_display: "£7.38",
  payment_method: "cash",
  cash_tendered_display: "£10.00",
  change_display: "£2.62",
  loyalty_points_earned: 7,
  age_verified: false,
};

const INIT = Buffer.from([0x1b, 0x40]);
const CUT_PREFIX = Buffer.from([0x1d, 0x56]);

const createdFiles: string[] = [];
afterAll(() => {
  for (const f of createdFiles) {
    try {
      fs.rmSync(f, { force: true });
    } catch {
      /* ignore */
    }
  }
});

describe("column math", () => {
  it("maps paper widths to column counts", () => {
    expect(layout.charsForWidth(58)).toBe(32);
    expect(layout.charsForWidth(80)).toBe(48);
    expect(layout.charsForWidth(999)).toBe(48); // default 80mm
  });

  it("formatLine fills exactly the paper width and right-aligns the value", () => {
    const l58 = layout.formatLine("Subtotal", "£7.88", 32);
    expect(l58).toHaveLength(32);
    expect(l58.endsWith("£7.88")).toBe(true);
    expect(l58.startsWith("Subtotal")).toBe(true);

    const l80 = layout.formatLine("Subtotal", "£7.88", 48);
    expect(l80).toHaveLength(48);
    expect(l80.endsWith("£7.88")).toBe(true);
  });

  it("truncates an over-long left label rather than overflowing", () => {
    const line = layout.formatLine("A very very long product name here", "£9.99", 32);
    expect(line).toHaveLength(32);
    expect(line.endsWith("£9.99")).toBe(true);
  });
});

describe("receipt buffer", () => {
  it("starts with ESC/POS init and ends with a cut, for 58mm", () => {
    const buf = layout.buildReceiptBuffer(SAMPLE_RECEIPT, 58);
    expect(buf.length).toBeGreaterThan(0);
    expect(buf.subarray(0, 2).equals(INIT)).toBe(true);
    expect(buf.indexOf(CUT_PREFIX)).toBeGreaterThan(0);
  });

  it("contains a Code128 barcode command for the receipt number", () => {
    const buf = layout.buildReceiptBuffer(SAMPLE_RECEIPT, 80);
    // GS k 73 (0x1d 0x6b 0x49) is the Code128 command
    expect(buf.indexOf(Buffer.from([0x1d, 0x6b, 0x49]))).toBeGreaterThan(0);
    expect(buf.includes(Buffer.from("R-2026-000123", "ascii"))).toBe(true);
  });

  it("differs between 58mm and 80mm layouts", () => {
    const b58 = layout.buildReceiptBuffer(SAMPLE_RECEIPT, 58);
    const b80 = layout.buildReceiptBuffer(SAMPLE_RECEIPT, 80);
    expect(b58.equals(b80)).toBe(false);
  });
});

describe("dry-run printing", () => {
  it("writes a non-empty .bin with init + cut when POS_PRINTER_DRYRUN=1", async () => {
    process.env.POS_PRINTER_DRYRUN = "1";
    try {
      const result = await printer.printReceipt(SAMPLE_RECEIPT, { widthMm: 80 });
      expect(result.dryRun).toBe(true);
      expect(result.outputPath).toBeTruthy();
      createdFiles.push(result.outputPath);

      const bytes = fs.readFileSync(result.outputPath);
      expect(bytes.length).toBeGreaterThan(0);
      expect(bytes.subarray(0, 2).equals(INIT)).toBe(true);
      expect(bytes.indexOf(CUT_PREFIX)).toBeGreaterThan(0);
    } finally {
      delete process.env.POS_PRINTER_DRYRUN;
    }
  });

  it("printTest also produces a dry-run buffer", async () => {
    process.env.POS_PRINTER_DRYRUN = "1";
    try {
      const result = await printer.printTest({ widthMm: 58 });
      expect(result.dryRun).toBe(true);
      createdFiles.push(result.outputPath);
      const bytes = fs.readFileSync(result.outputPath);
      expect(bytes.subarray(0, 2).equals(INIT)).toBe(true);
    } finally {
      delete process.env.POS_PRINTER_DRYRUN;
    }
  });

  it("list() never throws and returns an array with no printer attached", () => {
    const printers = printer.list();
    expect(Array.isArray(printers)).toBe(true);
  });
});
