"use strict";

/**
 * The SINGLE source of truth for every IPC channel the renderer is allowed to
 * invoke. The preload bridge and the main-process handler registry both import
 * from here. Any channel not in ALLOWED_CHANNELS is rejected — there is no
 * dynamic / string-built channel anywhere in the app.
 */

const CHANNELS = Object.freeze({
  // App / meta
  APP_GET_VERSION: "app:getVersion",
  APP_GET_PLATFORM: "app:getPlatform",

  // Receipt printer (Task 4)
  PRINTER_LIST: "printer:list",
  PRINTER_PRINT_RECEIPT: "printer:printReceipt",
  PRINTER_PRINT_TEST: "printer:printTest",

  // Weighing scale (Task 6)
  SCALE_LIST_PORTS: "scale:listPorts",
  SCALE_CONNECT: "scale:connect",
  SCALE_DISCONNECT: "scale:disconnect",
  // main -> renderer push
  SCALE_WEIGHT_EVENT: "scale:weight",

  // Cash drawer (Task 7)
  DRAWER_OPEN: "drawer:open",
  DRAWER_OPEN_TEST: "drawer:openTest",

  // Encrypted local DB (Task 3 / Task 12)
  DB_GET_META: "db:getMeta",
  DB_SET_META: "db:setMeta",
  DB_GET_CACHED_PRODUCTS: "db:getCachedProducts",
  DB_GET_CACHED_PROMOTIONS: "db:getCachedPromotions",
  DB_REFRESH_CACHE: "db:refreshCache",
  DB_ENQUEUE_TRANSACTION: "db:enqueueTransaction",
  DB_GET_QUEUE_STATUS: "db:getQueueStatus",
  DB_SET_SYNC_TOKEN: "db:setSyncToken",
  // main -> renderer push
  DB_SYNC_STATUS_EVENT: "db:syncStatus",

  // Weigh-label printer (Task 9)
  LABEL_PRINT: "label:print",
  LABEL_PREVIEW: "label:preview",

  // Staff clock in/out (Task 13)
  STAFF_CLOCK_IN: "staff:clockIn",
  STAFF_CLOCK_OUT: "staff:clockOut",
  STAFF_GET_STATUS: "staff:getStatus",
  // main -> renderer push
  STAFF_STATUS_EVENT: "staff:status",

  // Toast notifications (Task 15)
  NOTIFY_TEST: "notify:test",
  // main -> renderer push
  NOTIFY_DEEPLINK_EVENT: "notify:deepLink",
});

// Channels the renderer may INVOKE (request/response). Push-only event channels
// (main -> renderer) are intentionally excluded.
const INVOKE_CHANNELS = Object.freeze([
  CHANNELS.APP_GET_VERSION,
  CHANNELS.APP_GET_PLATFORM,
  CHANNELS.PRINTER_LIST,
  CHANNELS.PRINTER_PRINT_RECEIPT,
  CHANNELS.PRINTER_PRINT_TEST,
  CHANNELS.SCALE_LIST_PORTS,
  CHANNELS.SCALE_CONNECT,
  CHANNELS.SCALE_DISCONNECT,
  CHANNELS.DRAWER_OPEN,
  CHANNELS.DRAWER_OPEN_TEST,
  CHANNELS.DB_GET_META,
  CHANNELS.DB_SET_META,
  CHANNELS.DB_GET_CACHED_PRODUCTS,
  CHANNELS.DB_GET_CACHED_PROMOTIONS,
  CHANNELS.DB_REFRESH_CACHE,
  CHANNELS.DB_ENQUEUE_TRANSACTION,
  CHANNELS.DB_GET_QUEUE_STATUS,
  CHANNELS.DB_SET_SYNC_TOKEN,
  CHANNELS.LABEL_PRINT,
  CHANNELS.LABEL_PREVIEW,
  CHANNELS.STAFF_CLOCK_IN,
  CHANNELS.STAFF_CLOCK_OUT,
  CHANNELS.STAFF_GET_STATUS,
  CHANNELS.NOTIFY_TEST,
]);

// Push-only channels the main process may SEND to the renderer.
const EVENT_CHANNELS = Object.freeze([
  CHANNELS.SCALE_WEIGHT_EVENT,
  CHANNELS.DB_SYNC_STATUS_EVENT,
  CHANNELS.STAFF_STATUS_EVENT,
  CHANNELS.NOTIFY_DEEPLINK_EVENT,
]);

module.exports = { CHANNELS, INVOKE_CHANNELS, EVENT_CHANNELS };
