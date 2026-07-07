/**
 * Checkout screen state + actions. Wraps the apiClient and holds the current
 * REAL backend order. Promotions/discounts are NEVER computed here — we render
 * whatever the backend applies on confirm.
 */

import { createStore } from "./createStore";
import { api, ApiError, getAuth, login as apiLogin, logout as apiLogout } from "../services/apiClient";
import type { AuthTokens, Customer, Department, Order, ProductVariant } from "../services/types";
import { linesFromOrder, totalPence, type BasketLine } from "./basket";

export interface CheckoutState {
  auth: AuthTokens | null;
  departments: Department[];
  selectedDepartmentId: number | null;
  order: Order | null;
  confirmed: boolean;
  customer: Customer | null;
  busy: boolean;
  loadingDepartments: boolean;
  error: string[] | null;
}

const initialState: CheckoutState = {
  auth: getAuth(),
  departments: [],
  selectedDepartmentId: null,
  order: null,
  confirmed: false,
  customer: null,
  busy: false,
  loadingDepartments: false,
  error: null,
};

export const checkoutStore = createStore<CheckoutState>(initialState);
const { getState, setState } = checkoutStore;

function toErrorMessages(err: unknown): string[] {
  if (err instanceof ApiError) return err.messages();
  if (err instanceof Error) return [err.message];
  return ["Unexpected error"];
}

export function clearError(): void {
  setState({ error: null });
}

export function basketLines(): BasketLine[] {
  return linesFromOrder(getState().order);
}

/* ------------------------------ auth ------------------------------------ */

export async function login(email: string, password: string): Promise<boolean> {
  setState({ busy: true, error: null });
  try {
    const auth = await apiLogin(email, password);
    setState({ auth });
    await loadDepartments();
    return true;
  } catch (err) {
    setState({ error: toErrorMessages(err) });
    return false;
  } finally {
    setState({ busy: false });
  }
}

export function logout(): void {
  apiLogout();
  setState({ ...initialState, auth: null });
}

/* ------------------------------ departments ----------------------------- */

export async function loadDepartments(): Promise<void> {
  setState({ loadingDepartments: true, error: null });
  try {
    const departments = await api.getDepartments();
    setState({
      departments,
      selectedDepartmentId: departments[0]?.id ?? null,
    });
  } catch (err) {
    setState({ error: toErrorMessages(err) });
  } finally {
    setState({ loadingDepartments: false });
  }
}

export function selectDepartment(id: number): void {
  setState({ selectedDepartmentId: id });
}

/* ------------------------------ order/basket ---------------------------- */

async function ensureOrder(): Promise<Order> {
  const existing = getState().order;
  if (existing) return existing;
  const order = await api.createOrder();
  setState({ order, confirmed: false });
  return order;
}

export async function addVariant(
  variant: ProductVariant,
  opts: { quantity?: number; weightKg?: number } = {},
): Promise<boolean> {
  setState({ busy: true, error: null });
  try {
    const order = await ensureOrder();
    const payload: { variant_id: number; quantity?: number; weight_kg?: number } = {
      variant_id: variant.id,
    };
    if (opts.weightKg != null) payload.weight_kg = opts.weightKg;
    else payload.quantity = opts.quantity ?? 1;
    const updated = await api.addOrderItem(order.id, payload);
    setState({ order: updated, confirmed: false });
    return true;
  } catch (err) {
    setState({ error: toErrorMessages(err) });
    return false;
  } finally {
    setState({ busy: false });
  }
}

export async function removeItem(itemId: number): Promise<void> {
  const order = getState().order;
  if (!order) return;
  setState({ busy: true, error: null });
  try {
    const updated = await api.removeOrderItem(order.id, itemId);
    setState({ order: updated, confirmed: false });
  } catch (err) {
    setState({ error: toErrorMessages(err) });
  } finally {
    setState({ busy: false });
  }
}

export async function confirmOrder(): Promise<boolean> {
  const order = getState().order;
  if (!order) return false;
  setState({ busy: true, error: null });
  try {
    const updated = await api.confirmOrder(order.id);
    setState({ order: updated, confirmed: true });
    return true;
  } catch (err) {
    setState({ error: toErrorMessages(err) });
    return false;
  } finally {
    setState({ busy: false });
  }
}

export function setCustomer(customer: Customer | null): void {
  setState({ customer });
}

export async function checkout(
  payload: import("../services/types").CheckoutPayload,
): Promise<Order | null> {
  const order = getState().order;
  if (!order) return null;

  // Offline: complete the sale locally and enqueue it for background replay
  // (idempotent by client_uuid). Server promotions remain authoritative on sync.
  if (typeof navigator !== "undefined" && !navigator.onLine) {
    const lines = linesFromOrder(order);
    const offlinePayload = {
      items: lines.map((l) => ({
        variant_id: l.variantId,
        quantity: l.weightKg == null ? l.quantity : undefined,
        weight_kg: l.weightKg ?? undefined,
      })),
      payment: { ...payload, customer_id: getState().customer?.id },
      estimatedTotalPence: order.total_pence ?? totalPence(lines),
    };
    try {
      await window.api?.db.enqueueTransaction(offlinePayload);
      resetSale();
      return { ...order, status: "queued_offline" };
    } catch (err) {
      setState({ error: toErrorMessages(err) });
      return null;
    }
  }

  setState({ busy: true, error: null });
  try {
    const paid = await api.checkout(order.id, {
      ...payload,
      customer_id: getState().customer?.id,
    });
    setState({ order: paid });
    return paid;
  } catch (err) {
    setState({ error: toErrorMessages(err) });
    return null;
  } finally {
    setState({ busy: false });
  }
}

/** Reset the basket for the next sale (keeps auth + department selection). */
export function resetSale(): void {
  setState({ order: null, confirmed: false, customer: null, error: null });
}
