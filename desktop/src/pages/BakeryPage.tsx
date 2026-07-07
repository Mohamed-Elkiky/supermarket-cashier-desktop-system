import { useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../services/apiClient";
import { useToast } from "../components/Toast";
import {
  eligibleForMarkdown,
  markdownPayload,
  selectionSummary,
  toggleSelection,
  type BakeryItem,
} from "./bakeryLogic";
import type { Product } from "../services/types";

function findDepartmentId(depts: Array<{ id: number; name: string }>, keyword: string): number | null {
  const hit = depts.find((d) => d.name.toLowerCase().includes(keyword));
  return hit ? hit.id : null;
}

export default function BakeryPage() {
  const toast = useToast();
  const [departmentId, setDepartmentId] = useState<number | null>(null);
  const [items, setItems] = useState<BakeryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<number[]>([]);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    (async () => {
      try {
        const depts = await api.getDepartments();
        const id = findDepartmentId(depts, "bakery") ?? depts[0]?.id ?? null;
        if (!active) return;
        setDepartmentId(id);

        const res = await api.getProducts(id ?? undefined);
        const products: Product[] = Array.isArray(res) ? res : (res.results ?? []);
        const variantIds: number[] = [];
        const meta = new Map<number, { productId: number; sku: string; name: string; unit: string }>();
        for (const p of products) {
          for (const v of p.variants ?? []) {
            variantIds.push(v.id);
            meta.set(v.id, { productId: p.id, sku: v.sku, name: v.name, unit: v.unit_of_measure });
          }
        }
        const stock = variantIds.length ? await api.getStockBulk(variantIds, id ?? undefined) : [];
        if (!active) return;
        const rows: BakeryItem[] = stock.map((s) => {
          const m = meta.get(s.variant_id);
          return {
            variantId: s.variant_id,
            productId: m?.productId ?? 0,
            sku: s.sku ?? m?.sku ?? "",
            name: s.name ?? m?.name ?? "",
            stockQuantity: s.stock_quantity,
            unitOfMeasure: s.unit_of_measure ?? m?.unit ?? "each",
          };
        });
        setItems(rows);
      } catch (err) {
        if (!active) return;
        setError(err instanceof ApiError ? err.messages().join("; ") : "Failed to load bakery data");
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  const eligible = useMemo(() => eligibleForMarkdown(items), [items]);
  const summary = useMemo(() => selectionSummary(eligible, selected), [eligible, selected]);

  async function applyMarkdowns() {
    if (departmentId == null || summary.count === 0) return;
    setSubmitting(true);
    let ok = 0;
    let managerBlocked = false;
    try {
      for (const item of summary.items) {
        try {
          await api.createLedgerMovement(markdownPayload(item, departmentId));
          ok += 1;
        } catch (err) {
          if (err instanceof ApiError && (err.status === 403 || err.status === 401)) {
            managerBlocked = true;
            break;
          }
          throw err;
        }
      }
      if (managerBlocked) {
        toast.addToast("Markdown requires a department manager sign-in", "error", { blocking: true });
      } else {
        toast.addToast(`Marked down ${ok} item(s)`, "success");
        setItems((list) => list.filter((i) => !selected.includes(i.variantId)));
        setSelected([]);
      }
    } catch {
      toast.addToast("Some markdowns failed", "warning");
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) return <div className="page-pad">Loading bakery production…</div>;
  if (error) return <div className="page-pad form-errors">{error}</div>;

  return (
    <div className="bakery page-pad">
      <h2>Bakery</h2>

      <section>
        <h3>Daily production (remaining stock)</h3>
        {items.length === 0 ? (
          <div className="grid--empty">No bakery products found</div>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>Product</th>
                <th>SKU</th>
                <th>Remaining</th>
                <th>Unit</th>
              </tr>
            </thead>
            <tbody>
              {items.map((i) => (
                <tr key={i.variantId}>
                  <td>{i.name}</td>
                  <td>{i.sku}</td>
                  <td>{i.stockQuantity}</td>
                  <td>{i.unitOfMeasure}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section>
        <h3>End-of-day markdown</h3>
        {eligible.length === 0 ? (
          <p className="muted">Nothing eligible — no remaining stock.</p>
        ) : (
          <>
            <ul className="markdown-list">
              {eligible.map((i) => (
                <li key={i.variantId}>
                  <label className="checkbox">
                    <input
                      type="checkbox"
                      checked={selected.includes(i.variantId)}
                      onChange={() => setSelected((s) => toggleSelection(s, i.variantId))}
                    />
                    {i.name} — {i.stockQuantity} {i.unitOfMeasure}
                  </label>
                </li>
              ))}
            </ul>
            <p className="muted">
              Selected {summary.count} item(s), {summary.totalUnits} unit(s) to mark down.
            </p>
            <button
              className="btn btn--primary"
              disabled={submitting || summary.count === 0}
              onClick={() => void applyMarkdowns()}
            >
              {submitting ? "Applying…" : "Confirm end-of-day markdown"}
            </button>
          </>
        )}
      </section>
    </div>
  );
}
