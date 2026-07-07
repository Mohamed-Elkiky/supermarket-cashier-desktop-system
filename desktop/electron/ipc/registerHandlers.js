"use strict";

/**
 * Centralised IPC handler registry.
 *
 * Every ipcMain.handle in the app lives here, keyed off the frozen channel
 * allow-list in channels.js. Each handler validates its payload at the top and
 * rejects anything unexpected. There is no ipcMain.on scattered across the code
 * base and no dynamically-named channel.
 *
 * Feature modules (printer, scale, drawer, db, label, staff, notifier) are
 * lazy-required so a module that is not installed / not yet built (or a native
 * dependency that failed to load) degrades to a clear error for that one channel
 * instead of crashing app start-up.
 */

const { ipcMain, app } = require("electron");
const { CHANNELS, INVOKE_CHANNELS } = require("./channels");

/** Require a feature module, returning null if it cannot be loaded. */
function safeRequire(modulePath) {
  try {
    return require(modulePath);
  } catch (err) {
    console.warn(
      `[ipc] feature module ${modulePath} unavailable:`,
      err && err.message ? err.message : err,
    );
    return null;
  }
}

function requireModule(modulePath, featureName) {
  const mod = safeRequire(modulePath);
  if (!mod) {
    throw new Error(`${featureName} is not available in this environment`);
  }
  return mod;
}

/* ------------------------------ validation ------------------------------ */

function assert(condition, message) {
  if (!condition) {
    throw new Error(`Invalid IPC payload: ${message}`);
  }
}

function asObject(payload) {
  return payload && typeof payload === "object" ? payload : {};
}

function assertString(value, name) {
  assert(typeof value === "string" && value.length > 0, `${name} must be a non-empty string`);
  return value;
}

/* ------------------------------ registration ---------------------------- */

let registered = false;
const handledChannels = new Set();

/**
 * Register a single ipcMain.handle for an allow-listed channel. Rejects any
 * attempt to register a channel that is not on the invoke allow-list, and
 * records coverage so we can detect drift.
 */
function handle(channel, fn) {
  if (!INVOKE_CHANNELS.includes(channel)) {
    throw new Error(`Refusing to register non-allow-listed channel: ${channel}`);
  }
  handledChannels.add(channel);
  ipcMain.handle(channel, fn);
}

function registerHandlers() {
  if (registered) return;
  registered = true;

  // --- App / meta ---------------------------------------------------------
  handle(CHANNELS.APP_GET_VERSION, () => app.getVersion());
  handle(CHANNELS.APP_GET_PLATFORM, () => process.platform);

  // --- Receipt printer (Task 4) ------------------------------------------
  handle(CHANNELS.PRINTER_LIST, () => {
    const printer = requireModule("../hardware/receiptPrinter", "Receipt printer");
    return printer.list();
  });
  handle(CHANNELS.PRINTER_PRINT_RECEIPT, (_e, payload) => {
    const { data, opts } = asObject(payload);
    assert(data && typeof data === "object", "receipt data is required");
    const printer = requireModule("../hardware/receiptPrinter", "Receipt printer");
    return printer.printReceipt(data, asObject(opts));
  });
  handle(CHANNELS.PRINTER_PRINT_TEST, (_e, payload) => {
    const { opts } = asObject(payload);
    const printer = requireModule("../hardware/receiptPrinter", "Receipt printer");
    return printer.printTest(asObject(opts));
  });

  // --- Weighing scale (Task 6) -------------------------------------------
  handle(CHANNELS.SCALE_LIST_PORTS, () => {
    const scale = requireModule("../hardware/scale", "Weighing scale");
    return scale.listPorts();
  });
  handle(CHANNELS.SCALE_CONNECT, (_e, payload) => {
    const { config } = asObject(payload);
    const scale = requireModule("../hardware/scale", "Weighing scale");
    return scale.connect(asObject(config));
  });
  handle(CHANNELS.SCALE_DISCONNECT, () => {
    const scale = requireModule("../hardware/scale", "Weighing scale");
    return scale.disconnect();
  });

  // --- Cash drawer (Task 7) ----------------------------------------------
  handle(CHANNELS.DRAWER_OPEN, (_e, payload) => {
    const { opts } = asObject(payload);
    const drawer = requireModule("../hardware/cashDrawer", "Cash drawer");
    return drawer.open(asObject(opts));
  });
  handle(CHANNELS.DRAWER_OPEN_TEST, (_e, payload) => {
    const { opts } = asObject(payload);
    const drawer = requireModule("../hardware/cashDrawer", "Cash drawer");
    return drawer.openTest(asObject(opts));
  });

  // --- Encrypted local DB (Task 3 / offline Task 12) ---------------------
  handle(CHANNELS.DB_GET_META, (_e, payload) => {
    const { key } = asObject(payload);
    assertString(key, "key");
    const db = requireModule("../db/database", "Local database");
    return db.getMeta(key);
  });
  handle(CHANNELS.DB_SET_META, (_e, payload) => {
    const { key, value } = asObject(payload);
    assertString(key, "key");
    assert(typeof value === "string", "value must be a string");
    const db = requireModule("../db/database", "Local database");
    return db.setMeta(key, value);
  });
  handle(CHANNELS.DB_GET_CACHED_PRODUCTS, (_e, payload) => {
    const { departmentId } = asObject(payload);
    const db = requireModule("../db/database", "Local database");
    return db.getCachedProducts(departmentId);
  });
  handle(CHANNELS.DB_GET_CACHED_PROMOTIONS, () => {
    const db = requireModule("../db/database", "Local database");
    return db.getCachedPromotions();
  });
  handle(CHANNELS.DB_REFRESH_CACHE, () => {
    const sync = requireModule("../sync/syncWorker", "Background sync");
    return sync.refreshCache();
  });
  handle(CHANNELS.DB_ENQUEUE_TRANSACTION, (_e, payload) => {
    const { payload: txPayload } = asObject(payload);
    assert(txPayload && typeof txPayload === "object", "transaction payload required");
    const db = requireModule("../db/database", "Local database");
    return db.enqueueTransaction(txPayload);
  });
  handle(CHANNELS.DB_GET_QUEUE_STATUS, () => {
    const sync = safeRequire("../sync/syncWorker");
    if (sync) return sync.getStatus();
    const db = requireModule("../db/database", "Local database");
    return db.getQueueStatus();
  });
  handle(CHANNELS.DB_SET_SYNC_TOKEN, (_e, payload) => {
    const { token } = asObject(payload);
    const sync = requireModule("../sync/syncWorker", "Background sync");
    sync.setAuthToken(typeof token === "string" ? token : null);
    return { ok: true };
  });

  // --- Weigh-label printer (Task 9) --------------------------------------
  handle(CHANNELS.LABEL_PRINT, (_e, payload) => {
    const { payload: labelPayload, opts } = asObject(payload);
    assert(labelPayload && typeof labelPayload === "object", "label payload required");
    const label = requireModule("../hardware/labelPrinter", "Label printer");
    return label.print(labelPayload, asObject(opts));
  });
  handle(CHANNELS.LABEL_PREVIEW, (_e, payload) => {
    const { payload: labelPayload, opts } = asObject(payload);
    assert(labelPayload && typeof labelPayload === "object", "label payload required");
    const label = requireModule("../hardware/labelPrinter", "Label printer");
    return label.preview(labelPayload, asObject(opts));
  });

  // --- Staff clock (Task 13) ---------------------------------------------
  handle(CHANNELS.STAFF_CLOCK_IN, () => {
    const staff = requireModule("../staff/clock", "Staff clock");
    return staff.clockIn();
  });
  handle(CHANNELS.STAFF_CLOCK_OUT, () => {
    const staff = requireModule("../staff/clock", "Staff clock");
    return staff.clockOut();
  });
  handle(CHANNELS.STAFF_GET_STATUS, () => {
    const staff = requireModule("../staff/clock", "Staff clock");
    return staff.getStatus();
  });

  // --- Toast notifications (Task 15) -------------------------------------
  handle(CHANNELS.NOTIFY_TEST, (_e, payload) => {
    const { category } = asObject(payload);
    assertString(category, "category");
    const notifier = requireModule("../notifications/notifier", "Notifications");
    return notifier.test(category);
  });

  // Safety net: make sure we did not forget to wire a channel from the
  // allow-list (helps catch drift during development).
  for (const channel of INVOKE_CHANNELS) {
    if (!handledChannels.has(channel)) {
      console.warn(`[ipc] WARNING: allow-listed channel not handled: ${channel}`);
    }
  }
}

module.exports = { registerHandlers };
