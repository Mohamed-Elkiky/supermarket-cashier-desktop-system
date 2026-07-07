"use strict";

/**
 * Connected weighing-scale serial integration (Electron main process).
 *
 * - Uses the `serialport` package for real scales; parses lines with a pluggable
 *   protocol (continuous stream or ENQ/poll) from scaleProtocols.js.
 * - Normalises to { weightKg, stable } and only surfaces STABLE readings to the
 *   renderer (debouncing noise + duplicate frames).
 * - MOCK MODE (POS_SCALE_MOCK=1 or no port configured) runs a simulator that
 *   emits realistic stable readings so deli/produce screens work without
 *   hardware. Never crashes when no scale is connected.
 *
 * Readings are pushed to the renderer through the central event bus on the
 * SCALE_WEIGHT_EVENT channel; the renderer subscribes via window.api.scale.onWeight.
 */

const { getParser, round3, ENQ } = require("./scaleProtocols");

let port = null;
let readline = null;
let mockTimer = null;
let pollTimer = null;
let currentConfig = null;
let lastStableWeight = null;

/* ------------------------------ emit plumbing --------------------------- */

function defaultEmit(reading) {
  try {
    const { sendToRenderer } = require("../ipc/events");
    const { CHANNELS } = require("../ipc/channels");
    sendToRenderer(CHANNELS.SCALE_WEIGHT_EVENT, reading);
  } catch {
    /* not under Electron */
  }
}

let emitReading = defaultEmit;

/** Test seam: override where stable readings are delivered. */
function __setEmitterForTest(fn) {
  emitReading = typeof fn === "function" ? fn : defaultEmit;
}

/** Surface a reading if it is stable and meaningfully different (debounce). */
function surface(reading) {
  if (!reading || reading.stable !== true) return;
  if (
    lastStableWeight !== null &&
    Math.abs(reading.weightKg - lastStableWeight) < 0.001
  ) {
    return;
  }
  lastStableWeight = reading.weightKg;
  emitReading(reading);
}

/* ------------------------------ port listing ---------------------------- */

async function listPorts() {
  try {
    const { SerialPort } = require("serialport");
    const ports = await SerialPort.list();
    return ports.map((p) => ({ path: p.path, manufacturer: p.manufacturer }));
  } catch {
    return [];
  }
}

/* ------------------------------ connect --------------------------------- */

async function connect(config = {}) {
  await disconnect();
  currentConfig = {
    baudRate: 9600,
    dataBits: 8,
    parity: "none",
    protocol: "continuous",
    ...config,
  };
  lastStableWeight = null;

  const useMock = process.env.POS_SCALE_MOCK === "1" || !currentConfig.path;
  if (useMock) {
    startMock();
    return { ok: true, mock: true };
  }

  try {
    const { SerialPort, ReadlineParser } = require("serialport");
    port = new SerialPort({
      path: currentConfig.path,
      baudRate: currentConfig.baudRate,
      dataBits: currentConfig.dataBits,
      parity: currentConfig.parity,
      autoOpen: true,
    });
    const parser = getParser(currentConfig.protocol);
    readline = port.pipe(new ReadlineParser({ delimiter: "\r\n" }));
    readline.on("data", (line) => {
      const reading = parser.parse(String(line));
      if (reading) surface(reading);
    });
    port.on("error", (err) => {
      console.warn("[scale] serial error:", err && err.message ? err.message : err);
    });
    if (currentConfig.protocol === "poll") {
      const interval = currentConfig.pollIntervalMs || 500;
      pollTimer = setInterval(() => {
        try {
          port.write(ENQ);
        } catch {
          /* ignore transient write errors */
        }
      }, interval);
    }
    return { ok: true, mock: false };
  } catch (err) {
    console.warn(
      "[scale] connect failed, using mock:",
      err && err.message ? err.message : err,
    );
    startMock();
    return { ok: true, mock: true };
  }
}

async function disconnect() {
  stopMock();
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
  if (port) {
    try {
      await new Promise((resolve) => port.close(() => resolve()));
    } catch {
      /* already closed */
    }
    port = null;
    readline = null;
  }
  return { ok: true };
}

/* ------------------------------ mock mode ------------------------------- */

function randTarget() {
  // Realistic deli/produce weights: 0.05 kg – 3.0 kg.
  return round3(0.05 + Math.random() * 2.95);
}

function startMock() {
  stopMock();
  let target = randTarget();
  const interval = (currentConfig && currentConfig.mockIntervalMs) || 1200;
  mockTimer = setInterval(() => {
    // Random-walk the weight so the renderer sees a live, changing value that
    // settles to a stable reading (as a real item on a scale would).
    target = round3(Math.min(3.0, Math.max(0.05, target + (Math.random() - 0.5) * 0.08)));
    surface({ weightKg: target, stable: true });
  }, interval);
}

function stopMock() {
  if (mockTimer) {
    clearInterval(mockTimer);
    mockTimer = null;
  }
}

function isConnected() {
  return !!(port || mockTimer);
}

module.exports = {
  listPorts,
  connect,
  disconnect,
  isConnected,
  surface,
  __setEmitterForTest,
};
