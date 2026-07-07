// @vitest-environment node
import { describe, it, expect, afterAll } from "vitest";
import fs from "node:fs";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { computeLabelPrice, allergenSummary, buildEan13, isValidEan13, resolveBarcodeValue } =
  require("../labelLogic.js");
const { getTemplate, TEMPLATES } = require("../labelTemplates.js");
const labelPrinter = require("../labelPrinter.js");

const created: string[] = [];
afterAll(() => created.forEach((f) => fs.rmSync(f, { force: true })));

describe("label price maths", () => {
  it("computes weight * price-per-kg (pence)", () => {
    expect(computeLabelPrice({ weightKg: 0.734, pricePerKg: 350 })).toEqual({
      pence: 257, // round(350 * 0.734) = 256.9 -> 257
      display: "£2.57",
    });
  });
  it("uses an explicit total price when provided", () => {
    expect(computeLabelPrice({ totalPrice: 199 })).toEqual({ pence: 199, display: "£1.99" });
  });
});

describe("allergen summary", () => {
  it("separates contains from may-contain", () => {
    const s = allergenSummary([
      { name: "Milk" },
      { name: "Nuts", mayContain: true },
      { name: "Soy" },
    ]);
    expect(s.contains).toEqual(["Milk", "Soy"]);
    expect(s.mayContain).toEqual(["Nuts"]);
    expect(s.line).toBe("Contains: Milk, Soy  |  May contain: Nuts");
  });
});

describe("template selection", () => {
  it("selects a department template by key", () => {
    expect(getTemplate({ departmentKey: "deli" })).toBe(TEMPLATES.deli);
    expect(getTemplate({ departmentKey: "bakery" }).barcodeType).toBe("code128");
  });
  it("falls back to the default template for unknown departments", () => {
    expect(getTemplate({ departmentId: 99999 })).toBe(TEMPLATES.default);
    expect(getTemplate({})).toBe(TEMPLATES.default);
  });
  it("maps a numeric departmentId via POS_LABEL_TEMPLATE_MAP", () => {
    process.env.POS_LABEL_TEMPLATE_MAP = JSON.stringify({ "7": "deli" });
    try {
      expect(getTemplate({ departmentId: 7 })).toBe(TEMPLATES.deli);
    } finally {
      delete process.env.POS_LABEL_TEMPLATE_MAP;
    }
  });
});

describe("barcode encoding", () => {
  it("builds a valid, decodable EAN-13 with a correct check digit", () => {
    const code = buildEan13({ prefix: "02", plu: 1234, amount: 257 });
    expect(code).toMatch(/^\d{13}$/);
    expect(isValidEan13(code)).toBe(true);
  });

  it("embeds price for a deli (ean13) template and sku+weight for code128", () => {
    const price = computeLabelPrice({ weightKg: 0.5, pricePerKg: 400 }); // 200p
    const deli = resolveBarcodeValue(
      { sku: "HAM01", plu: 55, weightKg: 0.5 },
      TEMPLATES.deli,
      price,
    );
    expect(deli.type).toBe("ean13");
    expect(isValidEan13(deli.value)).toBe(true);
    // amount segment (positions 7..11) encodes the price in pence (00200)
    expect(deli.value.slice(7, 12)).toBe("00200");

    const bakery = resolveBarcodeValue({ sku: "LOAF", weightKg: 0.4 }, TEMPLATES.bakery, price);
    expect(bakery.type).toBe("code128");
    expect(bakery.value).toBe("LOAF-0400");
  });
});

describe("preview rendering (dry-run)", () => {
  it("produces a PNG label with a decodable barcode via bwip-js", async () => {
    const res = await labelPrinter.preview(
      {
        productName: "Sliced Honey Ham",
        sku: "HAM01",
        plu: 55,
        weightKg: 0.734,
        pricePerKg: 350,
        bestBefore: "2026-07-10",
        allergens: [{ name: "Milk" }, { name: "Nuts", mayContain: true }],
      },
      { departmentKey: "deli" },
    );
    expect(res.ok).toBe(true);
    created.push(res.outputPath, res.svgPath, res.manifestPath);

    const png = fs.readFileSync(res.outputPath);
    // PNG signature
    expect(png.subarray(0, 4).equals(Buffer.from([0x89, 0x50, 0x4e, 0x47]))).toBe(true);
    expect(png.length).toBeGreaterThan(50);

    // SVG contains the required fields
    const svg = fs.readFileSync(res.svgPath, "utf8");
    expect(svg).toContain("Sliced Honey Ham");
    expect(svg).toContain("£2.57");
    expect(svg).toContain("Best before: 2026-07-10");
    expect(res.template).toBe("deli");
    expect(isValidEan13(res.barcode.value)).toBe(true);
  });
});
