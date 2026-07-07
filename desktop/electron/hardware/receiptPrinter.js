"use strict";

/**
 * ESC/POS receipt printer integration (Electron main process).
 *
 * - Auto-detects USB ESC/POS printers (via the `usb` package) and any network
 *   printers configured through POS_NETWORK_PRINTERS.
 * - Prints receipts at 58 mm (32 col) or 80 mm (48 col) using the pure layout
 *   in receiptLayout.js.
 * - DRY-RUN mode (POS_PRINTER_DRYRUN=1 or no printer attached) writes the raw
 *   ESC/POS byte buffer to <userData>/dryrun/receipt-<ts>.bin so receipts can be
 *   inspected without hardware. The cash-drawer module (Task 7) reuses sendRaw()
 *   so its pulse lands on the same connection / same dry-run file.
 *
 * Native modules are lazy-required; everything degrades gracefully with no
 * hardware present.
 */

const fs = require("fs");
const os = require("os");
const path = require("path");

const layout = require("./receiptLayout");

// Known ESC/POS printer USB vendor IDs (heuristic for discovery).
const KNOWN_PRINTER_VENDORS = new Set([
  0x04b8, // Epson
  0x0519, // Star Micronics
  0x0416, // Winbond (many generic 58mm)
  0x0dd4, // Custom / Bixolon
  0x1504, // Bixolon
  0x0483, // STMicro (generic clones)
  0x6868, // Zjiang / generic
]);

const PRINTER_USB_CLASS = 7; // USB printer class

let lastDryRunPath = null;

/* ------------------------------ helpers --------------------------------- */

function dryRunDir() {
  let base;
  try {
    const { app } = require("electron");
    base = app && app.getPath ? app.getPath("userData") : os.tmpdir();
  } catch {
    base = os.tmpdir();
  }
  return path.join(base, "dryrun");
}

function timestamp() {
  return new Date().toISOString().replace(/[:.]/g, "-");
}

function writeDryRunFile(buffer, prefix) {
  const dir = dryRunDir();
  fs.mkdirSync(dir, { recursive: true });
  const p = path.join(dir, `${prefix}-${timestamp()}.bin`);
  fs.writeFileSync(p, buffer);
  lastDryRunPath = p;
  return p;
}

function appendDryRunFile(buffer) {
  if (lastDryRunPath && fs.existsSync(lastDryRunPath)) {
    fs.appendFileSync(lastDryRunPath, buffer);
    return lastDryRunPath;
  }
  return writeDryRunFile(buffer, "drawer");
}

function getLastDryRunPath() {
  return lastDryRunPath;
}

/* ------------------------------ discovery ------------------------------- */

function listNetworkPrinters() {
  const raw = process.env.POS_NETWORK_PRINTERS;
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.map((p, i) => ({
      id: p.id || `net-${i}`,
      name: p.name || `${p.host}:${p.port || 9100}`,
      interface: "network",
      host: p.host,
      port: p.port || 9100,
      widthMm: p.widthMm === 58 ? 58 : 80,
    }));
  } catch {
    return [];
  }
}

function listUsbPrinters() {
  let usb;
  try {
    usb = require("usb");
  } catch {
    return [];
  }
  let devices;
  try {
    devices = usb.getDeviceList ? usb.getDeviceList() : [];
  } catch {
    return [];
  }
  const results = [];
  for (const d of devices) {
    const desc = d.deviceDescriptor || {};
    const isPrinter =
      desc.bDeviceClass === PRINTER_USB_CLASS || KNOWN_PRINTER_VENDORS.has(desc.idVendor);
    if (!isPrinter) continue;
    const vid = (desc.idVendor || 0).toString(16).padStart(4, "0");
    const pid = (desc.idProduct || 0).toString(16).padStart(4, "0");
    results.push({
      id: `usb-${vid}-${pid}`,
      name: `USB printer ${vid}:${pid}`,
      interface: "usb",
      vendorId: desc.idVendor,
      productId: desc.idProduct,
      widthMm: 80, // width is not discoverable from USB; default 80mm
      _device: d,
    });
  }
  return results;
}

/** Public: enumerate all printers. Never throws; returns [] when none found. */
function list() {
  try {
    const printers = [...listUsbPrinters(), ...listNetworkPrinters()];
    // Strip internal handles from the public shape.
    return printers.map(({ id, name, interface: iface, widthMm }) => ({
      id,
      name,
      interface: iface,
      widthMm,
    }));
  } catch {
    return [];
  }
}

function resolvePrinter(opts) {
  const printers = [...listUsbPrinters(), ...listNetworkPrinters()];
  if (printers.length === 0) return null;
  if (opts && opts.printerId) {
    return printers.find((p) => p.id === opts.printerId) || null;
  }
  return printers[0];
}

/* ------------------------------ transmit -------------------------------- */

function isDryRun(opts) {
  if (process.env.POS_PRINTER_DRYRUN === "1") return true;
  return resolvePrinter(opts) === null;
}

async function sendToDevice(buffer, printer) {
  if (!printer) throw new Error("No printer resolved");
  if (printer.interface === "network") {
    await sendToNetwork(buffer, printer.host, printer.port);
    return;
  }
  await sendToUsb(buffer, printer);
}

function sendToNetwork(buffer, host, port) {
  const net = require("net");
  return new Promise((resolve, reject) => {
    const socket = net.connect({ host, port }, () => {
      socket.write(buffer, () => socket.end());
    });
    socket.on("error", reject);
    socket.on("close", () => resolve());
  });
}

async function sendToUsb(buffer, printer) {
  const usb = require("usb");
  const device = printer._device || null;
  if (!device) throw new Error("USB device handle unavailable");
  device.open();
  try {
    const iface = device.interfaces[0];
    if (iface.isKernelDriverActive && iface.isKernelDriverActive()) {
      iface.detachKernelDriver();
    }
    iface.claim();
    const outEndpoint = iface.endpoints.find((e) => e.direction === "out");
    if (!outEndpoint) throw new Error("No OUT endpoint on USB printer");
    await new Promise((resolve, reject) => {
      outEndpoint.transfer(buffer, (err) => (err ? reject(err) : resolve()));
    });
    await new Promise((resolve) => iface.release(true, () => resolve()));
  } finally {
    try {
      device.close();
    } catch {
      /* ignore */
    }
  }
  void usb;
}

/**
 * Core dispatch used by printReceipt/printTest and the cash drawer.
 * @param {Buffer} buffer raw ESC/POS bytes
 * @param {object} opts { printerId?, dryRunPrefix?, appendToLast? }
 */
async function sendRaw(buffer, opts = {}) {
  if (isDryRun(opts)) {
    const outputPath = opts.appendToLast
      ? appendDryRunFile(buffer)
      : writeDryRunFile(buffer, opts.dryRunPrefix || "raw");
    return { ok: true, dryRun: true, outputPath, bytes: buffer.length };
  }
  const printer = resolvePrinter(opts);
  try {
    await sendToDevice(buffer, printer);
    return { ok: true, dryRun: false, bytes: buffer.length };
  } catch (err) {
    // Fall back to a dry-run capture so a sale is never lost to a printer fault.
    const outputPath = writeDryRunFile(buffer, opts.dryRunPrefix || "raw");
    return {
      ok: false,
      dryRun: true,
      outputPath,
      message: err && err.message ? err.message : String(err),
    };
  }
}

/* ------------------------------ public API ------------------------------ */

function resolveWidth(opts, printer) {
  if (opts && (opts.widthMm === 58 || opts.widthMm === 80)) return opts.widthMm;
  if (printer && printer.widthMm) return printer.widthMm;
  return 80;
}

async function printReceipt(data, opts = {}) {
  const printer = resolvePrinter(opts);
  const widthMm = resolveWidth(opts, printer);
  const buffer = layout.buildReceiptBuffer(data, widthMm);
  return sendRaw(buffer, { ...opts, dryRunPrefix: "receipt" });
}

async function printTest(opts = {}) {
  const printer = resolvePrinter(opts);
  const widthMm = resolveWidth(opts, printer);
  const buffer = layout.buildTestBuffer(widthMm);
  return sendRaw(buffer, { ...opts, dryRunPrefix: "receipt-test" });
}

/** Optional startup auto-detect: logs discovered printers. */
function init() {
  const printers = list();
  if (printers.length === 0) {
    console.log("[printer] no ESC/POS printers detected (dry-run available)");
  } else {
    console.log(`[printer] detected ${printers.length} printer(s):`, printers.map((p) => p.id).join(", "));
  }
  return printers;
}

module.exports = {
  init,
  list,
  printReceipt,
  printTest,
  sendRaw,
  resolvePrinter,
  resolveWidth,
  isDryRun,
  getLastDryRunPath,
  dryRunDir,
};
