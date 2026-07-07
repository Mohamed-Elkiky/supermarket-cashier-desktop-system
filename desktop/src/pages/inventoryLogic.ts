/**
 * Pure inventory helpers: margin maths, CSV template/parse, and per-row import
 * validation that mirrors the backend rules. No React -> fully unit-testable.
 */

import Papa from "papaparse";

/* ------------------------------ margin ---------------------------------- */

/** Margin % = (sell - cost) / sell * 100, to 1 dp. Prefers a backend value. */
export function computeMarginPercent(
  sellPence: number,
  costPence: number,
  backend?: string | null,
): number {
  if (backend) {
    const n = parseFloat(String(backend).replace(/[^0-9.-]/g, ""));
    if (Number.isFinite(n)) return n;
  }
  if (!sellPence || sellPence <= 0) return 0;
  return Math.round(((sellPence - costPence) / sellPence) * 1000) / 10;
}

/* ------------------------------ CSV template ---------------------------- */

export const CSV_COLUMNS = [
  "department",
  "supplier",
  "name",
  "description",
  "is_age_restricted",
  "age_restriction_years",
  "sku",
  "barcode",
  "variant_name",
  "pricing_mode",
  "sell_price",
  "cost_price",
  "unit_of_measure",
  "low_stock_threshold",
  "track_expiry",
  "expiry_alert_days",
] as const;

/** A CSV template string (header + one example row). Money is in PENCE. */
export function csvTemplate(): string {
  const example = [
    "1", // department id
    "", // supplier id (optional)
    "Cheddar Cheese",
    "Mature cheddar block",
    "false",
    "",
    "CHE-400",
    "5012345678900",
    "Cheddar 400g",
    "fixed",
    "350", // sell_price pence
    "220", // cost_price pence
    "each",
    "6",
    "true",
    "14",
  ];
  return `${CSV_COLUMNS.join(",")}\n${example.join(",")}\n`;
}

/* ------------------------------ parsing --------------------------------- */

export type CsvRow = Record<string, string>;

export function parseCsv(text: string): CsvRow[] {
  const result = Papa.parse<CsvRow>(text, {
    header: true,
    skipEmptyLines: true,
    transformHeader: (h) => h.trim(),
  });
  return (result.data || []).filter((r) => Object.values(r).some((v) => String(v).trim() !== ""));
}

/* ------------------------------ validation ------------------------------ */

const WEIGHT_UNITS = new Set(["kg", "g"]);

export interface RowValidation {
  index: number;
  valid: boolean;
  errors: string[];
  raw: CsvRow;
  product?: Record<string, unknown>;
  variant?: Record<string, unknown>;
}

function parseBool(v: string | undefined): boolean {
  return ["true", "1", "yes", "y"].includes(String(v ?? "").trim().toLowerCase());
}

function parseIntOr(v: string | undefined): number | null {
  const s = String(v ?? "").trim();
  if (s === "") return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
}

/** Validate a single CSV row against the backend's product/variant rules. */
export function validateRow(raw: CsvRow, index = 0): RowValidation {
  const errors: string[] = [];
  const name = String(raw.name ?? "").trim();
  const sku = String(raw.sku ?? "").trim();
  const variantName = String(raw.variant_name ?? "").trim() || name;
  const pricingMode = String(raw.pricing_mode ?? "").trim();
  const unit = String(raw.unit_of_measure ?? "").trim().toLowerCase();
  const department = parseIntOr(raw.department);
  const sell = parseIntOr(raw.sell_price);
  const cost = parseIntOr(raw.cost_price);
  const isAgeRestricted = parseBool(raw.is_age_restricted);
  const ageYears = parseIntOr(raw.age_restriction_years);

  if (!name) errors.push("name is required");
  if (!sku) errors.push("sku is required");
  if (department == null) errors.push("department (id) is required");
  if (pricingMode !== "fixed" && pricingMode !== "weight_based") {
    errors.push('pricing_mode must be "fixed" or "weight_based"');
  }
  if (!unit) errors.push("unit_of_measure is required");
  else if (pricingMode === "weight_based" && !WEIGHT_UNITS.has(unit)) {
    errors.push("weight_based items must use unit kg or g");
  } else if (pricingMode === "fixed" && WEIGHT_UNITS.has(unit)) {
    errors.push("fixed items must not use unit kg or g");
  }
  if (sell == null) errors.push("sell_price must be a number (pence)");
  if (cost == null) errors.push("cost_price must be a number (pence)");
  if (sell != null && cost != null && sell < cost) {
    errors.push("sell_price must be >= cost_price");
  }
  if (isAgeRestricted && (ageYears == null || ageYears <= 0)) {
    errors.push("age_restriction_years is required when is_age_restricted is true");
  }

  const valid = errors.length === 0;
  return {
    index,
    valid,
    errors,
    raw,
    product: valid
      ? {
          department,
          supplier: parseIntOr(raw.supplier) ?? undefined,
          name,
          description: String(raw.description ?? "").trim() || undefined,
          is_age_restricted: isAgeRestricted,
          age_restriction_years: isAgeRestricted ? ageYears : null,
        }
      : undefined,
    variant: valid
      ? {
          sku,
          barcode: String(raw.barcode ?? "").trim() || undefined,
          name: variantName,
          pricing_mode: pricingMode,
          sell_price: sell,
          cost_price: cost,
          unit_of_measure: unit,
          low_stock_threshold: parseIntOr(raw.low_stock_threshold) ?? 0,
          track_expiry: parseBool(raw.track_expiry),
          expiry_alert_days: parseIntOr(raw.expiry_alert_days) ?? 0,
        }
      : undefined,
  };
}

export function validateRows(rows: CsvRow[]): RowValidation[] {
  return rows.map((r, i) => validateRow(r, i));
}

/** Build a downloadable error-report CSV for failed rows. */
export function buildErrorReportCsv(failed: Array<{ raw: CsvRow; errors: string[] }>): string {
  const header = [...CSV_COLUMNS, "errors"];
  const lines = [header.join(",")];
  for (const f of failed) {
    const cells = CSV_COLUMNS.map((c) => csvCell(f.raw[c] ?? ""));
    cells.push(csvCell(f.errors.join("; ")));
    lines.push(cells.join(","));
  }
  return lines.join("\n");
}

function csvCell(value: string): string {
  const s = String(value ?? "");
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}
