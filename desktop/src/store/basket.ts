/**
 * Pure basket helpers (no React, no network) so the money/line maths is fully
 * unit-testable. Money is always integer pence. The authoritative basket lives
 * on the backend order; these helpers drive the local/optimistic view and the
 * running subtotal, and reconcile against server totals.
 */

import type { Order, OrderItem } from "../services/types";

export interface BasketLine {
  id: number;
  variantId: number;
  name: string;
  quantity: number;
  weightKg: number | null;
  unitPricePence: number;
  lineTotalPence: number;
  promotionName: string | null;
  discountPence: number;
}

/** Parse a money display string like "£1.20" / "-£0.30" into integer pence. */
export function parsePenceFromDisplay(display: string | null | undefined): number {
  if (!display) return 0;
  const negative = /-/.test(display);
  const digits = display.replace(/[^0-9.]/g, "");
  if (!digits) return 0;
  const pounds = parseFloat(digits);
  if (!Number.isFinite(pounds)) return 0;
  const pence = Math.round(pounds * 100);
  return negative ? -pence : pence;
}

/** Compute a line total (pence) before discount. */
export function computeLineTotalPence(
  unitPricePence: number,
  quantity: number,
  weightKg: number | null,
): number {
  if (weightKg != null) {
    return Math.round(unitPricePence * weightKg);
  }
  return unitPricePence * quantity;
}

/** Add a line, merging with an existing same-variant fixed-price line. */
export function addLine(lines: BasketLine[], line: BasketLine): BasketLine[] {
  if (line.weightKg == null) {
    const existing = lines.find((l) => l.variantId === line.variantId && l.weightKg == null);
    if (existing) {
      return lines.map((l) =>
        l === existing
          ? {
              ...l,
              quantity: l.quantity + line.quantity,
              lineTotalPence: computeLineTotalPence(
                l.unitPricePence,
                l.quantity + line.quantity,
                null,
              ),
            }
          : l,
      );
    }
  }
  return [...lines, line];
}

/** Remove a line by id. */
export function removeLine(lines: BasketLine[], id: number): BasketLine[] {
  return lines.filter((l) => l.id !== id);
}

/** Set a fixed-price line quantity (>=1); removes when quantity hits 0. */
export function setQuantity(lines: BasketLine[], id: number, quantity: number): BasketLine[] {
  if (quantity <= 0) return removeLine(lines, id);
  return lines.map((l) =>
    l.id === id
      ? { ...l, quantity, lineTotalPence: computeLineTotalPence(l.unitPricePence, quantity, l.weightKg) }
      : l,
  );
}

export function subtotalPence(lines: BasketLine[]): number {
  return lines.reduce((sum, l) => sum + l.lineTotalPence, 0);
}

export function discountTotalPence(lines: BasketLine[]): number {
  return lines.reduce((sum, l) => sum + l.discountPence, 0);
}

export function totalPence(lines: BasketLine[]): number {
  return subtotalPence(lines) - discountTotalPence(lines);
}

/** Map a backend OrderItem into a local basket line. */
export function fromOrderItem(item: OrderItem): BasketLine {
  return {
    id: item.id,
    variantId: item.variant,
    name: item.variant_name_snapshot,
    quantity: item.quantity,
    weightKg: item.weight_kg,
    unitPricePence: parsePenceFromDisplay(item.unit_price_display),
    lineTotalPence: parsePenceFromDisplay(item.line_total_display),
    promotionName: item.promotion_name,
    discountPence: Math.abs(parsePenceFromDisplay(item.discount_display)),
  };
}

/** Map a backend order's items into local basket lines. */
export function linesFromOrder(order: Order | null): BasketLine[] {
  if (!order || !Array.isArray(order.items)) return [];
  return order.items.map(fromOrderItem);
}

/** Format integer pence as a "£x.xx" string. */
export function formatPence(pence: number): string {
  const sign = pence < 0 ? "-" : "";
  const abs = Math.abs(pence);
  return `${sign}£${(abs / 100).toFixed(2)}`;
}
