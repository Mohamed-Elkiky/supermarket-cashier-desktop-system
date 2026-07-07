"use strict";

/**
 * Electron main process for the Supermarket POS desktop client.
 *
 * Responsibilities:
 *  - Branded splash window, then the hardened main window (Task 1).
 *  - Full security hardening: contextIsolation/sandbox, CSP, navigation
 *    lockdown, allow-listed external opens (Task 2).
 *  - electron-updater wiring, feed URL from env, silent when unconfigured (Task 1).
 *  - Encrypted local DB init + first-run key warning (Task 3).
 *  - System tray clock widget (Task 13) and Windows toast notifier (Task 15).
 *
 * Feature subsystems are lazy/guarded so a missing native dependency degrades
 * gracefully instead of preventing the app from starting.
 */

const path = require("path");
const { app, BrowserWindow, session, shell } = require("electron");
const { registerHandlers } = require("./ipc/registerHandlers");
const events = require("./ipc/events");

const APP_USER_MODEL_ID = "com.kiky.supermarketpos";
// Automated launch smoke test: boot the full app, then quit as soon as the shell
// window is ready. Lets CI/dev verify the whole main-process chain without a
// human closing a window. No effect on normal runs.
const SMOKE_TEST = process.env.POS_SMOKE_TEST === "1";
const DEV_SERVER_URL = process.env.VITE_DEV_SERVER_URL || "http://localhost:5173";
const BACKEND_HTTP = "http://localhost:8000";
const BACKEND_WS = "ws://localhost:8000";

/** True when running against the Vite dev server rather than a packaged build. */
function isDev() {
  return (
    !!process.env.VITE_DEV_SERVER_URL ||
    (process.env.NODE_ENV !== "production" && !app.isPackaged)
  );
}

/** Hosts we permit opening in the user's real browser via shell.openExternal. */
const EXTERNAL_HTTPS_ALLOWLIST = new Set([
  // e.g. "docs.kiky.example" — intentionally empty by default.
]);

let mainWindow = null;
let splashWindow = null;

/* ------------------------------------------------------------------ */
/* Content-Security-Policy                                            */
/* ------------------------------------------------------------------ */

function buildCsp() {
  const connect = ["'self'", BACKEND_HTTP, BACKEND_WS];
  const script = ["'self'"];
  const style = ["'self'", "'unsafe-inline'"]; // inline styles from React / CSS-in-JS

  if (isDev()) {
    // Vite dev server + React Refresh need inline/eval and an HMR websocket.
    script.push("'unsafe-inline'", "'unsafe-eval'");
    connect.push(DEV_SERVER_URL, DEV_SERVER_URL.replace(/^http/, "ws"));
  }

  return [
    `default-src 'self'`,
    `script-src ${script.join(" ")}`,
    `style-src ${style.join(" ")}`,
    `img-src 'self' data:`,
    `font-src 'self' data:`,
    `connect-src ${connect.join(" ")}`,
    `object-src 'none'`,
    `base-uri 'self'`,
    `frame-ancestors 'none'`,
    `form-action 'self'`,
  ].join("; ");
}

function installCsp() {
  const csp = buildCsp();
  session.defaultSession.webRequest.onHeadersReceived((details, callback) => {
    callback({
      responseHeaders: {
        ...details.responseHeaders,
        "Content-Security-Policy": [csp],
        "X-Content-Type-Options": ["nosniff"],
      },
    });
  });
}

/* ------------------------------------------------------------------ */
/* Navigation lockdown                                                */
/* ------------------------------------------------------------------ */

function isSameOriginNavigation(targetUrl) {
  try {
    const url = new URL(targetUrl);
    if (isDev()) {
      const dev = new URL(DEV_SERVER_URL);
      return url.origin === dev.origin;
    }
    return url.protocol === "file:";
  } catch {
    return false;
  }
}

function maybeOpenExternal(targetUrl) {
  try {
    const url = new URL(targetUrl);
    if (url.protocol === "https:" && EXTERNAL_HTTPS_ALLOWLIST.has(url.hostname)) {
      void shell.openExternal(targetUrl);
    }
  } catch {
    /* ignore malformed URLs */
  }
}

function hardenNavigation() {
  app.on("web-contents-created", (_event, contents) => {
    // Deny all window.open / target=_blank; optionally hand off to the browser.
    contents.setWindowOpenHandler(({ url }) => {
      maybeOpenExternal(url);
      return { action: "deny" };
    });
    // Block navigations away from the app's own origin.
    contents.on("will-navigate", (event, url) => {
      if (!isSameOriginNavigation(url)) {
        event.preventDefault();
        maybeOpenExternal(url);
      }
    });
    // Refuse attaching webviews.
    contents.on("will-attach-webview", (event) => event.preventDefault());
  });
}

/* ------------------------------------------------------------------ */
/* Windows                                                            */
/* ------------------------------------------------------------------ */

const HARDENED_WEB_PREFERENCES = {
  contextIsolation: true,
  nodeIntegration: false,
  nodeIntegrationInWorker: false,
  nodeIntegrationInSubFrames: false,
  sandbox: true,
  webSecurity: true,
  allowRunningInsecureContent: false,
  experimentalFeatures: false,
  preload: path.join(__dirname, "preload.js"),
};

function createSplashWindow() {
  splashWindow = new BrowserWindow({
    width: 500,
    height: 300,
    frame: false,
    resizable: false,
    center: true,
    show: true,
    skipTaskbar: true,
    alwaysOnTop: true,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  void splashWindow.loadFile(path.join(__dirname, "splash.html"));
  splashWindow.on("closed", () => {
    splashWindow = null;
  });
}

function createMainWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 1024,
    minHeight: 700,
    show: false,
    backgroundColor: "#0f172a",
    title: "Supermarket POS",
    webPreferences: HARDENED_WEB_PREFERENCES,
  });

  events.setMainWindow(mainWindow);

  if (isDev()) {
    void mainWindow.loadURL(DEV_SERVER_URL);
  } else {
    void mainWindow.loadFile(path.join(__dirname, "../dist/index.html"));
  }

  mainWindow.once("ready-to-show", () => {
    if (splashWindow && !splashWindow.isDestroyed()) {
      splashWindow.close();
    }
    if (mainWindow) {
      mainWindow.show();
      mainWindow.focus();
    }
    if (SMOKE_TEST) {
      console.log("[smoke] main window ready-to-show — shell rendered OK");
      setTimeout(() => app.quit(), 400);
    }
  });

  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

/* ------------------------------------------------------------------ */
/* Auto-updater (Task 1)                                              */
/* ------------------------------------------------------------------ */

function initAutoUpdater() {
  const feedUrl = process.env.UPDATE_FEED_URL;
  if (!feedUrl) {
    console.log("auto-update disabled: no feed configured");
    return;
  }
  try {
    const { autoUpdater } = require("electron-updater");
    autoUpdater.setFeedURL({ provider: "generic", url: feedUrl });
    if (!app.isPackaged) {
      // The updater cannot verify signatures against a dev build; make it best
      // effort so development never crashes.
      autoUpdater.forceDevUpdateConfig = true;
    }
    autoUpdater.on("error", (err) => {
      console.warn("auto-update error:", err && err.message ? err.message : err);
    });
    void autoUpdater.checkForUpdatesAndNotify();
  } catch (err) {
    console.warn(
      "auto-update unavailable:",
      err && err.message ? err.message : err,
    );
  }
}

/* ------------------------------------------------------------------ */
/* Guarded subsystem init (DB / tray / notifier)                      */
/* ------------------------------------------------------------------ */

async function initDatabase() {
  let dbModule;
  try {
    dbModule = require("./db/database");
  } catch (err) {
    console.warn(
      "local database module unavailable:",
      err && err.message ? err.message : err,
    );
    return;
  }
  try {
    await dbModule.init();
    console.log("[db] encrypted local database ready at", dbModule.getDbPath());
  } catch (err) {
    const msg = err && err.message ? err.message : String(err);
    // Dev convenience: any DB init failure (most often a native module not yet
    // rebuilt for the Electron ABI) is non-fatal while developing so the UI can
    // still be worked on. It is FATAL in a packaged build — we never silently
    // run without encryption in production. (Never block on a modal dialog.)
    if (isDev()) {
      console.warn("[db] encrypted DB disabled in dev:", msg);
      if (err && err.nativeUnavailable) {
        console.warn("[db] run `npx electron-rebuild` to enable it inside Electron.");
      }
      return;
    }
    console.error("[db] FATAL — cannot open encrypted database:", msg);
    try {
      const { dialog } = require("electron");
      dialog.showErrorBox(
        "Secure storage unavailable",
        "The encrypted local database could not be opened, so the till cannot " +
          "start safely. Data is never stored unencrypted.\n\n" +
          msg,
      );
    } catch {
      /* dialog unavailable */
    }
    app.quit();
  }
}

function initTray() {
  try {
    const tray = require("./tray/trayWidget");
    tray.init({ focusMain: () => focusMainWindow() });
  } catch (err) {
    console.warn("tray unavailable:", err && err.message ? err.message : err);
  }
}

function initNotifier() {
  try {
    const notifier = require("./notifications/notifier");
    notifier.init();
  } catch (err) {
    console.warn(
      "notifier unavailable:",
      err && err.message ? err.message : err,
    );
  }
}

function initHardware() {
  // Auto-detect connected receipt printers on startup (never fatal).
  try {
    require("./hardware/receiptPrinter").init();
  } catch (err) {
    console.warn("printer detection skipped:", err && err.message ? err.message : err);
  }
}

function initSync() {
  // Background connectivity watcher + offline replay worker.
  try {
    require("./sync/syncWorker").start();
  } catch (err) {
    console.warn("sync worker unavailable:", err && err.message ? err.message : err);
  }
}

function focusMainWindow() {
  if (!mainWindow) {
    createMainWindow();
    return;
  }
  if (mainWindow.isMinimized()) mainWindow.restore();
  mainWindow.show();
  mainWindow.focus();
}

/* ------------------------------------------------------------------ */
/* App lifecycle                                                      */
/* ------------------------------------------------------------------ */

// Enforce a single running instance so the tray/DB stay coherent.
const gotSingleInstanceLock = app.requestSingleInstanceLock();
if (!gotSingleInstanceLock) {
  app.quit();
} else {
  app.on("second-instance", () => focusMainWindow());

  app.whenReady().then(async () => {
    app.setAppUserModelId(APP_USER_MODEL_ID);

    installCsp();
    hardenNavigation();
    registerHandlers();

    createSplashWindow();
    // Open the encrypted DB (and show the first-run recovery warning) before the
    // renderer loads, so the UI never races an uninitialised database.
    await initDatabase();
    createMainWindow();

    initAutoUpdater();
    initHardware();
    initSync();
    initTray();
    initNotifier();

    if (SMOKE_TEST) {
      // Watchdog: quit even if the renderer never signals ready (e.g. dev
      // server down) so an automated smoke run can never hang.
      setTimeout(() => {
        console.log("[smoke] watchdog timeout — quitting");
        app.quit();
      }, 20000);
    }

    app.on("activate", () => {
      if (BrowserWindow.getAllWindows().length === 0) {
        createMainWindow();
      }
    });
  });

  app.on("window-all-closed", () => {
    // On Windows/Linux quit when all windows close; keep the tray-driven app
    // alive only on macOS per platform convention.
    if (process.platform !== "darwin") {
      app.quit();
    }
  });
}

module.exports = { buildCsp, isSameOriginNavigation, HARDENED_WEB_PREFERENCES };
