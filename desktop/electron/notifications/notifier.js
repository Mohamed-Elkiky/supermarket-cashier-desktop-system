"use strict";

/**
 * Windows toast notifications (Electron main process).
 *
 * Categorised notifications ({low_stock, expiry, food_safety_due, new_order})
 * are raised with Electron's Notification. Clicking a toast focuses the main
 * window and deep-links the renderer to the relevant screen via IPC.
 *
 * A lightweight poller fetches low-stock + expiry alerts per department WHEN a
 * manager session is active (cashier tokens are rejected 403 -> polling is
 * skipped silently). Alerts are de-duplicated/throttled with a per-key cooldown
 * and a per-cycle volume cap. Per-category enable/disable is stored in kv_meta.
 *
 * Dedupe/throttle and the category->route map are pure and unit-tested.
 */

const API_BASE = process.env.POS_API_BASE || "http://localhost:8000/api/v1";

const CATEGORIES = ["low_stock", "expiry", "food_safety_due", "new_order"];

const ROUTE_MAP = {
  low_stock: "inventory",
  expiry: "inventory",
  food_safety_due: "food_safety",
  new_order: "checkout",
};

function routeForCategory(category) {
  return ROUTE_MAP[category] || "checkout";
}

/* ------------------------------ dedupe/throttle ------------------------- */

const DEFAULT_COOLDOWN_MS = 5 * 60 * 1000;
let maxPerCycle = 5;
const notifiedAt = new Map(); // key -> last timestamp (ms)

/** Should this alert key fire now? Records the time when it may. */
function shouldNotify(key, now = Date.now(), cooldownMs = DEFAULT_COOLDOWN_MS) {
  const last = notifiedAt.get(key);
  if (last != null && now - last < cooldownMs) return false;
  notifiedAt.set(key, now);
  return true;
}

function resetDedupe() {
  notifiedAt.clear();
}

function setMaxPerCycle(n) {
  maxPerCycle = Math.max(1, n | 0);
}

/* ------------------------------ category config ------------------------- */

function isCategoryEnabled(category) {
  try {
    const db = require("../db/database");
    return db.getMeta(`notify_${category}_enabled`) !== "0";
  } catch {
    return true;
  }
}

function setCategoryEnabled(category, enabled) {
  try {
    require("../db/database").setMeta(`notify_${category}_enabled`, enabled ? "1" : "0");
  } catch {
    /* db optional */
  }
}

/* ------------------------------ raise a toast --------------------------- */

function focusMainAndRoute(category, deepLink) {
  try {
    const { BrowserWindow } = require("electron");
    const win = BrowserWindow.getAllWindows()[0];
    if (win) {
      if (win.isMinimized()) win.restore();
      win.show();
      win.focus();
    }
  } catch {
    /* not under Electron */
  }
  const payload = deepLink || { route: routeForCategory(category) };
  try {
    const { sendToRenderer } = require("../ipc/events");
    const { CHANNELS } = require("../ipc/channels");
    sendToRenderer(CHANNELS.NOTIFY_DEEPLINK_EVENT, payload);
  } catch {
    /* renderer not ready */
  }
}

/** Raise a categorised toast. Returns { shown, reason? }. */
function notify(category, { title, body, deepLink } = {}) {
  if (!CATEGORIES.includes(category)) return { shown: false, reason: "unknown_category" };
  if (!isCategoryEnabled(category)) return { shown: false, reason: "disabled" };
  try {
    const { Notification } = require("electron");
    if (!Notification || (Notification.isSupported && !Notification.isSupported())) {
      return { shown: false, reason: "unsupported" };
    }
    const n = new Notification({ title: title || category, body: body || "" });
    n.on("click", () => focusMainAndRoute(category, deepLink));
    n.show();
    return { shown: true };
  } catch {
    return { shown: false, reason: "no_electron" };
  }
}

/** Fire a sample toast for a category (verification helper). */
function test(category) {
  return notify(category, {
    title: `Test: ${category}`,
    body: `Sample ${category} notification`,
    deepLink: { route: routeForCategory(category) },
  });
}

/* ------------------------------ poller ---------------------------------- */

function defaultClient() {
  const syncWorker = require("../sync/syncWorker");
  const auth = () => {
    const token = syncWorker.getAuthToken();
    return { Accept: "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) };
  };
  const get = async (url) => {
    const res = await fetch(url, { headers: auth() });
    const json = await res.json().catch(() => null);
    if (res.ok && json && json.success) return json.data;
    const err = new Error(json && json.error ? json.error.code : `http_${res.status}`);
    err.status = res.status;
    throw err;
  };
  return {
    getLowStock: (deptId) => get(`${API_BASE}/inventory/stock/alerts/${deptId}/`),
    getExpiry: (deptId, days = 7) =>
      get(`${API_BASE}/inventory/ledger/expiry/${deptId}/?days_ahead=${days}`),
  };
}

/**
 * Poll low-stock + expiry alerts for the given departments and raise toasts for
 * new alerts. Skips silently when the session lacks manager permission (403).
 */
async function pollAlerts(client = defaultClient(), opts = {}) {
  const now = opts.now ?? Date.now();
  const cooldownMs = opts.cooldownMs ?? DEFAULT_COOLDOWN_MS;
  const notifyFn = opts.notifyFn || notify;
  const departmentIds = opts.departmentIds || [];
  const fired = [];

  for (const deptId of departmentIds) {
    let low;
    try {
      low = await client.getLowStock(deptId);
    } catch (err) {
      if (err && err.status === 403) return { fired, skipped: true, reason: "not_manager" };
      continue;
    }
    for (const a of low || []) {
      if (fired.length >= maxPerCycle) break;
      const key = `low_stock:${a.variant_id}`;
      if (shouldNotify(key, now, cooldownMs)) {
        notifyFn("low_stock", {
          title: "Low stock",
          body: `${a.name} — ${a.current_stock} left (min ${a.low_stock_threshold})`,
          deepLink: { route: "inventory", params: { variant_id: a.variant_id } },
        });
        fired.push(key);
      }
    }

    let expiry = [];
    try {
      expiry = await client.getExpiry(deptId);
    } catch {
      expiry = [];
    }
    for (const b of expiry || []) {
      if (fired.length >= maxPerCycle) break;
      const key = `expiry:${b.variant_id}:${b.best_before_date}`;
      if (shouldNotify(key, now, cooldownMs)) {
        notifyFn("expiry", {
          title: "Expiring soon",
          body: `${b.name} best before ${b.best_before_date}`,
          deepLink: { route: "inventory", params: { variant_id: b.variant_id } },
        });
        fired.push(key);
      }
    }
  }
  return { fired };
}

/* ------------------------------ lifecycle ------------------------------- */

let pollTimer = null;

function startPolling(opts = {}) {
  stopPolling();
  const interval = opts.intervalMs || 60000;
  pollTimer = setInterval(() => {
    void pollAlerts(defaultClient(), opts).catch(() => {});
  }, interval);
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

function init() {
  // App user model id is set in main.js; nothing to start until a manager
  // session + departments are configured (poller is opt-in via startPolling).
  console.log("[notifier] ready");
}

module.exports = {
  CATEGORIES,
  ROUTE_MAP,
  routeForCategory,
  shouldNotify,
  resetDedupe,
  setMaxPerCycle,
  isCategoryEnabled,
  setCategoryEnabled,
  notify,
  test,
  pollAlerts,
  startPolling,
  stopPolling,
  init,
};
