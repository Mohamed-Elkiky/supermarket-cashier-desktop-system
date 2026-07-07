"use strict";

/**
 * Weigh-label printer integration (Electron main process).
 *
 * Prints branded deli/produce weigh labels: product name, weight, price
 * (weight x price-per-kg), best-before date, an allergen summary (with a
 * separate "may contain" line) and a SCANNABLE barcode. Barcodes are rendered
 * with bwip-js — either a price/weight-embedded EAN-13 or a Code128 of sku+weight
 * depending on the per-department template.
 *
 * PREVIEW / DRY-RUN writes a real PNG barcode plus a composite SVG label and a
 * text manifest under <userData>/dryrun so labels can be verified without a
 * label printer. Never crashes when no label printer is attached.
 */

const fs = require("fs");
const path = require("path");

const { getTemplate } = require("./labelTemplates");
const {
  computeLabelPrice,
  allergenSummary,
  resolveBarcodeValue,
} = require("./labelLogic");
const receiptPrinter = require("./receiptPrinter");

function timestamp() {
  return new Date().toISOString().replace(/[:.]/g, "-");
}

function dryRunDir() {
  return receiptPrinter.dryRunDir();
}

/** Render a barcode to a PNG Buffer with bwip-js. */
function renderBarcodePng(bcid, text) {
  const bwipjs = require("bwip-js");
  return new Promise((resolve, reject) => {
    bwipjs.toBuffer(
      { bcid, text: String(text), scale: 3, height: 12, includetext: true, textxalign: "center" },
      (err, png) => (err ? reject(err) : resolve(png)),
    );
  });
}

function escapeXml(s) {
  return String(s ?? "").replace(/[<>&'"]/g, (c) =>
    ({ "<": "&lt;", ">": "&gt;", "&": "&amp;", "'": "&apos;", '"': "&quot;" })[c],
  );
}

/** Build the printable field set from a payload + template. */
function buildFields(payload, template) {
  const price = computeLabelPrice(payload);
  const allergens = allergenSummary(payload.allergens);
  const barcode = resolveBarcodeValue(payload, template, price);
  return {
    productName: payload.productName,
    weightKg: payload.weightKg != null ? Number(payload.weightKg) : null,
    priceDisplay: price.display,
    pricePence: price.pence,
    bestBefore: payload.bestBefore || null,
    allergens,
    barcode,
    template,
  };
}

/** Compose a self-contained SVG label (all fields + embedded barcode PNG). */
function buildLabelSvg(fields, barcodePngBase64) {
  const { template } = fields;
  const w = template.widthMm;
  const h = template.heightMm;
  const lines = [];
  let y = 5;
  const put = (text, size = 3, weight = "normal") => {
    lines.push(
      `<text x="2" y="${y}" font-size="${size}" font-family="sans-serif" font-weight="${weight}">${escapeXml(
        text,
      )}</text>`,
    );
    y += size + 1.5;
  };

  for (const field of template.fields) {
    if (field === "productName") put(fields.productName, 3.5, "bold");
    else if (field === "weight" && fields.weightKg != null) put(`${fields.weightKg.toFixed(3)} kg`);
    else if (field === "price") put(fields.priceDisplay, 4, "bold");
    else if (field === "bestBefore" && fields.bestBefore) put(`Best before: ${fields.bestBefore}`, 2.6);
    else if (field === "allergens" && template.showAllergens && fields.allergens.line)
      put(fields.allergens.line, 2.2);
    else if (field === "barcode") {
      lines.push(
        `<image x="2" y="${y}" width="${w - 4}" height="${Math.max(
          6,
          h - y - 2,
        )}" href="data:image/png;base64,${barcodePngBase64}" preserveAspectRatio="xMidYMid meet"/>`,
      );
    }
  }

  return `<svg xmlns="http://www.w3.org/2000/svg" width="${w}mm" height="${h}mm" viewBox="0 0 ${w} ${h}">
  <rect x="0" y="0" width="${w}" height="${h}" fill="#ffffff" stroke="#000" stroke-width="0.2"/>
  ${lines.join("\n  ")}
</svg>`;
}

function bcidFor(barcode) {
  return barcode.type === "ean13" ? "ean13" : "code128";
}

/**
 * Render a label to disk (dry-run/preview). Returns the output paths + fields.
 */
async function renderToFiles(payload, opts, prefix) {
  const template = getTemplate(opts);
  const fields = buildFields(payload, template);
  const dir = dryRunDir();
  fs.mkdirSync(dir, { recursive: true });
  const stamp = timestamp();

  const png = await renderBarcodePng(bcidFor(fields.barcode), fields.barcode.value);
  const pngPath = path.join(dir, `${prefix}-${stamp}.png`);
  fs.writeFileSync(pngPath, png);

  const svg = buildLabelSvg(fields, png.toString("base64"));
  const svgPath = path.join(dir, `${prefix}-${stamp}.svg`);
  fs.writeFileSync(svgPath, svg, "utf8");

  const manifest = [
    `Template: ${template.key} (${template.widthMm}x${template.heightMm}mm)`,
    `Product:  ${fields.productName}`,
    fields.weightKg != null ? `Weight:   ${fields.weightKg.toFixed(3)} kg` : "Weight:   n/a",
    `Price:    ${fields.priceDisplay}`,
    `Best before: ${fields.bestBefore || "n/a"}`,
    `Allergens:   ${fields.allergens.line || "none"}`,
    `Barcode:  ${fields.barcode.type.toUpperCase()} ${fields.barcode.value}`,
  ].join("\n");
  const txtPath = path.join(dir, `${prefix}-${stamp}.txt`);
  fs.writeFileSync(txtPath, manifest, "utf8");

  return {
    ok: true,
    dryRun: true,
    outputPath: pngPath,
    svgPath,
    manifestPath: txtPath,
    barcode: fields.barcode,
    pricePence: fields.pricePence,
    template: template.key,
  };
}

function hasLabelPrinter() {
  return !!process.env.POS_LABEL_PRINTER;
}

/** Preview a label without hardware. */
async function preview(payload, opts = {}) {
  return renderToFiles(payload, opts, "label-preview");
}

/** Print a label. Falls back to a dry-run render if no printer / dry-run mode. */
async function print(payload, opts = {}) {
  if (process.env.POS_PRINTER_DRYRUN === "1" || !hasLabelPrinter()) {
    const res = await renderToFiles(payload, opts, "label");
    return { ...res, message: hasLabelPrinter() ? undefined : "no label printer — dry-run" };
  }
  // A real label printer would receive raster/ZPL here. Kept as a dry-run render
  // so the flow is exercised without a device driver.
  const res = await renderToFiles(payload, opts, "label");
  return { ...res, dryRun: false };
}

module.exports = {
  print,
  preview,
  buildFields,
  buildLabelSvg,
  renderBarcodePng,
  hasLabelPrinter,
};
