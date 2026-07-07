# Electron security hardening

This document lists every renderer/main-process security control in the desktop
client, why it exists, and the file it lives in. It follows the Electron security
checklist and OWASP guidance for desktop apps.

The renderer is treated as **untrusted**: it may only reach the operating system,
hardware, network privileges, and local database through the narrow, typed,
allow-listed bridge in `preload.js`. There is no direct Node access from any page.

## Controls

| # | Control | Why | Where |
|---|---------|-----|-------|
| 1 | `contextIsolation: true` on every `BrowserWindow` | Keeps the preload's privileged objects in a separate JS world from page scripts, so a compromised page cannot reach into them. | `electron/main.js` → `HARDENED_WEB_PREFERENCES`, splash window |
| 2 | `nodeIntegration: false` (+ `nodeIntegrationInWorker`, `nodeIntegrationInSubFrames` false) | Denies the renderer `require`, `process`, `Buffer`, etc. XSS cannot become RCE. | `electron/main.js` → `HARDENED_WEB_PREFERENCES` |
| 3 | `sandbox: true` | Runs the renderer in an OS sandbox; the preload only gets a limited API surface. | `electron/main.js` → `HARDENED_WEB_PREFERENCES` |
| 4 | `webSecurity: true`, `allowRunningInsecureContent: false`, `experimentalFeatures: false` | Enforces same-origin policy, blocks mixed content, disables experimental web features. | `electron/main.js` → `HARDENED_WEB_PREFERENCES` |
| 5 | Dedicated `preload.js` via `path.join(__dirname, "preload.js")` | Single, audited entry point for privileged capability. | `electron/main.js`, `electron/preload.js` |
| 6 | `contextBridge.exposeInMainWorld("api", …)` — allow-listed methods only | The renderer sees a fixed, typed API. No `ipcRenderer`, `require`, `fs`, `process`, or `Buffer` is ever placed on `window`. | `electron/preload.js` |
| 7 | Centralised IPC with a frozen channel allow-list | Every `ipcMain.handle` is registered in one place from a fixed constant list; unknown/dynamic channels cannot be registered. | `electron/ipc/channels.js`, `electron/ipc/registerHandlers.js` |
| 8 | Per-handler payload validation | Each handler validates/parses its payload at the top and throws on anything unexpected. | `electron/ipc/registerHandlers.js` |
| 9 | Push events sanitised | Main→renderer events strip the Electron event object; the renderer callback only sees the payload. | `electron/preload.js` (`subscribe`), `electron/ipc/events.js` |
| 10 | `setWindowOpenHandler` denies all `window.open` / `target=_blank` | Prevents arbitrary popups / navigations; external links are only opened via `shell.openExternal` after an https + host allow-list check. | `electron/main.js` → `hardenNavigation`, `maybeOpenExternal` |
| 11 | `will-navigate` blocked off-origin | The main window can only navigate within its own origin (dev server in dev, `file://` in prod). | `electron/main.js` → `isSameOriginNavigation` |
| 12 | `will-attach-webview` denied | `<webview>` embedding is refused outright. | `electron/main.js` → `hardenNavigation` |
| 13 | Strict Content-Security-Policy via `onHeadersReceived` | Locks scripts to `'self'`, forbids object/base/frame-ancestors, and only allows `connect-src` to self + the backend API (`http://localhost:8000`, `ws://localhost:8000`). | `electron/main.js` → `buildCsp`, `installCsp` |
| 14 | `X-Content-Type-Options: nosniff` | Prevents MIME sniffing of responses. | `electron/main.js` → `installCsp` |
| 15 | `@electron/remote` NOT used | The remote module is a well-known privilege-escalation vector; it is neither installed nor enabled. | verified by grep in CI/DoD |
| 16 | Single-instance lock | One running instance keeps the encrypted DB and tray coherent and avoids races. | `electron/main.js` → `requestSingleInstanceLock` |

## Content-Security-Policy details

Production policy (strict):

```
default-src 'self';
script-src 'self';
style-src 'self' 'unsafe-inline';
img-src 'self' data:;
font-src 'self' data:;
connect-src 'self' http://localhost:8000 ws://localhost:8000;
object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'
```

- `connect-src` intentionally includes the backend origin `http://localhost:8000`
  (REST) and `ws://localhost:8000` (future websocket/live features) so the
  renderer's API client can reach the Django API.
- `script-src 'self'` has **no** `'unsafe-inline'` in production.
- `style-src` keeps `'unsafe-inline'` because React/CSS injects inline styles;
  this does not enable script execution.

**Dev-only relaxation:** when running against the Vite dev server, `script-src`
also allows `'unsafe-inline' 'unsafe-eval'` and `connect-src` adds the Vite HMR
origin/websocket. This is required for Vite + React Refresh and applies *only*
when `isDev()` is true (never in a packaged build). The CSP is still active in
dev — it simply permits the tooling — so the shell loads without CSP console
errors.

## Notes for reviewers

- To audit: `grep -R "nodeIntegration: true"`, `grep -R "contextIsolation: false"`,
  `grep -R "@electron/remote"` should all return **nothing**.
- The preload never exposes `require`, `ipcRenderer`, `process`, `fs`, or `Buffer`
  to `window`; only the `window.api` object defined in `preload.js`.
