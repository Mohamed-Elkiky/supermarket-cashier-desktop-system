/**
 * Shared API client for the Django REST backend.
 *
 * - Base URL from VITE_API_BASE (default http://localhost:8000/api/v1).
 * - Every success response is { success:true, data:<payload> }; this client
 *   unwraps `.data`. Errors are { success:false, error:{code,status,errors} }
 *   and are thrown as a typed ApiError.
 * - Auth: bearer access token on every call; on 401 it refreshes once and
 *   retries; if refresh fails it clears auth (forcing re-login).
 * - Tokens live in memory only (never localStorage) per the CSP/security model.
 */

import type {
  AuthTokens,
  CheckoutPayload,
  Customer,
  Department,
  ExpiryInfo,
  LedgerMovementPayload,
  LineTotalResult,
  Order,
  Product,
  ProductVariant,
  StockRow,
} from "./types";
import type { ReceiptData } from "../types/api";

export const API_BASE: string =
  (typeof import.meta !== "undefined" &&
    (import.meta as { env?: Record<string, string> }).env?.VITE_API_BASE) ||
  "http://localhost:8000/api/v1";

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly errors: unknown[];

  constructor(code: string, status: number, errors: unknown[] = [], message?: string) {
    super(message || code);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
    this.errors = errors;
  }

  /** Human-readable list of error messages for surfacing in the UI. */
  messages(): string[] {
    if (Array.isArray(this.errors) && this.errors.length > 0) {
      return this.errors.map((e) =>
        typeof e === "string" ? e : (e as { message?: string })?.message || JSON.stringify(e),
      );
    }
    return [this.message];
  }
}

/* ------------------------------ token store ----------------------------- */

let tokens: AuthTokens | null = null;
type AuthListener = (t: AuthTokens | null) => void;
const authListeners = new Set<AuthListener>();

export function getAuth(): AuthTokens | null {
  return tokens;
}

export function isAuthenticated(): boolean {
  return tokens !== null;
}

export function clearAuth(): void {
  tokens = null;
  authListeners.forEach((l) => l(null));
}

export function onAuthChange(cb: AuthListener): () => void {
  authListeners.add(cb);
  return () => authListeners.delete(cb);
}

function setTokens(next: AuthTokens): void {
  tokens = next;
  authListeners.forEach((l) => l(next));
}

/** Test seam. */
export function __setTokensForTest(next: AuthTokens | null): void {
  tokens = next;
}

/* ------------------------------ core request ---------------------------- */

interface RequestOptions {
  method?: string;
  body?: unknown;
  auth?: boolean;
  _retry?: boolean;
}

async function parseJson(res: Response): Promise<unknown> {
  try {
    return await res.json();
  } catch {
    return null;
  }
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, auth = true, _retry = false } = options;
  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (auth && tokens) headers["Authorization"] = `Bearer ${tokens.access}`;

  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  if (res.status === 401 && auth && tokens && !_retry) {
    const refreshed = await tryRefresh();
    if (refreshed) {
      return request<T>(path, { ...options, _retry: true });
    }
    clearAuth();
  }

  const json = (await parseJson(res)) as
    | { success: true; data: T }
    | { success: false; error: { code: string; status: number; errors: unknown[] } }
    | null;

  if (res.ok && json && "success" in json && json.success) {
    return json.data;
  }

  if (json && "error" in json && json.error) {
    const e = json.error;
    throw new ApiError(e.code || "error", e.status || res.status, e.errors || [], e.code);
  }
  throw new ApiError("http_error", res.status, [], `HTTP ${res.status}`);
}

async function tryRefresh(): Promise<boolean> {
  if (!tokens) return false;
  try {
    const res = await fetch(`${API_BASE}/auth/refresh/`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ refresh: tokens.refresh }),
    });
    const json = (await parseJson(res)) as
      | { success: true; data: { access: string; refresh?: string } }
      | null;
    if (res.ok && json && json.success && json.data?.access) {
      setTokens({
        ...tokens,
        access: json.data.access,
        refresh: json.data.refresh || tokens.refresh,
      });
      return true;
    }
    return false;
  } catch {
    return false;
  }
}

/* ------------------------------ auth ------------------------------------ */

export async function login(email: string, password: string): Promise<AuthTokens> {
  const data = await request<AuthTokens>("/auth/login/", {
    method: "POST",
    body: { email, password },
    auth: false,
  });
  setTokens(data);
  return data;
}

export function logout(): void {
  clearAuth();
}

/* ------------------------------ endpoints ------------------------------- */

export const api = {
  getDepartments: () => request<Department[]>("/departments/"),

  lookupBarcode: (barcode: string) =>
    request<ProductVariant>(`/inventory/barcode/?barcode=${encodeURIComponent(barcode)}`),

  getProducts: (departmentId?: number) =>
    request<Product[] | { results: Product[] }>(
      departmentId ? `/inventory/products/?department=${departmentId}` : "/inventory/products/",
    ),

  computeLineTotal: (productId: number, variantId: number, payload: { weight_kg?: number; quantity?: number }) =>
    request<LineTotalResult>(`/inventory/products/${productId}/variants/${variantId}/line-total/`, {
      method: "POST",
      body: payload,
    }),

  checkExpiry: (variantPk: number, departmentId: number) =>
    request<ExpiryInfo>(`/inventory/expiry/${variantPk}/?department=${departmentId}`),

  createOrder: () => request<Order>("/pos/orders/", { method: "POST", body: {} }),

  addOrderItem: (orderId: number, payload: { variant_id: number; quantity?: number; weight_kg?: number }) =>
    request<Order>(`/pos/orders/${orderId}/items/`, { method: "POST", body: payload }),

  removeOrderItem: (orderId: number, itemId: number) =>
    request<Order>(`/pos/orders/${orderId}/items/${itemId}/`, { method: "DELETE" }),

  confirmOrder: (orderId: number) =>
    request<Order>(`/pos/orders/${orderId}/confirm/`, { method: "POST", body: {} }),

  checkout: (orderId: number, payload: CheckoutPayload) =>
    request<Order>(`/pos/orders/${orderId}/checkout/`, { method: "POST", body: payload }),

  getReceipt: (orderId: number) => request<ReceiptData>(`/pos/orders/${orderId}/receipt/`),

  getVariant: (productId: number, variantId: number) =>
    request<ProductVariant>(`/inventory/products/${productId}/variants/${variantId}/`),

  getStockBulk: (variantIds: number[], departmentId?: number) =>
    request<StockRow[]>("/inventory/stock/bulk/", {
      method: "POST",
      body: { variant_ids: variantIds, department_id: departmentId },
    }),

  createLedgerMovement: (payload: LedgerMovementPayload) =>
    request<unknown>("/inventory/ledger/movements/", { method: "POST", body: payload }),

  createProduct: (payload: Record<string, unknown>) =>
    request<Product>("/inventory/products/", { method: "POST", body: payload }),

  createVariant: (productId: number, payload: Record<string, unknown>) =>
    request<ProductVariant>(`/inventory/products/${productId}/variants/`, {
      method: "POST",
      body: payload,
    }),

  searchCustomers: (q: string) =>
    request<Customer[]>(`/loyalty/customers/search/?q=${encodeURIComponent(q)}`),

  redeemLoyalty: (customerId: number, points: number) =>
    request<Customer>(`/loyalty/customers/${customerId}/loyalty/redeem/`, {
      method: "POST",
      body: { points },
    }),
};

export type Api = typeof api;
