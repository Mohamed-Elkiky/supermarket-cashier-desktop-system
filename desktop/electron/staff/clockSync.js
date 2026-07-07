"use strict";

/**
 * Offline queue + replay for staff clock in/out events (Electron main process).
 *
 * When a clock-in/out cannot reach the backend it is queued in
 * pending_clock_events with a client UUID + timestamp and replayed on
 * reconnection using the same background-sync mechanism as sales. No clock event
 * is ever lost or double-applied (UNIQUE(client_uuid) + remove-on-success).
 *
 * The backend client is injectable so the queue/replay logic is unit-testable.
 */

const db = require("../db/database");

const API_BASE = process.env.POS_API_BASE || "http://localhost:8000/api/v1";

const PATHS = {
  clock_in: "/staff/clock-events/clock-in/",
  clock_out: "/staff/clock-events/clock-out/",
};

function defaultClient() {
  const syncWorker = require("../sync/syncWorker");
  return {
    async postClockEvent(eventType, body) {
      const token = syncWorker.getAuthToken();
      const path = PATHS[eventType];
      if (!path) throw new Error(`unknown clock event: ${eventType}`);
      const res = await fetch(`${API_BASE}${path}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify(body),
      });
      const json = await res.json().catch(() => null);
      if (res.ok && json && json.success) return json.data;
      const err = new Error(json && json.error ? json.error.code : `http_${res.status}`);
      err.status = res.status;
      throw err;
    },
  };
}

/** Queue a clock event (idempotent by client_uuid). */
function enqueue(evt) {
  return db.enqueueClockEvent(evt);
}

/**
 * Replay queued clock events in order. Each is atomic: success -> removed;
 * failure -> attempts++ + kept for a later retry.
 */
async function replayClockEvents(client = defaultClient()) {
  let drained = 0;
  let failed = 0;
  const pending = db.listPendingClockEvents();
  for (const row of pending) {
    try {
      await client.postClockEvent(row.event_type, {
        client_uuid: row.client_uuid,
        occurred_at: row.occurred_at,
      });
      db.markClockEventDone(row.client_uuid);
      drained += 1;
    } catch (err) {
      db.recordClockEventFailure(row.client_uuid, err && err.message ? err.message : String(err));
      failed += 1;
    }
  }
  return { drained, failed };
}

module.exports = { enqueue, replayClockEvents, defaultClient, PATHS };
