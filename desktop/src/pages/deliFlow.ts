/**
 * Pure state machine for the deli counter "select -> weigh -> confirm -> print"
 * workflow. Framework-agnostic and fully unit-testable.
 */

export type DeliStep = "select" | "weigh" | "confirm" | "printing" | "done";

export interface DeliVariantRef {
  productId: number;
  variantId: number;
  name: string;
  sku: string;
  pricePerKg: number; // pence/kg
}

export interface DeliState {
  step: DeliStep;
  variant: DeliVariantRef | null;
  weightKg: number | null;
  stable: boolean;
}

export type DeliAction =
  | { type: "SELECT"; variant: DeliVariantRef }
  | { type: "WEIGHT"; weightKg: number; stable: boolean }
  | { type: "SET_MANUAL_WEIGHT"; weightKg: number }
  | { type: "CONFIRM_WEIGHT" }
  | { type: "PRINT_START" }
  | { type: "PRINT_DONE" }
  | { type: "BACK" }
  | { type: "RESET" };

export const initialDeliState: DeliState = {
  step: "select",
  variant: null,
  weightKg: null,
  stable: false,
};

export function deliReducer(state: DeliState, action: DeliAction): DeliState {
  switch (action.type) {
    case "SELECT":
      return { step: "weigh", variant: action.variant, weightKg: null, stable: false };

    case "WEIGHT":
      if (state.step !== "weigh") return state;
      return { ...state, weightKg: action.weightKg, stable: action.stable };

    case "SET_MANUAL_WEIGHT":
      if (state.step !== "weigh") return state;
      // A manual override is treated as a stable, operator-confirmed value.
      return { ...state, weightKg: action.weightKg, stable: true };

    case "CONFIRM_WEIGHT":
      if (state.step !== "weigh") return state;
      if (state.weightKg == null || state.weightKg <= 0) return state; // guard
      return { ...state, step: "confirm" };

    case "PRINT_START":
      if (state.step !== "confirm") return state;
      return { ...state, step: "printing" };

    case "PRINT_DONE":
      if (state.step !== "printing") return state;
      return { ...state, step: "done" };

    case "BACK":
      if (state.step === "weigh") return { ...initialDeliState };
      if (state.step === "confirm") return { ...state, step: "weigh" };
      return state;

    case "RESET":
      return { ...initialDeliState };

    default:
      return state;
  }
}

/** Whether the operator may confirm the current weight. */
export function canConfirmWeight(state: DeliState): boolean {
  return state.step === "weigh" && state.weightKg != null && state.weightKg > 0;
}
