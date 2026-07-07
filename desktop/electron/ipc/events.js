"use strict";

/**
 * Central main -> renderer push channel. Feature modules (scale, sync worker,
 * staff clock, notifier) call sendToRenderer() rather than reaching into a
 * BrowserWindow themselves, so there is exactly one place that talks to the
 * renderer's webContents.
 */

let mainWindow = null;

function setMainWindow(win) {
  mainWindow = win;
}

function sendToRenderer(channel, payload) {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send(channel, payload);
  }
}

module.exports = { setMainWindow, sendToRenderer };
