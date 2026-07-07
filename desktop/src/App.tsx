import { useEffect, useState } from "react";
import { ToastProvider } from "./components/Toast";
import { ShortcutsProvider } from "./hooks/useShortcuts";
import { initSyncTokenBridge, useSyncStatus } from "./services/offline";
import CheckoutPage from "./pages/CheckoutPage";
import DeliCounterPage from "./pages/DeliCounterPage";
import BakeryPage from "./pages/BakeryPage";
import InventoryDashboardPage from "./pages/InventoryDashboardPage";

type View = "checkout" | "deli" | "bakery" | "inventory";

const NAV: Array<{ id: View; label: string }> = [
  { id: "checkout", label: "Checkout" },
  { id: "deli", label: "Deli" },
  { id: "bakery", label: "Bakery" },
  { id: "inventory", label: "Inventory" },
];

/**
 * Application shell: branded header, primary navigation, and the active screen.
 * Additional screens (deli, bakery, inventory) are added to NAV as they land.
 */
function SyncBadge() {
  const status = useSyncStatus();
  const label = status.online ? "Online" : "Offline";
  const cls = status.online ? "sync-badge sync-badge--online" : "sync-badge sync-badge--offline";
  return (
    <span className={cls} title={status.lastSyncedAt ? `Last synced ${status.lastSyncedAt}` : undefined}>
      {status.syncing ? "Syncing…" : label}
      {status.pendingTransactions > 0 && ` · ${status.pendingTransactions} queued`}
    </span>
  );
}

function App() {
  const [view, setView] = useState<View>("checkout");
  const [appVersion, setAppVersion] = useState<string>("");

  useEffect(() => {
    window.api?.app?.getVersion?.().then(setAppVersion).catch(() => setAppVersion(""));
    const unsubToken = initSyncTokenBridge();
    // Deep-link from a clicked toast notification -> navigate to the screen.
    const unsubLink = window.api?.notify?.onDeepLink?.((payload) => {
      const route = payload?.route;
      if (route === "inventory" || route === "food_safety") setView("inventory");
      else if (route === "checkout" || route === "new_order") setView("checkout");
    });
    return () => {
      unsubToken();
      unsubLink?.();
    };
  }, []);

  return (
    <ToastProvider>
      <ShortcutsProvider>
        <div className="app-shell">
        <header className="app-header">
          <div className="app-header__brand">
            <span className="app-header__logo" aria-hidden="true">
              🛒
            </span>
            <h1 className="app-header__title">Supermarket POS</h1>
          </div>
          <nav className="app-nav" aria-label="Primary">
            {NAV.map((n) => (
              <button
                key={n.id}
                className={`app-nav__link ${view === n.id ? "app-nav__link--active" : ""}`}
                aria-current={view === n.id ? "page" : undefined}
                onClick={() => setView(n.id)}
              >
                {n.label}
              </button>
            ))}
          </nav>
          <SyncBadge />
          {appVersion && <span className="app-header__version">v{appVersion}</span>}
        </header>

        <main className="app-body">
          {view === "checkout" && <CheckoutPage />}
          {view === "deli" && <DeliCounterPage />}
          {view === "bakery" && <BakeryPage />}
          {view === "inventory" && <InventoryDashboardPage />}
        </main>
        </div>
      </ShortcutsProvider>
    </ToastProvider>
  );
}

export default App;
