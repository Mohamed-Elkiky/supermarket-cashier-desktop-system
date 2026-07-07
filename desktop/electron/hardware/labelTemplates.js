"use strict";

/**
 * Per-department weigh-label templates.
 *
 * A template controls the physical size, the field order printed on the label,
 * the barcode symbology, and whether allergens are shown. Selecting a department
 * picks its template; anything unknown falls back to the default.
 *
 * Templates can be chosen by a string key (departmentKey, e.g. "deli") or by a
 * numeric departmentId mapped via POS_LABEL_TEMPLATE_MAP (JSON: {"<id>":"deli"}).
 */

const DEFAULT_TEMPLATE = Object.freeze({
  key: "default",
  widthMm: 50,
  heightMm: 30,
  fields: ["productName", "weight", "price", "bestBefore", "allergens", "barcode"],
  barcodeType: "code128",
  showAllergens: true,
  embed: "price", // for EAN-13 templates: embed "price" or "weight"
  ean13Prefix: "02",
});

const TEMPLATES = Object.freeze({
  deli: {
    key: "deli",
    widthMm: 60,
    heightMm: 40,
    fields: ["productName", "weight", "price", "allergens", "bestBefore", "barcode"],
    barcodeType: "ean13",
    showAllergens: true,
    embed: "price",
    ean13Prefix: "02",
  },
  bakery: {
    key: "bakery",
    widthMm: 50,
    heightMm: 30,
    fields: ["productName", "price", "bestBefore", "allergens", "barcode"],
    barcodeType: "code128",
    showAllergens: true,
    embed: "price",
    ean13Prefix: "02",
  },
  produce: {
    key: "produce",
    widthMm: 40,
    heightMm: 25,
    fields: ["productName", "weight", "price", "barcode"],
    barcodeType: "ean13",
    showAllergens: false,
    embed: "weight",
    ean13Prefix: "21",
  },
  default: DEFAULT_TEMPLATE,
});

function parseIdMap() {
  const raw = process.env.POS_LABEL_TEMPLATE_MAP;
  if (!raw) return {};
  try {
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

/** Resolve a template from { departmentKey?, departmentId? }. */
function getTemplate(opts = {}) {
  if (opts.departmentKey && TEMPLATES[opts.departmentKey]) {
    return TEMPLATES[opts.departmentKey];
  }
  if (opts.departmentId != null) {
    const key = parseIdMap()[String(opts.departmentId)];
    if (key && TEMPLATES[key]) return TEMPLATES[key];
  }
  return TEMPLATES.default;
}

module.exports = { TEMPLATES, DEFAULT_TEMPLATE, getTemplate };
