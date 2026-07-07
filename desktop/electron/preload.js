"use strict";

/**
 * Hardened preload bridge.
 *
 * Runs with contextIsolation:true + sandbox:true, so this is the ONLY channel
 * between the renderer and the main process. We expose a small, fixed,
 * allow-listed API via contextBridge. No Node globals (require, process, Buffer,
 * fs, ipcRenderer itself) are ever placed on `window`. Every method funnels
 * through ipcRenderer.invoke on a known channel constant.
 */

const { contextBridge, ipcRenderer } = require("electron");
const { CHANNELS } = require("./ipc/channels");

/** invoke() wrapper so no raw channel string is constructed in the bridge. */
function invoke(channel, payload) {
  return ipcRenderer.invoke(channel, payload);
}

/**
 * Subscribe to a main -> renderer push channel. Strips the Electron event object
 * so the renderer callback only ever sees the sanitized payload. Returns an
 * unsubscribe function.
 */
function subscribe(channel, cb) {
  const listener = (_event, payload) => {
    try {
      cb(payload);
    } catch {
      /* renderer callback errors must not break the IPC pipe */
    }
  };
  ipcRenderer.on(channel, listener);
  return () => ipcRenderer.removeListener(channel, listener);
}

const api = {
  app: {
    getVersion: () => invoke(CHANNELS.APP_GET_VERSION),
    getPlatform: () => invoke(CHANNELS.APP_GET_PLATFORM),
  },
  printer: {
    list: () => invoke(CHANNELS.PRINTER_LIST),
    printReceipt: (data, opts) =>
      invoke(CHANNELS.PRINTER_PRINT_RECEIPT, { data, opts }),
    printTest: (opts) => invoke(CHANNELS.PRINTER_PRINT_TEST, { opts }),
  },
  scale: {
    listPorts: () => invoke(CHANNELS.SCALE_LIST_PORTS),
    connect: (config) => invoke(CHANNELS.SCALE_CONNECT, { config }),
    disconnect: () => invoke(CHANNELS.SCALE_DISCONNECT),
    onWeight: (cb) => subscribe(CHANNELS.SCALE_WEIGHT_EVENT, cb),
  },
  drawer: {
    open: (opts) => invoke(CHANNELS.DRAWER_OPEN, { opts }),
    openTest: (opts) => invoke(CHANNELS.DRAWER_OPEN_TEST, { opts }),
  },
  db: {
    getMeta: (key) => invoke(CHANNELS.DB_GET_META, { key }),
    setMeta: (key, value) => invoke(CHANNELS.DB_SET_META, { key, value }),
    getCachedProducts: (departmentId) =>
      invoke(CHANNELS.DB_GET_CACHED_PRODUCTS, { departmentId }),
    getCachedPromotions: () => invoke(CHANNELS.DB_GET_CACHED_PROMOTIONS),
    refreshCache: () => invoke(CHANNELS.DB_REFRESH_CACHE),
    enqueueTransaction: (payload) =>
      invoke(CHANNELS.DB_ENQUEUE_TRANSACTION, { payload }),
    getQueueStatus: () => invoke(CHANNELS.DB_GET_QUEUE_STATUS),
    setSyncToken: (token) => invoke(CHANNELS.DB_SET_SYNC_TOKEN, { token }),
    onSyncStatus: (cb) => subscribe(CHANNELS.DB_SYNC_STATUS_EVENT, cb),
  },
  label: {
    print: (payload, opts) => invoke(CHANNELS.LABEL_PRINT, { payload, opts }),
    preview: (payload, opts) =>
      invoke(CHANNELS.LABEL_PREVIEW, { payload, opts }),
  },
  staff: {
    clockIn: () => invoke(CHANNELS.STAFF_CLOCK_IN),
    clockOut: () => invoke(CHANNELS.STAFF_CLOCK_OUT),
    getStatus: () => invoke(CHANNELS.STAFF_GET_STATUS),
    onStatusChange: (cb) => subscribe(CHANNELS.STAFF_STATUS_EVENT, cb),
  },
  notify: {
    test: (category) => invoke(CHANNELS.NOTIFY_TEST, { category }),
    onDeepLink: (cb) => subscribe(CHANNELS.NOTIFY_DEEPLINK_EVENT, cb),
  },
};

contextBridge.exposeInMainWorld("api", api);
