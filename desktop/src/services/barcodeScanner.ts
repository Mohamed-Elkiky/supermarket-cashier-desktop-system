/**
 * Barcode scanner HID input handler.
 *
 * USB barcode scanners present to the OS as HID keyboards: they "type" the
 * barcode very fast and end with a terminator key (usually Enter). This service
 * watches window keydown events and distinguishes a scanner burst (keystrokes
 * arriving within `interKeyMs` of each other) from a human typing (slow gaps).
 *
 * It is framework-agnostic (no React) and uses a pub/sub emitter so multiple
 * screens can subscribe. When a burst is recognised, the buffered keystrokes are
 * suppressed (preventDefault) so they do not also land in a focused input.
 */

export interface BarcodeScannerConfig {
  /** Max gap (ms) between keystrokes to still count as one scan. */
  interKeyMs: number;
  /** Minimum assembled length to be treated as a barcode. */
  minLength: number;
  /** Key that terminates a scan (KeyboardEvent.key). */
  terminator: string;
  /** Optional prefix that scanners prepend; stripped from the result. */
  prefix?: string;
  /** Optional suffix that scanners append; stripped from the result. */
  suffix?: string;
  /** Prevent buffered burst keystrokes from reaching focused inputs. */
  suppressInput: boolean;
}

export const DEFAULT_CONFIG: BarcodeScannerConfig = {
  interKeyMs: 30,
  minLength: 3,
  terminator: "Enter",
  suppressInput: true,
};

export type BarcodeListener = (code: string) => void;

type NowFn = () => number;

export class BarcodeScanner {
  private config: BarcodeScannerConfig;
  private buffer = "";
  private lastTime = 0;
  private readonly listeners = new Set<BarcodeListener>();
  private startCount = 0;
  private readonly now: NowFn;

  constructor(config: Partial<BarcodeScannerConfig> = {}, now?: NowFn) {
    this.config = { ...DEFAULT_CONFIG, ...config };
    // Injectable clock keeps the detector deterministic under fake timers.
    this.now = now ?? (() => (typeof performance !== "undefined" ? performance.now() : Date.now()));
  }

  configure(partial: Partial<BarcodeScannerConfig>): void {
    this.config = { ...this.config, ...partial };
  }

  getConfig(): BarcodeScannerConfig {
    return { ...this.config };
  }

  subscribe(cb: BarcodeListener): () => void {
    this.listeners.add(cb);
    return () => this.listeners.delete(cb);
  }

  unsubscribe(cb: BarcodeListener): void {
    this.listeners.delete(cb);
  }

  /** Attach the window listener. Reference-counted so multiple screens share one. */
  start(): void {
    this.startCount += 1;
    if (this.startCount === 1 && typeof window !== "undefined") {
      window.addEventListener("keydown", this.handleKeyDown, true);
    }
  }

  /** Detach when the last consumer stops. */
  stop(): void {
    if (this.startCount === 0) return;
    this.startCount -= 1;
    if (this.startCount === 0 && typeof window !== "undefined") {
      window.removeEventListener("keydown", this.handleKeyDown, true);
      this.reset();
    }
  }

  /** Feed an event directly (used by tests and by the window listener). */
  handleKeyDown = (event: KeyboardEvent): void => {
    const { key } = event;

    if (key === this.config.terminator) {
      this.finishScan(event);
      return;
    }

    // Only printable single characters are part of a barcode.
    if (key.length !== 1) return;

    const now = this.now();
    const delta = now - this.lastTime;
    this.lastTime = now;

    if (delta <= this.config.interKeyMs) {
      // Continuation of a fast burst -> almost certainly the scanner.
      this.buffer += key;
      if (this.config.suppressInput) event.preventDefault();
    } else {
      // Either the first char of a scan or a human keystroke; start fresh.
      this.buffer = key;
    }
  };

  private finishScan(event: KeyboardEvent): void {
    const raw = this.buffer;
    this.reset();

    let code = raw;
    const { prefix, suffix, minLength, suppressInput } = this.config;
    if (prefix && code.startsWith(prefix)) code = code.slice(prefix.length);
    if (suffix && code.endsWith(suffix)) code = code.slice(0, code.length - suffix.length);

    if (code.length >= minLength) {
      if (suppressInput) event.preventDefault();
      this.emit(code);
    }
    // Otherwise it was human typing / too short — let the terminator act normally.
  }

  private emit(code: string): void {
    for (const cb of this.listeners) {
      try {
        cb(code);
      } catch {
        /* one bad subscriber must not break the others */
      }
    }
  }

  private reset(): void {
    this.buffer = "";
    this.lastTime = 0;
  }
}

/** Shared singleton used by the React hook so screens share one listener. */
export const barcodeScanner = new BarcodeScanner();

/** Factory for isolated instances (tests, embedded panels). */
export function createBarcodeScanner(
  config?: Partial<BarcodeScannerConfig>,
  now?: NowFn,
): BarcodeScanner {
  return new BarcodeScanner(config, now);
}
