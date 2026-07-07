/**
 * Ambient typing for the allow-listed contextBridge API exposed by the hardened
 * preload (electron/preload.js). The renderer may ONLY reach the main process
 * through `window.api`; no Node globals are available. Every method here maps to
 * a single ipcRenderer.invoke(<channel>) call registered in
 * electron/ipc/registerHandlers.js.
 */

/* ------------------------------------------------------------------ */
/* Shared domain shapes                                               */
/* ------------------------------------------------------------------ */

export type PaperWidthMm = 58 | 80;

export interface ReceiptItem {
  name: string;
  sku: string;
  quantity: number;
  weight_kg: number | null;
  unit_price_display: string;
  discount_display: string | null;
  promotion_name: string | null;
  line_total_display: string;
}

export interface ReceiptData {
  receipt_number: string;
  paid_at: string;
  cashier: string;
  items: ReceiptItem[];
  subtotal_display: string;
  discount_total_display: string;
  tax_total_display: string;
  total_display: string;
  payment_method: "cash" | "card" | "loyalty_points" | "mixed";
  cash_tendered_display: string | null;
  change_display: string | null;
  loyalty_points_earned: number;
  age_verified: boolean;
}

export interface PrinterInfo {
  id: string;
  name: string;
  interface: "usb" | "network";
  widthMm: PaperWidthMm;
}

export interface PrintOptions {
  printerId?: string;
  widthMm?: PaperWidthMm;
}

export interface PrintResult {
  ok: boolean;
  dryRun: boolean;
  outputPath?: string;
  message?: string;
}

export interface SerialPortInfo {
  path: string;
  manufacturer?: string;
}

export interface ScaleConfig {
  path?: string;
  baudRate?: number;
  dataBits?: number;
  parity?: string;
  protocol?: "continuous" | "poll";
}

export interface WeightReading {
  weightKg: number;
  stable: boolean;
}

export interface DrawerOpenOptions {
  printerId?: string;
}

export interface DrawerResult {
  ok: boolean;
  dryRun: boolean;
  outputPath?: string;
  opened: boolean;
  message?: string;
}

export interface LabelPayload {
  productName: string;
  weightKg?: number;
  pricePerKg?: number;
  totalPrice?: number;
  bestBefore?: string | null;
  allergens?: Array<{ name: string; mayContain?: boolean }>;
  barcodeValue: string;
  sku?: string;
}

export interface LabelResult {
  ok: boolean;
  dryRun: boolean;
  outputPath?: string;
  message?: string;
}

export interface CachedProduct {
  variant_id: number;
  product_id: number;
  sku: string;
  barcode: string | null;
  name: string;
  pricing_mode: "fixed" | "weight_based";
  sell_price_pence: number;
  department_id: number | null;
  unit_of_measure: string;
  updated_at: string;
}

export interface CachedPromotion {
  id: number;
  name: string;
  promotion_type: string;
  payload_json: string;
  is_active: boolean;
  updated_at: string;
}

export interface QueueStatus {
  pendingTransactions: number;
  pendingClockEvents: number;
  online: boolean;
  lastSyncedAt: string | null;
  syncing: boolean;
}

export interface ClockStatus {
  clockedIn: boolean;
  staffName: string | null;
  shiftStartedAt: string | null;
}

export type NotificationCategory =
  | "low_stock"
  | "expiry"
  | "food_safety_due"
  | "new_order";

export interface DeepLinkPayload {
  route: string;
  params?: Record<string, string | number>;
}

/* ------------------------------------------------------------------ */
/* The bridge surface                                                 */
/* ------------------------------------------------------------------ */

export interface PosApi {
  app: {
    getVersion(): Promise<string>;
    getPlatform(): Promise<string>;
  };
  printer: {
    list(): Promise<PrinterInfo[]>;
    printReceipt(data: ReceiptData, opts?: PrintOptions): Promise<PrintResult>;
    printTest(opts?: PrintOptions): Promise<PrintResult>;
  };
  scale: {
    listPorts(): Promise<SerialPortInfo[]>;
    connect(config: ScaleConfig): Promise<{ ok: boolean; mock: boolean }>;
    disconnect(): Promise<{ ok: boolean }>;
    onWeight(cb: (reading: WeightReading) => void): () => void;
  };
  drawer: {
    open(opts?: DrawerOpenOptions): Promise<DrawerResult>;
    openTest(opts?: DrawerOpenOptions): Promise<DrawerResult>;
  };
  db: {
    getMeta(key: string): Promise<string | null>;
    setMeta(key: string, value: string): Promise<{ ok: boolean }>;
    getCachedProducts(departmentId?: number): Promise<CachedProduct[]>;
    getCachedPromotions(): Promise<CachedPromotion[]>;
    refreshCache(): Promise<{ ok: boolean; products: number; promotions: number }>;
    enqueueTransaction(payload: unknown): Promise<{ ok: boolean; clientUuid: string }>;
    getQueueStatus(): Promise<QueueStatus>;
    setSyncToken(token: string | null): Promise<{ ok: boolean }>;
    onSyncStatus(cb: (status: QueueStatus) => void): () => void;
  };
  label: {
    print(payload: LabelPayload, opts: { departmentId?: number }): Promise<LabelResult>;
    preview(payload: LabelPayload, opts: { departmentId?: number }): Promise<LabelResult>;
  };
  staff: {
    clockIn(): Promise<ClockStatus>;
    clockOut(): Promise<ClockStatus>;
    getStatus(): Promise<ClockStatus>;
    onStatusChange(cb: (status: ClockStatus) => void): () => void;
  };
  notify: {
    test(category: NotificationCategory): Promise<{ ok: boolean }>;
    onDeepLink(cb: (payload: DeepLinkPayload) => void): () => void;
  };
}

declare global {
  interface Window {
    api?: PosApi;
  }
}

export {};
