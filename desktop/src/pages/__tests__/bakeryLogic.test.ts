import { describe, it, expect } from "vitest";
import {
  eligibleForMarkdown,
  toggleSelection,
  selectionSummary,
  markdownPayload,
  type BakeryItem,
} from "../bakeryLogic";

const items: BakeryItem[] = [
  { variantId: 1, productId: 1, sku: "LOAF", name: "Sourdough", stockQuantity: 5, unitOfMeasure: "each" },
  { variantId: 2, productId: 2, sku: "BAG", name: "Bagel", stockQuantity: 0, unitOfMeasure: "each" },
  { variantId: 3, productId: 3, sku: "CROI", name: "Croissant", stockQuantity: 12, unitOfMeasure: "each" },
];

describe("bakery markdown logic", () => {
  it("marks only items with remaining stock as eligible", () => {
    const eligible = eligibleForMarkdown(items);
    expect(eligible.map((i) => i.sku)).toEqual(["LOAF", "CROI"]);
  });

  it("toggles selection immutably", () => {
    let sel: number[] = [];
    sel = toggleSelection(sel, 1);
    expect(sel).toEqual([1]);
    sel = toggleSelection(sel, 3);
    expect(sel).toEqual([1, 3]);
    sel = toggleSelection(sel, 1);
    expect(sel).toEqual([3]);
  });

  it("summarises the selection", () => {
    const summary = selectionSummary(items, [1, 3]);
    expect(summary.count).toBe(2);
    expect(summary.totalUnits).toBe(17);
  });

  it("builds a NEGATIVE markdown movement payload", () => {
    const payload = markdownPayload(items[0], 42);
    expect(payload).toEqual({
      variant_id: 1,
      department_id: 42,
      movement_type: "markdown",
      quantity: -5,
      reason: "End-of-day markdown",
    });
    expect(payload.quantity).toBeLessThan(0);
  });
});
