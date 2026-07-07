"use strict";

/**
 * Cash drawer trigger (Electron main process).
 *
 * The drawer is wired to the receipt printer's RJ11 kick port, so "open drawer"
 * is an ESC/POS pulse sent THROUGH the printer on the SAME connection. We reuse
 * receiptPrinter.sendRaw() so the pulse goes to the same device — and, in
 * dry-run, is appended to the same receipt .bin file.
 *
 * Business rule: the drawer only opens after a confirmed CASH payment (and a
 * mixed payment only when some cash was tendered). Card / loyalty never open it.
 */

const receiptPrinter = require("./receiptPrinter");

const ESC = 0x1b;

/** Default drawer-open policy (small, overridable config). */
const DEFAULT_DRAWER_CONFIG = Object.freeze({
  openOnCash: true,
  openOnMixedWithCash: true,
});

function clampByte(n, fallback) {
  const v = Number.isFinite(n) ? Math.round(n) : fallback;
  return Math.max(0, Math.min(255, v));
}

/**
 * ESC/POS drawer kick: ESC p m t1 t2.
 * Defaults produce the standard pulse 0x1B 0x70 0x00 0x19 0xFA
 * (pin 2, on=25, off=250). t1/t2 (on/off durations) are configurable.
 */
function drawerPulseBytes(opts = {}) {
  const m = opts.pin === 5 ? 0x01 : 0x00; // pin 2 -> m=0, pin 5 -> m=1
  const t1 = clampByte(opts.onTime, 0x19);
  const t2 = clampByte(opts.offTime, 0xfa);
  return Buffer.from([ESC, 0x70, m, t1, t2]);
}

/**
 * Decide whether a completed payment should pop the drawer.
 * @param {{payment_method:string, cash_tendered_pence?:number}} payment
 */
function shouldOpenDrawer(payment, config = DEFAULT_DRAWER_CONFIG) {
  if (!payment) return false;
  const method = payment.payment_method;
  const cash = Number(payment.cash_tendered_pence) || 0;
  if (method === "cash") return !!config.openOnCash;
  if (method === "mixed") return !!config.openOnMixedWithCash && cash > 0;
  return false; // card, loyalty_points, etc.
}

/** Send the drawer pulse (reusing the printer connection / dry-run file). */
async function open(opts = {}) {
  const bytes = drawerPulseBytes(opts);
  const result = await receiptPrinter.sendRaw(bytes, {
    printerId: opts.printerId,
    dryRunPrefix: "drawer",
    appendToLast: true,
  });
  return { ...result, opened: result.ok !== false };
}

/** Manual test trigger. */
async function openTest(opts = {}) {
  const bytes = drawerPulseBytes(opts);
  const result = await receiptPrinter.sendRaw(bytes, {
    printerId: opts.printerId,
    dryRunPrefix: "drawer-test",
    appendToLast: false,
  });
  return { ...result, opened: result.ok !== false };
}

/**
 * Checkout-flow hook: call AFTER printReceipt. Opens the drawer only for cash
 * (and mixed-with-cash) payments. Returns { opened:false } when the payment
 * method does not open the drawer.
 */
async function openAfterPayment(payment, opts = {}) {
  if (!shouldOpenDrawer(payment, opts.config)) {
    return { ok: true, opened: false, dryRun: false, message: "payment method does not open drawer" };
  }
  return open({ printerId: opts.printerId, ...opts });
}

module.exports = {
  DEFAULT_DRAWER_CONFIG,
  drawerPulseBytes,
  shouldOpenDrawer,
  open,
  openTest,
  openAfterPayment,
};
