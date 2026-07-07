"use strict";

/**
 * Pure ESC/POS receipt layout.
 *
 * This module has NO native dependencies so it is fully unit-testable. It turns
 * the backend receipt contract into a raw ESC/POS byte Buffer for either paper
 * width (58 mm = 32 cols, 80 mm = 48 cols). node-thermal-printer is used at the
 * transport layer (receiptPrinter.js) for real devices; the byte layout here is
 * hand-rolled so column maths and control codes are deterministic and testable.
 */

/* ------------------------------ ESC/POS bytes --------------------------- */

const ESC = 0x1b;
const GS = 0x1d;

const CMD = {
  INIT: Buffer.from([ESC, 0x40]), // ESC @ — initialise/reset
  LF: Buffer.from([0x0a]),
  ALIGN_LEFT: Buffer.from([ESC, 0x61, 0x00]),
  ALIGN_CENTER: Buffer.from([ESC, 0x61, 0x01]),
  ALIGN_RIGHT: Buffer.from([ESC, 0x61, 0x02]),
  BOLD_ON: Buffer.from([ESC, 0x45, 0x01]),
  BOLD_OFF: Buffer.from([ESC, 0x45, 0x00]),
  SIZE_NORMAL: Buffer.from([GS, 0x21, 0x00]), // GS ! 0
  SIZE_DBL: Buffer.from([GS, 0x21, 0x11]), // GS ! double width+height
  FEED_3: Buffer.from([ESC, 0x64, 0x03]), // ESC d 3 — feed 3 lines
  CUT: Buffer.from([GS, 0x56, 0x42, 0x00]), // GS V 66 0 — partial cut w/ feed
  DRAWER_KICK: Buffer.from([ESC, 0x70, 0x00, 0x19, 0xfa]), // ESC p 0 25 250
};

const WIDTHS = { 58: 32, 80: 48 };

/** Column count for a paper width (mm). Defaults to 80 mm / 48 cols. */
function charsForWidth(widthMm) {
  return WIDTHS[widthMm] || WIDTHS[80];
}

/* ------------------------------ text helpers ---------------------------- */

function toText(value) {
  return value === null || value === undefined ? "" : String(value);
}

/** Truncate to at most `width` characters. */
function truncate(text, width) {
  const s = toText(text);
  return s.length > width ? s.slice(0, width) : s;
}

/**
 * Left/right justified line, exactly `width` chars. The right value is kept
 * whole; the left is truncated if the two would collide.
 */
function formatLine(left, right, width) {
  const r = toText(right);
  const maxLeft = Math.max(0, width - r.length - 1);
  let l = toText(left);
  if (l.length > maxLeft) l = l.slice(0, maxLeft);
  const gap = width - l.length - r.length;
  return l + " ".repeat(Math.max(1, gap)) + r;
}

/** Center a string within `width` chars. */
function centerLine(text, width) {
  const s = truncate(text, width);
  const pad = Math.max(0, Math.floor((width - s.length) / 2));
  return " ".repeat(pad) + s;
}

/** A horizontal rule of dashes. */
function rule(width) {
  return "-".repeat(width);
}

function line(text) {
  return Buffer.concat([Buffer.from(toText(text), "ascii"), CMD.LF]);
}

/* ------------------------------ barcode --------------------------------- */

/**
 * ESC/POS Code128 barcode command for `data` (printer renders it natively).
 * GS h (height), GS w (module width), GS H (HRI below), then GS k 73 n data,
 * where data is prefixed with the Code128 code-set selector "{B".
 */
function code128Command(data) {
  const payload = Buffer.concat([
    Buffer.from([0x7b, 0x42]), // "{B" code set B
    Buffer.from(toText(data), "ascii"),
  ]);
  return Buffer.concat([
    Buffer.from([GS, 0x68, 0x50]), // GS h 80 — barcode height
    Buffer.from([GS, 0x77, 0x02]), // GS w 2  — module width
    Buffer.from([GS, 0x48, 0x02]), // GS H 2  — HRI text below barcode
    Buffer.from([GS, 0x6b, 0x49, payload.length]), // GS k 73 n
    payload,
  ]);
}

/* ------------------------------ builders -------------------------------- */

const STORE_NAME = "SUPERMARKET POS";

/** Build the full receipt as an ESC/POS byte Buffer. */
function buildReceiptBuffer(data, widthMm) {
  const width = charsForWidth(widthMm);
  const parts = [];
  const push = (buf) => parts.push(buf);

  push(CMD.INIT);

  // Header
  push(CMD.ALIGN_CENTER);
  push(CMD.BOLD_ON);
  push(CMD.SIZE_DBL);
  push(line(truncate(STORE_NAME, Math.floor(width / 2))));
  push(CMD.SIZE_NORMAL);
  push(CMD.BOLD_OFF);
  push(line("Sales Receipt"));
  push(CMD.ALIGN_LEFT);
  push(line(rule(width)));

  // Meta: date, cashier, receipt number
  push(line(formatLine("Receipt", toText(data.receipt_number), width)));
  push(line(formatLine("Date", formatDate(data.paid_at), width)));
  push(line(formatLine("Cashier", truncate(data.cashier, 20), width)));
  push(line(rule(width)));

  // Items
  const items = Array.isArray(data.items) ? data.items : [];
  for (const item of items) {
    push(line(truncate(item.name, width)));
    const qtyText =
      item.weight_kg != null
        ? `  ${formatWeight(item.weight_kg)}kg @ ${toText(item.unit_price_display)}`
        : `  ${toText(item.quantity)} @ ${toText(item.unit_price_display)}`;
    push(line(formatLine(qtyText, toText(item.line_total_display), width)));
    if (item.promotion_name) {
      push(line(truncate(`  * ${item.promotion_name}`, width)));
    }
    if (item.discount_display) {
      push(line(formatLine("  Discount", toText(item.discount_display), width)));
    }
  }
  push(line(rule(width)));

  // Totals
  push(line(formatLine("Subtotal", toText(data.subtotal_display), width)));
  if (data.discount_total_display && data.discount_total_display !== "-£0.00") {
    push(line(formatLine("Discounts", toText(data.discount_total_display), width)));
  }
  push(line(formatLine("Tax", toText(data.tax_total_display), width)));
  push(CMD.BOLD_ON);
  push(line(formatLine("TOTAL", toText(data.total_display), width)));
  push(CMD.BOLD_OFF);
  push(line(rule(width)));

  // Payment
  push(line(formatLine("Payment", paymentLabel(data.payment_method), width)));
  if (data.cash_tendered_display) {
    push(line(formatLine("Cash", toText(data.cash_tendered_display), width)));
  }
  if (data.change_display) {
    push(line(formatLine("Change", toText(data.change_display), width)));
  }
  if (data.loyalty_points_earned) {
    push(line(formatLine("Points earned", toText(data.loyalty_points_earned), width)));
  }
  if (data.age_verified) {
    push(line("Age verified: YES"));
  }

  // Barcode of the receipt number
  push(CMD.LF);
  push(CMD.ALIGN_CENTER);
  push(code128Command(data.receipt_number));
  push(CMD.LF);
  push(line(centerLine("Thank you for shopping!", width)));
  push(CMD.ALIGN_LEFT);

  // Feed + cut
  push(CMD.FEED_3);
  push(CMD.CUT);

  return Buffer.concat(parts);
}

/** A short self-test receipt used by printTest(). */
function buildTestBuffer(widthMm) {
  const width = charsForWidth(widthMm);
  const parts = [
    CMD.INIT,
    CMD.ALIGN_CENTER,
    CMD.BOLD_ON,
    line("PRINTER TEST"),
    CMD.BOLD_OFF,
    CMD.ALIGN_LEFT,
    line(rule(width)),
    line(formatLine("Paper width", `${widthMm}mm`, width)),
    line(formatLine("Columns", String(width), width)),
    line(formatLine("Status", "OK", width)),
    line(rule(width)),
    CMD.ALIGN_CENTER,
    code128Command("TEST-0000"),
    CMD.LF,
    CMD.ALIGN_LEFT,
    CMD.FEED_3,
    CMD.CUT,
  ];
  return Buffer.concat(parts);
}

/* ------------------------------ formatting ------------------------------ */

function formatWeight(kg) {
  const n = Number(kg);
  return Number.isFinite(n) ? n.toFixed(3) : "0.000";
}

function formatDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return toText(iso);
  const pad = (x) => String(x).padStart(2, "0");
  return `${pad(d.getDate())}/${pad(d.getMonth() + 1)}/${d.getFullYear()} ${pad(
    d.getHours(),
  )}:${pad(d.getMinutes())}`;
}

function paymentLabel(method) {
  switch (method) {
    case "cash":
      return "Cash";
    case "card":
      return "Card";
    case "loyalty_points":
      return "Loyalty points";
    case "mixed":
      return "Mixed";
    default:
      return toText(method);
  }
}

module.exports = {
  CMD,
  WIDTHS,
  charsForWidth,
  truncate,
  formatLine,
  centerLine,
  rule,
  code128Command,
  buildReceiptBuffer,
  buildTestBuffer,
  formatWeight,
  formatDate,
  paymentLabel,
};
