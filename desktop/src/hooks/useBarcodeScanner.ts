import { useEffect, useRef } from "react";
import {
  barcodeScanner,
  DEFAULT_CONFIG,
  type BarcodeScannerConfig,
} from "../services/barcodeScanner";

const META_KEY = "barcode_scanner_config";

/**
 * Load persisted scanner defaults from the encrypted local DB (via the preload
 * bridge) if available, else fall back to sane constants. Never throws.
 */
async function loadPersistedConfig(): Promise<Partial<BarcodeScannerConfig>> {
  try {
    const raw = await window.api?.db.getMeta(META_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as Partial<BarcodeScannerConfig>;
      return parsed;
    }
  } catch {
    /* fall through to defaults */
  }
  return {};
}

/**
 * Subscribe the calling component to barcode scans. Starts the shared detector
 * on mount and stops it on unmount. `onScan` may change between renders without
 * re-subscribing (kept in a ref).
 */
export function useBarcodeScanner(
  onScan: (code: string) => void,
  opts?: Partial<BarcodeScannerConfig>,
): void {
  const cbRef = useRef(onScan);
  cbRef.current = onScan;

  const optsKey = JSON.stringify(opts ?? {});

  useEffect(() => {
    let active = true;
    let unsubscribe: () => void = () => {};
    const listener = (code: string) => cbRef.current(code);

    void (async () => {
      const persisted = await loadPersistedConfig();
      if (!active) return;
      barcodeScanner.configure({ ...DEFAULT_CONFIG, ...persisted, ...(opts ?? {}) });
      unsubscribe = barcodeScanner.subscribe(listener);
      barcodeScanner.start();
    })();

    return () => {
      active = false;
      unsubscribe();
      barcodeScanner.stop();
    };
    // optsKey captures option changes without depending on object identity.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [optsKey]);
}
