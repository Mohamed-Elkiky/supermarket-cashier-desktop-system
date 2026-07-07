"use strict";

/**
 * Windows system tray clock-in widget (Electron main process).
 *
 * A persistent tray icon whose tooltip + right-click menu reflect the signed-in
 * staff member and their clock status. Clock In/Out call the backend (queuing
 * offline on failure). The menu is rebuilt whenever the clock status changes so
 * enabled/disabled states stay correct.
 */

const path = require("path");
const { Tray, Menu, nativeImage, app } = require("electron");

const clock = require("../staff/clock");

// 16x16 green PNG fallback so the tray always has a valid icon even if no
// branded build/tray.png has been dropped in yet.
const FALLBACK_ICON_DATA_URL =
  "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAAGUlEQVR4nGNQOhr3nxLMMGrAqAGjBgwXAwBRB0QfyEny+QAAAABJRU5ErkJggg==";

let tray = null;
let opts = {};
let unsubStatus = null;

function loadIcon() {
  const file = path.join(__dirname, "..", "..", "build", "tray.png");
  try {
    const img = nativeImage.createFromPath(file);
    if (img && !img.isEmpty()) return img;
  } catch {
    /* fall back below */
  }
  return nativeImage.createFromDataURL(FALLBACK_ICON_DATA_URL);
}

function formatTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const pad = (n) => String(n).padStart(2, "0");
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function rebuildMenu() {
  if (!tray) return;
  const st = clock.getCachedStatus();
  const signedIn = st.signedIn;

  tray.setToolTip(
    signedIn
      ? `Supermarket POS — ${st.staffName || "Staff"} (${st.clockedIn ? "clocked in" : "clocked out"})`
      : "Supermarket POS — not signed in",
  );

  const template = [];
  if (!signedIn) {
    template.push({ label: "Not signed in — open app to log in", enabled: false });
  } else {
    template.push({ label: `Signed in: ${st.staffName || "Staff"}`, enabled: false });
    if (st.clockedIn && st.shiftStartedAt) {
      template.push({ label: `Shift since ${formatTime(st.shiftStartedAt)}`, enabled: false });
    }
  }
  template.push({ type: "separator" });
  template.push({ label: "Clock In", enabled: signedIn && !st.clockedIn, click: () => void onClock("in") });
  template.push({ label: "Clock Out", enabled: signedIn && st.clockedIn, click: () => void onClock("out") });
  template.push({ type: "separator" });
  template.push({ label: "Open POS", click: () => opts.focusMain && opts.focusMain() });
  template.push({ label: "Quit", click: () => app.quit() });

  tray.setContextMenu(Menu.buildFromTemplate(template));
}

async function onClock(direction) {
  try {
    const res = direction === "in" ? await clock.clockIn() : await clock.clockOut();
    if (res.queued) {
      balloon("Saved offline", "Clock event queued — it will sync when back online.");
    } else if (res.error) {
      balloon("Clock error", res.error);
    }
  } catch (err) {
    balloon("Clock error", err && err.message ? err.message : "Failed to record clock event");
  }
  rebuildMenu();
}

function balloon(title, content) {
  try {
    if (tray && typeof tray.displayBalloon === "function") {
      tray.displayBalloon({ title, content });
    }
  } catch {
    /* balloons are Windows-only / best effort */
  }
}

function init(options = {}) {
  opts = options;
  tray = new Tray(loadIcon());
  unsubStatus = clock.onStatusChange(() => rebuildMenu());
  rebuildMenu();
  // Pull the latest status from the backend, then refresh the menu.
  clock
    .getStatus()
    .then(() => rebuildMenu())
    .catch(() => rebuildMenu());
}

function destroy() {
  if (unsubStatus) {
    unsubStatus();
    unsubStatus = null;
  }
  if (tray) {
    tray.destroy();
    tray = null;
  }
}

module.exports = { init, destroy, rebuildMenu };
