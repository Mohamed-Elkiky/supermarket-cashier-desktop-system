import { describe, it, expect } from "vitest";
import { deliReducer, initialDeliState, canConfirmWeight, type DeliVariantRef } from "../deliFlow";

const variant: DeliVariantRef = {
  productId: 1,
  variantId: 10,
  name: "Honey Ham",
  sku: "HAM01",
  pricePerKg: 350,
};

describe("deli workflow state machine", () => {
  it("runs select -> weigh -> confirm -> printing -> done", () => {
    let s = initialDeliState;
    expect(s.step).toBe("select");

    s = deliReducer(s, { type: "SELECT", variant });
    expect(s.step).toBe("weigh");
    expect(s.variant).toEqual(variant);

    s = deliReducer(s, { type: "WEIGHT", weightKg: 0.734, stable: true });
    expect(s.weightKg).toBe(0.734);
    expect(canConfirmWeight(s)).toBe(true);

    s = deliReducer(s, { type: "CONFIRM_WEIGHT" });
    expect(s.step).toBe("confirm");

    s = deliReducer(s, { type: "PRINT_START" });
    expect(s.step).toBe("printing");

    s = deliReducer(s, { type: "PRINT_DONE" });
    expect(s.step).toBe("done");
  });

  it("cannot confirm without a positive weight", () => {
    let s = deliReducer(initialDeliState, { type: "SELECT", variant });
    expect(canConfirmWeight(s)).toBe(false);
    s = deliReducer(s, { type: "CONFIRM_WEIGHT" });
    expect(s.step).toBe("weigh"); // guarded
  });

  it("treats a manual weight as stable/confirmed-able", () => {
    let s = deliReducer(initialDeliState, { type: "SELECT", variant });
    s = deliReducer(s, { type: "SET_MANUAL_WEIGHT", weightKg: 0.5 });
    expect(s.stable).toBe(true);
    expect(canConfirmWeight(s)).toBe(true);
  });

  it("supports BACK and RESET", () => {
    let s = deliReducer(initialDeliState, { type: "SELECT", variant });
    s = deliReducer(s, { type: "WEIGHT", weightKg: 1, stable: true });
    s = deliReducer(s, { type: "CONFIRM_WEIGHT" });
    s = deliReducer(s, { type: "BACK" });
    expect(s.step).toBe("weigh");
    s = deliReducer(s, { type: "RESET" });
    expect(s.step).toBe("select");
    expect(s.variant).toBeNull();
  });
});
