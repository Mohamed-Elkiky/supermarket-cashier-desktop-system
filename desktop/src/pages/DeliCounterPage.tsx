import { useEffect, useMemo, useReducer, useState } from "react";
import { api } from "../services/apiClient";
import { formatPence } from "../store/basket";
import { useToast } from "../components/Toast";
import {
  deliReducer,
  initialDeliState,
  canConfirmWeight,
  type DeliVariantRef,
} from "./deliFlow";
import type { AllergenLink, Product, ProductVariant } from "../services/types";

function findDepartmentId(names: Array<{ id: number; name: string }>, keyword: string): number | null {
  const hit = names.find((d) => d.name.toLowerCase().includes(keyword));
  return hit ? hit.id : null;
}

function toLabelAllergens(links: AllergenLink[] | undefined) {
  return (links ?? []).map((l) => ({ name: l.allergen.name, mayContain: l.may_contain }));
}

export default function DeliCounterPage() {
  const toast = useToast();
  const [state, dispatch] = useReducer(deliReducer, initialDeliState);
  const [departmentId, setDepartmentId] = useState<number | null>(null);
  const [products, setProducts] = useState<Product[]>([]);
  const [loading, setLoading] = useState(true);
  const [scaleReady, setScaleReady] = useState(false);
  const [manual, setManual] = useState("");
  const [printing, setPrinting] = useState(false);

  // Locate the deli department, then load its products.
  useEffect(() => {
    let active = true;
    setLoading(true);
    api
      .getDepartments()
      .then(async (depts) => {
        const id = findDepartmentId(depts, "deli") ?? depts[0]?.id ?? null;
        if (!active) return;
        setDepartmentId(id);
        const res = await api.getProducts(id ?? undefined);
        if (!active) return;
        setProducts(Array.isArray(res) ? res : (res.results ?? []));
      })
      .catch(() => active && setProducts([]))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, []);

  // Subscribe to the scale during the weigh step.
  useEffect(() => {
    if (state.step !== "weigh") return;
    const scale = window.api?.scale;
    if (!scale) {
      setScaleReady(false);
      return;
    }
    const unsub = scale.onWeight((r) => {
      setScaleReady(true);
      dispatch({ type: "WEIGHT", weightKg: r.weightKg, stable: r.stable });
    });
    scale.connect({}).then(() => setScaleReady(true)).catch(() => setScaleReady(false));
    return () => unsub?.();
  }, [state.step]);

  const variants = useMemo(() => {
    const out: DeliVariantRef[] = [];
    for (const p of products) {
      for (const v of p.variants ?? []) {
        out.push({
          productId: p.id,
          variantId: v.id,
          name: v.name,
          sku: v.sku,
          pricePerKg: v.sell_price,
        });
      }
    }
    return out;
  }, [products]);

  const selectedVariant = useMemo<ProductVariant | null>(() => {
    if (!state.variant) return null;
    for (const p of products) {
      const v = (p.variants ?? []).find((x) => x.id === state.variant?.variantId);
      if (v) return v;
    }
    return null;
  }, [products, state.variant]);

  async function printLabel() {
    if (!state.variant || state.weightKg == null) return;
    dispatch({ type: "PRINT_START" });
    setPrinting(true);
    try {
      let bestBefore: string | null = null;
      if (departmentId != null) {
        try {
          const expiry = await api.checkExpiry(state.variant.variantId, departmentId);
          bestBefore = expiry.batches?.[0]?.best_before_date ?? null;
        } catch {
          /* best-before optional */
        }
      }
      const label = window.api?.label;
      if (!label) {
        toast.addToast("Label printer not available on this device", "warning");
      } else {
        const res = await label.print(
          {
            productName: state.variant.name,
            sku: state.variant.sku,
            weightKg: state.weightKg,
            pricePerKg: state.variant.pricePerKg,
            bestBefore,
            allergens: toLabelAllergens(selectedVariant?.allergens),
            barcodeValue: state.variant.sku,
          },
          { departmentId: departmentId ?? undefined },
        );
        toast.addToast(
          res.dryRun ? `Label preview saved (${res.outputPath ?? "dry-run"})` : "Label printed",
          "success",
        );
      }
      dispatch({ type: "PRINT_DONE" });
    } finally {
      setPrinting(false);
    }
  }

  if (loading) return <div className="page-pad">Loading deli products…</div>;

  return (
    <div className="deli page-pad">
      <h2>Deli counter</h2>

      {state.step === "select" && (
        <>
          <p className="muted">Select a product to weigh.</p>
          {variants.length === 0 ? (
            <div className="grid--empty">No deli products found</div>
          ) : (
            <div className="grid" role="list">
              {variants.map((v) => (
                <button
                  key={v.variantId}
                  role="listitem"
                  className="grid__item"
                  onClick={() => dispatch({ type: "SELECT", variant: v })}
                >
                  <span className="grid__name">{v.name}</span>
                  <span className="grid__meta">{formatPence(v.pricePerKg)}/kg</span>
                  <span className="grid__sku">{v.sku}</span>
                </button>
              ))}
            </div>
          )}
        </>
      )}

      {state.step === "weigh" && state.variant && (
        <div className="weigh-step">
          <h3>{state.variant.name}</h3>
          <p className={`scale-status ${scaleReady ? "ok" : "warn"}`}>
            {scaleReady
              ? state.stable
                ? "Scale stable"
                : "Reading…"
              : "No scale connected — enter weight manually"}
          </p>
          <div className="weigh-readout">
            {state.weightKg != null ? `${state.weightKg.toFixed(3)} kg` : "— kg"}
            {state.stable && <span className="stable-dot" aria-label="stable">●</span>}
          </div>
          <label>
            Manual weight (kg)
            <input
              type="number"
              step="0.001"
              min="0"
              value={manual}
              onChange={(e) => setManual(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  const kg = parseFloat(manual);
                  if (Number.isFinite(kg) && kg > 0) dispatch({ type: "SET_MANUAL_WEIGHT", weightKg: kg });
                }
              }}
            />
          </label>
          <div className="row-actions">
            <button className="btn" onClick={() => dispatch({ type: "BACK" })}>
              Back
            </button>
            <button
              className="btn btn--primary"
              disabled={!canConfirmWeight(state)}
              onClick={() => dispatch({ type: "CONFIRM_WEIGHT" })}
            >
              Confirm weight
            </button>
          </div>
        </div>
      )}

      {state.step === "confirm" && state.variant && (
        <div className="confirm-step">
          <h3>Confirm label</h3>
          <ul className="summary">
            <li>Product: {state.variant.name}</li>
            <li>Weight: {state.weightKg?.toFixed(3)} kg</li>
            <li>
              Price: {formatPence(Math.round(state.variant.pricePerKg * (state.weightKg ?? 0)))} (
              {formatPence(state.variant.pricePerKg)}/kg)
            </li>
          </ul>
          <div className="row-actions">
            <button className="btn" onClick={() => dispatch({ type: "BACK" })}>
              Back
            </button>
            <button className="btn btn--primary" disabled={printing} onClick={() => void printLabel()}>
              {printing ? "Printing…" : "Print label"}
            </button>
          </div>
        </div>
      )}

      {(state.step === "printing" || state.step === "done") && (
        <div className="done-step">
          <h3>{state.step === "printing" ? "Printing…" : "Label sent"}</h3>
          <button className="btn btn--primary" onClick={() => dispatch({ type: "RESET" })}>
            New item
          </button>
        </div>
      )}
    </div>
  );
}
