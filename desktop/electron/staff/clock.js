"use strict";

/**
 * Staff clock in/out (Electron main process). Backs the tray widget and the
 * window.api.staff.* bridge. When the backend is unreachable, events are queued
 * offline (clockSync) and replayed on reconnection.
 */

const crypto = require("crypto");

const clockSync = require("./clockSync");

let lastStatus = { clockedIn: false, staffName: null, shiftStartedAt: null };
const statusListeners = new Set();

function getToken() {
  try {
    return require("../sync/syncWorker").getAuthToken();
  } catch {
    return null;
  }
}

function normalizeStatus(data) {
  if (!data || typeof data !== "object") return lastStatus;
  return {
    clockedIn: data.clocked_in ?? data.is_clocked_in ?? false,
    staffName: data.staff_name ?? data.name ?? lastStatus.staffName ?? null,
    shiftStartedAt: data.shift_start_time ?? data.shift_started_at ?? null,
  };
}

function emitStatus() {
  for (const cb of statusListeners) {
    try {
      cb(lastStatus);
    } catch {
      /* ignore */
    }
  }
  try {
    const { sendToRenderer } = require("../ipc/events");
    const { CHANNELS } = require("../ipc/channels");
    sendToRenderer(CHANNELS.STAFF_STATUS_EVENT, lastStatus);
  } catch {
    /* not under Electron */
  }
}

/** Subscribe to clock status changes (used by the tray). */
function onStatusChange(cb) {
  statusListeners.add(cb);
  return () => statusListeners.delete(cb);
}

function isSignedIn() {
  return !!getToken();
}

async function doClock(eventType) {
  if (!isSignedIn()) {
    return { ...lastStatus, queued: false, signedIn: false, error: "not signed in" };
  }
  const clientUuid = crypto.randomUUID();
  const occurredAt = new Date().toISOString();
  try {
    const data = await clockSync.defaultClient().postClockEvent(eventType, {
      client_uuid: clientUuid,
      occurred_at: occurredAt,
    });
    lastStatus = normalizeStatus(data);
    emitStatus();
    return { ...lastStatus, queued: false, signedIn: true };
  } catch (err) {
    // Network / connectivity failure -> queue offline for replay.
    const status = err && err.status;
    if (status && status >= 400 && status < 500 && status !== 408) {
      // A real 4xx (e.g. already clocked in) is a business error, not offline.
      return { ...lastStatus, queued: false, signedIn: true, error: err.message };
    }
    clockSync.enqueue({ client_uuid: clientUuid, event_type: eventType, occurred_at: occurredAt });
    lastStatus = {
      clockedIn: eventType === "clock_in",
      staffName: lastStatus.staffName,
      shiftStartedAt: eventType === "clock_in" ? occurredAt : null,
    };
    emitStatus();
    return { ...lastStatus, queued: true, signedIn: true };
  }
}

async function clockIn() {
  return doClock("clock_in");
}

async function clockOut() {
  return doClock("clock_out");
}

async function getStatus() {
  if (!isSignedIn()) {
    lastStatus = { clockedIn: false, staffName: null, shiftStartedAt: null };
    return { ...lastStatus, signedIn: false };
  }
  try {
    const token = getToken();
    const API_BASE = process.env.POS_API_BASE || "http://localhost:8000/api/v1";
    const res = await fetch(`${API_BASE}/staff/clock-events/status/`, {
      headers: { Accept: "application/json", Authorization: `Bearer ${token}` },
    });
    const json = await res.json().catch(() => null);
    if (res.ok && json && json.success) {
      lastStatus = normalizeStatus(json.data);
    }
  } catch {
    /* offline — return last known status */
  }
  return { ...lastStatus, signedIn: true };
}

function getCachedStatus() {
  return { ...lastStatus, signedIn: isSignedIn() };
}

module.exports = { clockIn, clockOut, getStatus, getCachedStatus, onStatusChange, isSignedIn };
