import { describe, it, expect } from "vitest";
import {
  computeMarginPercent,
  parseCsv,
  validateRow,
  validateRows,
  csvTemplate,
  buildErrorReportCsv,
  CSV_COLUMNS,
  type CsvRow,
} from "../inventoryLogic";

function row(over: Partial<CsvRow> = {}): CsvRow {
  return {
    department: "1",
    supplier: "",
    name: "Cheddar",
    description: "",
    is_age_restricted: "false",
    age_restriction_years: "",
    sku: "CHE-400",
    barcode: "",
    variant_name: "Cheddar 400g",
    pricing_mode: "fixed",
    sell_price: "350",
    cost_price: "220",
    unit_of_measure: "each",
    low_stock_threshold: "6",
    track_expiry: "true",
    expiry_alert_days: "14",
    ...over,
  };
}

describe("margin", () => {
  it("computes (sell-cost)/sell*100 to 1dp", () => {
    expect(computeMarginPercent(350, 220)).toBe(37.1);
    expect(computeMarginPercent(100, 100)).toBe(0);
  });
  it("prefers a backend margin string", () => {
    expect(computeMarginPercent(350, 220, "40.0%")).toBe(40);
  });
  it("guards divide-by-zero", () => {
    expect(computeMarginPercent(0, 0)).toBe(0);
  });
});

describe("CSV parsing", () => {
  it("parses headered CSV into row objects", () => {
    const rows = parseCsv(csvTemplate());
    expect(rows).toHaveLength(1);
    expect(rows[0].name).toBe("Cheddar Cheese");
    expect(rows[0].pricing_mode).toBe("fixed");
  });
  it("skips blank lines", () => {
    const csv = `name,sku\nMilk,MLK\n\n , \nBread,BRD\n`;
    expect(parseCsv(csv)).toHaveLength(2);
  });
  it("template header has every column", () => {
    expect(csvTemplate().split("\n")[0].split(",")).toEqual([...CSV_COLUMNS]);
  });
});

describe("row validation", () => {
  it("accepts a valid fixed-price row", () => {
    const r = validateRow(row());
    expect(r.valid).toBe(true);
    expect(r.errors).toEqual([]);
    expect(r.product?.name).toBe("Cheddar");
    expect(r.variant?.sell_price).toBe(350);
  });

  it("accepts a valid weight-based row with kg", () => {
    const r = validateRow(row({ pricing_mode: "weight_based", unit_of_measure: "kg" }));
    expect(r.valid).toBe(true);
  });

  it("rejects weight_based with a non-weight unit", () => {
    const r = validateRow(row({ pricing_mode: "weight_based", unit_of_measure: "each" }));
    expect(r.valid).toBe(false);
    expect(r.errors.join()).toContain("weight_based items must use unit kg or g");
  });

  it("rejects fixed with a weight unit", () => {
    const r = validateRow(row({ pricing_mode: "fixed", unit_of_measure: "kg" }));
    expect(r.errors.join()).toContain("fixed items must not use unit kg or g");
  });

  it("rejects sell_price < cost_price", () => {
    const r = validateRow(row({ sell_price: "100", cost_price: "200" }));
    expect(r.errors.join()).toContain("sell_price must be >= cost_price");
  });

  it("requires age_restriction_years when age restricted", () => {
    const r = validateRow(row({ is_age_restricted: "true", age_restriction_years: "" }));
    expect(r.errors.join()).toContain("age_restriction_years is required");
    const ok = validateRow(row({ is_age_restricted: "true", age_restriction_years: "18" }));
    expect(ok.valid).toBe(true);
    expect(ok.product?.age_restriction_years).toBe(18);
  });

  it("rejects rows missing required fields", () => {
    const r = validateRow(row({ name: "", sku: "" }));
    expect(r.errors).toContain("name is required");
    expect(r.errors).toContain("sku is required");
  });
});

describe("error report", () => {
  it("appends an errors column for failed rows", () => {
    const results = validateRows([row(), row({ name: "", pricing_mode: "bad" })]);
    const failed = results.filter((r) => !r.valid).map((r) => ({ raw: r.raw, errors: r.errors }));
    const csv = buildErrorReportCsv(failed);
    expect(csv.split("\n")[0].endsWith(",errors")).toBe(true);
    expect(csv).toContain("name is required");
  });
});
