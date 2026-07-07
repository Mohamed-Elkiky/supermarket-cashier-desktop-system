import { describe, it, expect } from "vitest";
import {
  addLine,
  computeLineTotalPence,
  discountTotalPence,
  formatPence,
  parsePenceFromDisplay,
  removeLine,
  setQuantity,
  subtotalPence,
  totalPence,
  type BasketLine,
} from "../basket";

function line(over: Partial<BasketLine> = {}): BasketLine {
  return {
    id: 1,
    variantId: 100,
    name: "Item",
    quantity: 1,
    weightKg: null,
    unitPricePence: 120,
    lineTotalPence: 120,
    promotionName: null,
    discountPence: 0,
    ...over,
  };
}

describe("money parsing / formatting", () => {
  it("parses display strings to pence", () => {
    expect(parsePenceFromDisplay("£1.20")).toBe(120);
    expect(parsePenceFromDisplay("-£0.30")).toBe(-30);
    expect(parsePenceFromDisplay("£0.00")).toBe(0);
    expect(parsePenceFromDisplay(null)).toBe(0);
    expect(parsePenceFromDisplay("£12.34")).toBe(1234);
  });

  it("formats pence to display strings", () => {
    expect(formatPence(360)).toBe("£3.60");
    expect(formatPence(-30)).toBe("-£0.30");
    expect(formatPence(0)).toBe("£0.00");
  });
});

describe("line totals", () => {
  it("multiplies quantity for fixed-price items", () => {
    expect(computeLineTotalPence(120, 3, null)).toBe(360);
  });
  it("scales by weight for weight-based items", () => {
    expect(computeLineTotalPence(200, 1, 0.5)).toBe(100); // £2.00/kg * 0.5kg
    expect(computeLineTotalPence(123, 1, 0.734)).toBe(90); // rounds
  });
});

describe("basket add/remove/quantity", () => {
  it("merges a fixed-price line with the same variant", () => {
    const lines = addLine([line()], line({ id: 2 }));
    expect(lines).toHaveLength(1);
    expect(lines[0].quantity).toBe(2);
    expect(lines[0].lineTotalPence).toBe(240);
  });

  it("keeps weight-based lines separate", () => {
    const a = line({ id: 1, weightKg: 0.5, lineTotalPence: 60 });
    const b = line({ id: 2, weightKg: 0.7, lineTotalPence: 84 });
    const lines = addLine([a], b);
    expect(lines).toHaveLength(2);
  });

  it("removes a line by id", () => {
    expect(removeLine([line({ id: 1 }), line({ id: 2 })], 1)).toHaveLength(1);
  });

  it("updates quantity and removes at zero", () => {
    const updated = setQuantity([line({ id: 1 })], 1, 3);
    expect(updated[0].quantity).toBe(3);
    expect(updated[0].lineTotalPence).toBe(360);
    expect(setQuantity([line({ id: 1 })], 1, 0)).toHaveLength(0);
  });
});

describe("totals", () => {
  it("sums subtotal, discounts and total", () => {
    const lines = [
      line({ id: 1, lineTotalPence: 360, discountPence: 50 }),
      line({ id: 2, lineTotalPence: 120, discountPence: 0 }),
    ];
    expect(subtotalPence(lines)).toBe(480);
    expect(discountTotalPence(lines)).toBe(50);
    expect(totalPence(lines)).toBe(430);
  });
});
