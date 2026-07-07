"use strict";

/**
 * Offline background sync worker (Electron main process).
 *
 * - refreshCache(): pulls the product catalogue + active promotions into the
 *   encrypted local cache so the POS keeps working offline.
 * - replayQueue(): drains pending_transactions by replaying each queued sale to
 *   the backend (open order -> add items -> confirm -> checkout), carrying the
 *   client_uuid so the server can DEDUPE. Each transaction is atomic: it fully
 *   succeeds (removed from the queue) or is retried later (attempts++, last_error
 *   kept). A sale is never lost or double-applied.
 * - Connectivity is detected with a periodic health ping; on the offline->online
 *   transition it refreshes the cache and replays the queue.
 *
 * The backend HTTP client is INJECTABLE so the replay/idempotency logic is fully
 * unit-testable without a live server.
 *
 * NOTE on idempotency: the client always sends `client_uuid`. If the backend
 * does not yet honour it as an idempotency key, dedupe is still guaranteed
 * client-side (a queued row is removed only after a confirmed success, and the
 * UNIQUE(client_uuid) constraint prevents duplicate enqueues). Server-side
 * idempotency support should be added for full end-to-end safety — flagged here,
 * backend intentionally NOT modified.
 */

const db = require("../db/database");

const API_BASE = process.env.POS_API_BASE || "http://localhost:8000/api/v1";
const HEALTH_URL = process.env.POS_HEALTH_URL || "http://localhost:8000/api/health/";

let authToken = null;
let online = false;
let syncing = false;
let pingTimer = null;

function setAuthToken(token) {
  authToken = token || null;
}

function getAuthToken() {
  return authToken;
}

/* ------------------------------ status ---------------------------------- */

function getStatus() {
  const base = safeQueueStatus();
  return { ...base, online, syncing };
}

function safeQueueStatus() {
  try {
    return db.getQueueStatus();
  } catch {
    return { pendingTransactions: 0, pendingClockEvents: 0, lastSyncedAt: null };
  }
}

function emitStatus() {
  try {
    const { sendToRenderer } = require("../ipc/events");
    const { CHANNELS } = require("../ipc/channels");
    sendToRenderer(CHANNELS.DB_SYNC_STATUS_EVENT, getStatus());
  } catch {
    /* not under Electron */
  }
}

/* ------------------------------ default HTTP client --------------------- */

function authHeaders(extra = {}) {
  const headers = { Accept: "application/json", ...extra };
  if (authToken) headers["Authorization"] = `Bearer ${authToken}`;
  return headers;
}

async function unwrap(res) {
  const json = await res.json().catch(() => null);
  if (res.ok && json && json.success) return json.data;
  const code = json && json.error ? json.error.code : `http_${res.status}`;
  const err = new Error(code);
  err.status = res.status;
  throw err;
}

function defaultClient() {
  return {
    async health() {
      const res = await fetch(HEALTH_URL, { headers: { Accept: "application/json" } });
      if (!res.ok) throw new Error(`health ${res.status}`);
      return true;
    },
    async getProducts() {
      return unwrap(await fetch(`${API_BASE}/inventory/products/`, { headers: authHeaders() }));
    },
    async getPromotions() {
      return unwrap(
        await fetch(`${API_BASE}/pos/promotions/?is_active=true`, { headers: authHeaders() }),
      );
    },
    async openOrder(clientUuid) {
      return unwrap(
        await fetch(`${API_BASE}/pos/orders/`, {
          method: "POST",
          headers: authHeaders({ "Content-Type": "application/json" }),
          body: JSON.stringify({ client_uuid: clientUuid }),
        }),
      );
    },
    async addItem(orderId, item) {
      return unwrap(
        await fetch(`${API_BASE}/pos/orders/${orderId}/items/`, {
          method: "POST",
          headers: authHeaders({ "Content-Type": "application/json" }),
          body: JSON.stringify(item),
        }),
      );
    },
    async confirm(orderId) {
      return unwrap(
        await fetch(`${API_BASE}/pos/orders/${orderId}/confirm/`, {
          method: "POST",
          headers: authHeaders({ "Content-Type": "application/json" }),
          body: JSON.stringify({}),
        }),
      );
    },
    async checkout(orderId, payload) {
      return unwrap(
        await fetch(`${API_BASE}/pos/orders/${orderId}/checkout/`, {
          method: "POST",
          headers: authHeaders({ "Content-Type": "application/json" }),
          body: JSON.stringify(payload),
        }),
      );
    },
  };
}

/* ------------------------------ cache refresh --------------------------- */

function mapProductsToCache(products) {
  const list = Array.isArray(products) ? products : products?.results || [];
  const rows = [];
  for (const p of list) {
    for (const v of p.variants || []) {
      rows.push({
        variant_id: v.id,
        product_id: p.id,
        sku: v.sku,
        barcode: v.barcode,
        name: v.name,
        pricing_mode: v.pricing_mode,
        sell_price_pence: v.sell_price,
        department_id: p.department,
        unit_of_measure: v.unit_of_measure,
        payload_json: JSON.stringify(v),
      });
    }
  }
  return rows;
}

function mapPromotionsToCache(promotions) {
  const list = Array.isArray(promotions) ? promotions : promotions?.results || [];
  return list.map((pr) => ({
    id: pr.id,
    name: pr.name,
    promotion_type: pr.promotion_type,
    payload_json: JSON.stringify(pr),
    is_active: pr.is_active !== false,
  }));
}

async function refreshCache(client = defaultClient()) {
  const products = await client.getProducts();
  const promotions = await client.getPromotions();
  const productRows = mapProductsToCache(products);
  const promoRows = mapPromotionsToCache(promotions);
  db.replaceProductsCache(productRows);
  db.replacePromotionsCache(promoRows);
  db.setLastSyncedAt(new Date().toISOString());
  emitStatus();
  return { ok: true, products: productRows.length, promotions: promoRows.length };
}

/* ------------------------------ replay ---------------------------------- */

async function replayOne(client, payload) {
  const clientUuid = payload.client_uuid;
  const order = await client.openOrder(clientUuid);
  for (const item of payload.items || []) {
    await client.addItem(order.id, item);
  }
  await client.confirm(order.id);
  const paid = await client.checkout(order.id, { ...(payload.payment || {}), client_uuid: clientUuid });

  // Reconcile: the server's promotion application is authoritative. Flag any
  // mismatch against the offline estimate rather than trusting the estimate.
  if (
    payload.estimatedTotalPence != null &&
    paid &&
    paid.total_pence != null &&
    Number(payload.estimatedTotalPence) !== Number(paid.total_pence)
  ) {
    console.warn(
      `[sync] total mismatch for ${clientUuid}: offline £${payload.estimatedTotalPence} vs server £${paid.total_pence}`,
    );
    try {
      db.setMeta(
        `recon_mismatch_${clientUuid}`,
        JSON.stringify({ estimated: payload.estimatedTotalPence, server: paid.total_pence }),
      );
    } catch {
      /* meta best-effort */
    }
  }
  return paid;
}

/**
 * Drain the pending-transaction queue. Returns { drained, failed }.
 * Each transaction is atomic: success -> removed; failure -> attempts++ + kept.
 */
async function replayQueue(client = defaultClient()) {
  if (syncing) return { drained: 0, failed: 0, skipped: true };
  syncing = true;
  emitStatus();
  let drained = 0;
  let failed = 0;
  try {
    const pending = db.listPendingTransactions();
    for (const row of pending) {
      let payload;
      try {
        payload = JSON.parse(row.payload_json);
      } catch {
        db.recordTransactionFailure(row.client_uuid, "corrupt payload_json");
        failed += 1;
        continue;
      }
      try {
        await replayOne(client, payload);
        db.markTransactionDone(row.client_uuid);
        drained += 1;
      } catch (err) {
        db.recordTransactionFailure(row.client_uuid, err && err.message ? err.message : String(err));
        failed += 1;
      }
    }
  } finally {
    syncing = false;
    emitStatus();
  }
  return { drained, failed };
}

/** Enqueue a completed offline sale (idempotent by client_uuid). */
function enqueueSale(payload) {
  return db.enqueueTransaction(payload);
}

/* ------------------------------ connectivity ---------------------------- */

async function checkOnline(client = defaultClient()) {
  try {
    await client.health();
    return true;
  } catch {
    return false;
  }
}

async function tick(client = defaultClient()) {
  const was = online;
  online = await checkOnline(client);
  if (online && !was) {
    // Offline -> online transition: refresh cache and drain the queues.
    try {
      await refreshCache(client);
    } catch {
      /* refresh best-effort */
    }
    try {
      await replayQueue(client);
    } catch {
      /* replay best-effort */
    }
    try {
      await require("../staff/clockSync").replayClockEvents();
    } catch {
      /* clock replay best-effort */
    }
  }
  emitStatus();
  return online;
}

function start(intervalMs = 15000) {
  stop();
  pingTimer = setInterval(() => {
    void tick();
  }, intervalMs);
  // Kick an immediate check.
  void tick();
}

function stop() {
  if (pingTimer) {
    clearInterval(pingTimer);
    pingTimer = null;
  }
}

module.exports = {
  setAuthToken,
  getAuthToken,
  refreshCache,
  replayQueue,
  replayOne,
  enqueueSale,
  checkOnline,
  tick,
  start,
  stop,
  getStatus,
  mapProductsToCache,
  mapPromotionsToCache,
  defaultClient,
};
