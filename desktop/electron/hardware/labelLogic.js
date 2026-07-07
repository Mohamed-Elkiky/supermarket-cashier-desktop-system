"use strict";

/**
 * Pure weigh-label computations: price maths, allergen summary, and the
 * price/weight-embedded barcode value builders. No native deps -> unit testable.
 */

function formatPence(pence) {
  const sign = pence < 0 ? "-" : "";
  return `${sign}£${(Math.abs(pence) / 100).toFixed(2)}`;
}

/**
 * Compute the label price (integer pence + display). Uses totalPrice if given,
 * else pricePerKg (pence/kg) * weightKg. All money is pence.
 */
function computeLabelPrice(payload) {
  if (payload.totalPrice != null) {
    const pence = Math.round(Number(payload.totalPrice));
    return { pence, display: formatPence(pence) };
  }
  const perKg = Number(payload.pricePerKg) || 0;
  const kg = Number(payload.weightKg) || 0;
  const pence = Math.round(perKg * kg);
  return { pence, display: formatPence(pence) };
}

/**
 * Build the allergen summary. Returns lists + a printable line. "May contain"
 * items are flagged separately (EU FIC requirement).
 */
function allergenSummary(allergens) {
  const list = Array.isArray(allergens) ? allergens : [];
  const contains = list.filter((a) => !a.mayContain).map((a) => a.name);
  const mayContain = list.filter((a) => a.mayContain).map((a) => a.name);
  const parts = [];
  if (contains.length) parts.push(`Contains: ${contains.join(", ")}`);
  if (mayContain.length) parts.push(`May contain: ${mayContain.join(", ")}`);
  return { contains, mayContain, line: parts.join("  |  ") };
}

/* ------------------------------ EAN-13 ---------------------------------- */

function ean13CheckDigit(twelve) {
  let sum = 0;
  for (let i = 0; i < 12; i++) {
    const d = twelve.charCodeAt(i) - 48;
    sum += i % 2 === 0 ? d : d * 3;
  }
  return (10 - (sum % 10)) % 10;
}

function padDigits(value, len) {
  const n = Math.abs(Math.trunc(Number(value) || 0));
  return String(n).padStart(len, "0").slice(-len);
}

/**
 * Build a price/weight-embedded EAN-13: prefix(2) + PLU(5) + amount(5) + check(1).
 * `amount` is price in pence or weight in grams depending on the template.
 */
function buildEan13({ prefix = "02", plu = 0, amount = 0 } = {}) {
  const p = String(prefix).replace(/\D/g, "").padStart(2, "0").slice(0, 2);
  const twelve = (p + padDigits(plu, 5) + padDigits(amount, 5)).slice(0, 12);
  return twelve + String(ean13CheckDigit(twelve));
}

/** Validate an EAN-13 string (13 digits + correct check digit). */
function isValidEan13(code) {
  if (!/^\d{13}$/.test(code)) return false;
  return ean13CheckDigit(code.slice(0, 12)) === code.charCodeAt(12) - 48;
}

/** Code128 value encoding SKU + weight in grams, e.g. "DELI-HAM-0734". */
function buildCode128Value(sku, weightKg) {
  const grams = Math.round((Number(weightKg) || 0) * 1000);
  return `${sku || "ITEM"}-${String(grams).padStart(4, "0")}`;
}

/** Choose the concrete barcode value for a payload + template + price. */
function resolveBarcodeValue(payload, template, priceInfo) {
  if (template.barcodeType === "ean13") {
    const amount =
      template.embed === "weight"
        ? Math.round((Number(payload.weightKg) || 0) * 1000)
        : priceInfo.pence;
    const plu = payload.plu != null ? payload.plu : deriveNumeric(payload.sku || payload.barcodeValue);
    return { type: "ean13", value: buildEan13({ prefix: template.ean13Prefix, plu, amount }) };
  }
  return { type: "code128", value: buildCode128Value(payload.sku || payload.barcodeValue, payload.weightKg) };
}

/** Derive a numeric PLU from a string (digits only, else a stable hash). */
function deriveNumeric(str) {
  const digits = String(str || "").replace(/\D/g, "");
  if (digits) return Number(digits.slice(0, 5));
  let hash = 0;
  for (const ch of String(str || "")) hash = (hash * 31 + ch.charCodeAt(0)) % 100000;
  return hash;
}

module.exports = {
  formatPence,
  computeLabelPrice,
  allergenSummary,
  ean13CheckDigit,
  buildEan13,
  isValidEan13,
  buildCode128Value,
  resolveBarcodeValue,
  deriveNumeric,
};
