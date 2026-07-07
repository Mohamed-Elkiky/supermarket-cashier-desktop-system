/**
 * Pure bakery end-of-day markdown logic. Framework-agnostic + unit-testable.
 */

import type { LedgerMovementPayload } from "../services/types";

export interface BakeryItem {
  variantId: number;
  productId: number;
  sku: string;
  name: string;
  stockQuantity: number;
  unitOfMeasure: string;
}

/** Items eligible for end-of-day markdown: those with remaining stock. */
export function eligibleForMarkdown(items: BakeryItem[]): BakeryItem[] {
  return items.filter((i) => i.stockQuantity > 0);
}

/** Toggle a variant id in the selection set (immutable). */
export function toggleSelection(selected: number[], id: number): number[] {
  return selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id];
}

/** Summarise the current selection. */
export function selectionSummary(
  items: BakeryItem[],
  selectedIds: number[],
): { count: number; totalUnits: number; items: BakeryItem[] } {
  const chosen = items.filter((i) => selectedIds.includes(i.variantId));
  return {
    count: chosen.length,
    totalUnits: chosen.reduce((sum, i) => sum + i.stockQuantity, 0),
    items: chosen,
  };
}

/**
 * Build the markdown ledger movement for an item. Markdown is an OUTBOUND
 * movement so the quantity MUST be negative (the full remaining stock).
 */
export function markdownPayload(
  item: BakeryItem,
  departmentId: number,
  reason = "End-of-day markdown",
): LedgerMovementPayload {
  return {
    variant_id: item.variantId,
    department_id: departmentId,
    movement_type: "markdown",
    quantity: -Math.abs(item.stockQuantity),
    reason,
  };
}
