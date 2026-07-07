import { useEffect, useState } from "react";
import { api, getAuth, onAuthChange } from "./apiClient";
import type { CachedProduct } from "../types/api";
import type { Product, ProductVariant } from "./types";

/**
 * Load products for a department, falling back to the encrypted local cache when
 * offline / the network fails, so the POS keeps working without a connection.
 */
export async function loadProductsWithCacheFallback(departmentId?: number): Promise<Product[]> {
  try {
    if (typeof navigator !== "undefined" && !navigator.onLine) throw new Error("offline");
    const res = await api.getProducts(departmentId);
    return Array.isArray(res) ? res : (res.results ?? []);
  } catch {
    const cached = (await window.api?.db.getCachedProducts?.(departmentId)) ?? [];
    return groupCachedToProducts(cached);
  }
}

function groupCachedToProducts(rows: CachedProduct[]): Product[] {
  const byProduct = new Map<number, Product>();
  for (const r of rows) {
    const pid = r.product_id ?? r.variant_id;
    if (!byProduct.has(pid)) {
      byProduct.set(pid, { id: pid, name: r.name, department: r.department_id ?? 0, variants: [] });
    }
    const variant: ProductVariant = {
      id: r.variant_id,
      product: pid,
      sku: r.sku,
      barcode: r.barcode,
      name: r.name,
      pricing_mode: r.pricing_mode,
      sell_price: r.sell_price_pence,
      unit_of_measure: r.unit_of_measure,
      allergens: [],
    };
    byProduct.get(pid)?.variants.push(variant);
  }
  return [...byProduct.values()];
}

/** Push the current access token to the main-process sync worker. */
export function pushSyncToken(): void {
  const auth = getAuth();
  void window.api?.db.setSyncToken?.(auth?.access ?? null);
}

/** Keep the sync worker's token in step with auth. Returns an unsubscribe fn. */
export function initSyncTokenBridge(): () => void {
  pushSyncToken();
  return onAuthChange(() => pushSyncToken());
}

export interface SyncStatus {
  online: boolean;
  pendingTransactions: number;
  pendingClockEvents: number;
  syncing: boolean;
  lastSyncedAt: string | null;
}

/** Live sync status: main-process queue depth + browser online/offline. */
export function useSyncStatus(): SyncStatus {
  const [status, setStatus] = useState<SyncStatus>({
    online: typeof navigator !== "undefined" ? navigator.onLine : true,
    pendingTransactions: 0,
    pendingClockEvents: 0,
    syncing: false,
    lastSyncedAt: null,
  });

  useEffect(() => {
    let mounted = true;
    window.api?.db
      .getQueueStatus?.()
      .then((s) => mounted && setStatus((p) => ({ ...p, ...s })))
      .catch(() => {});
    const unsub = window.api?.db.onSyncStatus?.((s) => setStatus((p) => ({ ...p, ...s })));
    const on = () => setStatus((p) => ({ ...p, online: true }));
    const off = () => setStatus((p) => ({ ...p, online: false }));
    window.addEventListener("online", on);
    window.addEventListener("offline", off);
    return () => {
      mounted = false;
      unsub?.();
      window.removeEventListener("online", on);
      window.removeEventListener("offline", off);
    };
  }, []);

  return status;
}
