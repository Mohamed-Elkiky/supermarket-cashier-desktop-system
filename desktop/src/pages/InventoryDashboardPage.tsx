import { useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../services/apiClient";
import { formatPence } from "../store/basket";
import { useToast } from "../components/Toast";
import {
  computeMarginPercent,
  parseCsv,
  validateRows,
  csvTemplate,
  buildErrorReportCsv,
  type RowValidation,
} from "./inventoryLogic";
import type { Department, Product } from "../services/types";

interface GridRow {
  variantId: number;
  productId: number;
  sku: string;
  name: string;
  productName: string;
  pricingMode: string;
  sellPence: number;
  costPence: number;
  margin: number;
  unit: string;
  pricePerKgExample?: string;
  stock: number;
  isLowStock: boolean;
}

type SortKey = "name" | "sku" | "stock" | "sellPence" | "margin";

const PAGE_SIZE = 25;

function downloadTextFile(filename: string, content: string, mime = "text/csv") {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export default function InventoryDashboardPage() {
  const toast = useToast();
  const [departments, setDepartments] = useState<Department[]>([]);
  const [departmentId, setDepartmentId] = useState<number | null>(null);
  const [rows, setRows] = useState<GridRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("name");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const [page, setPage] = useState(0);

  // CSV import state
  const [preview, setPreview] = useState<RowValidation[] | null>(null);
  const [importing, setImporting] = useState(false);
  const [progress, setProgress] = useState(0);

  useEffect(() => {
    let active = true;
    api
      .getDepartments()
      .then((d) => {
        if (!active) return;
        setDepartments(d);
        setDepartmentId(d[0]?.id ?? null);
      })
      .catch(() => active && setDepartments([]));
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    setPage(0);
    (async () => {
      try {
        const res = await api.getProducts(departmentId ?? undefined);
        const products: Product[] = Array.isArray(res) ? res : (res.results ?? []);
        const meta = new Map<number, GridRow>();
        const ids: number[] = [];
        for (const p of products) {
          for (const v of p.variants ?? []) {
            ids.push(v.id);
            meta.set(v.id, {
              variantId: v.id,
              productId: p.id,
              sku: v.sku,
              name: v.name,
              productName: p.name,
              pricingMode: v.pricing_mode,
              sellPence: v.sell_price,
              costPence: v.cost_price ?? 0,
              margin: computeMarginPercent(v.sell_price, v.cost_price ?? 0, v.margin_percent),
              unit: v.unit_of_measure,
              pricePerKgExample: v.pricing_mode === "weight_based" ? v.line_total_example : undefined,
              stock: 0,
              isLowStock: false,
            });
          }
        }
        // Stock in batches of 200.
        for (let i = 0; i < ids.length; i += 200) {
          const batch = ids.slice(i, i + 200);
          const stock = await api.getStockBulk(batch, departmentId ?? undefined);
          for (const s of stock) {
            const r = meta.get(s.variant_id);
            if (r) {
              r.stock = s.stock_quantity;
              r.isLowStock = s.is_low_stock;
            }
          }
        }
        if (!active) return;
        setRows([...meta.values()]);
      } catch (err) {
        if (!active) return;
        setError(err instanceof ApiError ? err.messages().join("; ") : "Failed to load inventory");
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [departmentId]);

  const filteredSorted = useMemo(() => {
    const q = search.trim().toLowerCase();
    const filtered = q
      ? rows.filter(
          (r) =>
            r.name.toLowerCase().includes(q) ||
            r.sku.toLowerCase().includes(q) ||
            r.productName.toLowerCase().includes(q),
        )
      : rows;
    const dir = sortDir === "asc" ? 1 : -1;
    return [...filtered].sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      if (typeof av === "number" && typeof bv === "number") return (av - bv) * dir;
      return String(av).localeCompare(String(bv)) * dir;
    });
  }, [rows, search, sortKey, sortDir]);

  const pageRows = filteredSorted.slice(page * PAGE_SIZE, page * PAGE_SIZE + PAGE_SIZE);
  const pageCount = Math.max(1, Math.ceil(filteredSorted.length / PAGE_SIZE));

  function toggleSort(key: SortKey) {
    if (sortKey === key) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setSortKey(key);
      setSortDir("asc");
    }
  }

  async function onFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    const text = await file.text();
    const parsed = parseCsv(text);
    setPreview(validateRows(parsed));
  }

  async function runImport() {
    if (!preview) return;
    const valid = preview.filter((r) => r.valid);
    if (valid.length === 0) {
      toast.addToast("No valid rows to import", "warning");
      return;
    }
    setImporting(true);
    setProgress(0);
    const failed: Array<{ raw: Record<string, string>; errors: string[] }> = [];
    let done = 0;
    // Keep only rows that still need sending, so a retry never re-sends successes.
    const remaining: RowValidation[] = [...preview];
    for (const r of valid) {
      try {
        const product = await api.createProduct(r.product ?? {});
        await api.createVariant(product.id, r.variant ?? {});
        const idx = remaining.indexOf(r);
        if (idx >= 0) remaining.splice(idx, 1);
      } catch (err) {
        const msg = err instanceof ApiError ? err.messages().join("; ") : "import failed";
        failed.push({ raw: r.raw, errors: [msg] });
      }
      done += 1;
      setProgress(Math.round((done / valid.length) * 100));
    }
    setImporting(false);
    setPreview(remaining.length > 0 ? remaining : null);

    if (failed.length > 0) {
      downloadTextFile("import-errors.csv", buildErrorReportCsv(failed));
      toast.addToast(`${valid.length - failed.length} imported, ${failed.length} failed (report downloaded)`, "warning");
    } else {
      toast.addToast(`Imported ${valid.length} product(s)`, "success");
    }
  }

  const validCount = preview?.filter((r) => r.valid).length ?? 0;
  const invalidCount = preview ? preview.length - validCount : 0;

  return (
    <div className="inventory page-pad">
      <div className="inventory__toolbar">
        <h2>Inventory</h2>
        <label>
          Department
          <select
            value={departmentId ?? ""}
            onChange={(e) => setDepartmentId(e.target.value ? Number(e.target.value) : null)}
          >
            <option value="">All</option>
            {departments.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </select>
        </label>
        <input
          type="search"
          placeholder="Search name / SKU…"
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            setPage(0);
          }}
        />
        <div className="spacer" />
        <button className="btn btn--sm" onClick={() => downloadTextFile("product-template.csv", csvTemplate())}>
          Download CSV template
        </button>
        <label className="btn btn--sm" style={{ cursor: "pointer" }}>
          Import CSV
          <input type="file" accept=".csv,text/csv" hidden onChange={(e) => void onFile(e)} />
        </label>
      </div>

      {preview && (
        <div className="import-preview">
          <p>
            Preview: <strong>{validCount}</strong> valid, <strong>{invalidCount}</strong> invalid.
          </p>
          {invalidCount > 0 && (
            <ul className="form-errors">
              {preview
                .filter((r) => !r.valid)
                .slice(0, 8)
                .map((r) => (
                  <li key={r.index}>
                    Row {r.index + 1} ({r.raw.sku || r.raw.name || "?"}): {r.errors.join("; ")}
                  </li>
                ))}
            </ul>
          )}
          {importing && (
            <div className="progress" aria-label="Import progress">
              <div className="progress__bar" style={{ width: `${progress}%` }} />
              <span>{progress}%</span>
            </div>
          )}
          <div className="row-actions">
            <button className="btn" onClick={() => setPreview(null)} disabled={importing}>
              Cancel
            </button>
            <button
              className="btn btn--primary"
              onClick={() => void runImport()}
              disabled={importing || validCount === 0}
            >
              {importing ? "Importing…" : `Import ${validCount} product(s)`}
            </button>
          </div>
        </div>
      )}

      {loading ? (
        <div className="grid--empty">Loading inventory…</div>
      ) : error ? (
        <div className="form-errors">{error}</div>
      ) : filteredSorted.length === 0 ? (
        <div className="grid--empty">No products{search ? " match your search" : ""}</div>
      ) : (
        <>
          <table className="data-table">
            <thead>
              <tr>
                <SortHeader label="Name" k="name" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                <SortHeader label="SKU" k="sku" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                <SortHeader label="Stock" k="stock" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                <th>Cost</th>
                <SortHeader label="Sell" k="sellPence" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                <SortHeader label="Margin" k="margin" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
              </tr>
            </thead>
            <tbody>
              {pageRows.map((r) => (
                <tr key={r.variantId} className={r.isLowStock ? "row--low" : ""}>
                  <td>
                    {r.name}
                    {r.pricePerKgExample && <span className="muted"> · {r.pricePerKgExample}</span>}
                  </td>
                  <td>{r.sku}</td>
                  <td>
                    {r.stock}
                    {r.isLowStock && <span className="badge badge--low">LOW</span>}
                  </td>
                  <td>{formatPence(r.costPence)}</td>
                  <td>
                    {r.pricingMode === "weight_based"
                      ? `${formatPence(r.sellPence)}/kg`
                      : formatPence(r.sellPence)}
                  </td>
                  <td>{r.margin.toFixed(1)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="pager">
            <button className="btn btn--sm" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>
              Prev
            </button>
            <span>
              Page {page + 1} / {pageCount} ({filteredSorted.length} items)
            </span>
            <button
              className="btn btn--sm"
              disabled={page >= pageCount - 1}
              onClick={() => setPage((p) => p + 1)}
            >
              Next
            </button>
          </div>
        </>
      )}
    </div>
  );
}

function SortHeader({
  label,
  k,
  sortKey,
  sortDir,
  onSort,
}: {
  label: string;
  k: SortKey;
  sortKey: SortKey;
  sortDir: "asc" | "desc";
  onSort: (k: SortKey) => void;
}) {
  const active = sortKey === k;
  return (
    <th aria-sort={active ? (sortDir === "asc" ? "ascending" : "descending") : "none"}>
      <button className="th-sort" onClick={() => onSort(k)}>
        {label}
        {active ? (sortDir === "asc" ? " ▲" : " ▼") : ""}
      </button>
    </th>
  );
}
