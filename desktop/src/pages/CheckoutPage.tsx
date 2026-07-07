import { useEffect, useMemo, useRef, useState } from "react";
import { checkoutStore } from "../store/checkoutStore";
import * as actions from "../store/checkoutStore";
import { api } from "../services/apiClient";
import { formatPence, linesFromOrder } from "../store/basket";
import type { Customer, Product, ProductVariant } from "../services/types";
import { useBarcodeScanner } from "../hooks/useBarcodeScanner";
import { useToast } from "../components/Toast";
import { Modal } from "../components/Modal";
import { loadProductsWithCacheFallback } from "../services/offline";
import { useShortcuts } from "../hooks/useShortcuts";

const { useStore } = checkoutStore;

/* ------------------------------ Login gate ------------------------------ */

function LoginForm() {
  const busy = useStore((s) => s.busy);
  const error = useStore((s) => s.error);
  const [email, setEmail] = useState("admin@store.com");
  const [password, setPassword] = useState("");

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    await actions.login(email.trim(), password);
  }

  return (
    <div className="login-wrap">
      <form className="login-card" onSubmit={onSubmit} aria-label="Sign in">
        <h2>Cashier sign in</h2>
        <label>
          Email
          <input
            type="email"
            value={email}
            autoFocus
            onChange={(e) => setEmail(e.target.value)}
            required
          />
        </label>
        <label>
          Password
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </label>
        {error && (
          <ul className="form-errors" role="alert">
            {error.map((m, i) => (
              <li key={i}>{m}</li>
            ))}
          </ul>
        )}
        <button type="submit" className="btn btn--primary" disabled={busy}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}

/* ---------------------------- Department tabs --------------------------- */

function DepartmentTabs() {
  const departments = useStore((s) => s.departments);
  const selected = useStore((s) => s.selectedDepartmentId);
  const loading = useStore((s) => s.loadingDepartments);

  if (loading) return <div className="tabs tabs--loading">Loading departments…</div>;
  if (departments.length === 0) return <div className="tabs tabs--empty">No departments</div>;

  return (
    <div className="tabs" role="tablist" aria-label="Departments">
      {departments.map((d) => (
        <button
          key={d.id}
          role="tab"
          aria-selected={d.id === selected}
          className={`tab ${d.id === selected ? "tab--active" : ""}`}
          onClick={() => actions.selectDepartment(d.id)}
        >
          {d.name}
        </button>
      ))}
    </div>
  );
}

/* ---------------------------- Weight prompt ----------------------------- */

function WeightPromptModal({
  variant,
  onCancel,
  onConfirm,
}: {
  variant: ProductVariant;
  onCancel: () => void;
  onConfirm: (weightKg: number) => void;
}) {
  const [weight, setWeight] = useState("");
  const [scaleWeight, setScaleWeight] = useState<number | null>(null);
  const pricePerKg = variant.sell_price;

  useEffect(() => {
    // Auto-fill from a connected scale (stable readings only).
    const unsub = window.api?.scale.onWeight((r) => {
      setScaleWeight(r.weightKg);
      setWeight(r.weightKg.toFixed(3));
    });
    window.api?.scale.connect({}).catch(() => {});
    return () => unsub?.();
  }, []);

  const kg = parseFloat(weight);
  const valid = Number.isFinite(kg) && kg > 0;
  const linePreview = valid ? formatPence(Math.round(pricePerKg * kg)) : "—";

  return (
    <Modal
      open
      title={`Weigh: ${variant.name}`}
      onClose={onCancel}
      footer={
        <>
          <button className="btn" onClick={onCancel}>
            Cancel (Esc)
          </button>
          <button
            className="btn btn--primary"
            disabled={!valid}
            onClick={() => valid && onConfirm(kg)}
          >
            Add ({linePreview})
          </button>
        </>
      }
    >
      <p>
        Price per kg: <strong>{formatPence(pricePerKg)}</strong>
      </p>
      <label>
        Weight (kg)
        <input
          type="number"
          step="0.001"
          min="0"
          value={weight}
          autoFocus
          onChange={(e) => setWeight(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && valid) onConfirm(kg);
          }}
        />
      </label>
      <p className="muted">
        {scaleWeight != null
          ? `Scale: ${scaleWeight.toFixed(3)} kg (stable) — you may override`
          : "No scale reading yet — enter weight manually"}
      </p>
    </Modal>
  );
}

/* ---------------------------- Product entry ----------------------------- */

function ProductEntry({ onNeedsWeight }: { onNeedsWeight: (v: ProductVariant) => void }) {
  const selectedDepartmentId = useStore((s) => s.selectedDepartmentId);
  const busy = useStore((s) => s.busy);
  const toast = useToast();
  const [products, setProducts] = useState<Product[]>([]);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState("");
  const [barcode, setBarcode] = useState("");

  useEffect(() => {
    let active = true;
    setLoading(true);
    loadProductsWithCacheFallback(selectedDepartmentId ?? undefined)
      .then((list) => {
        if (!active) return;
        setProducts(list);
      })
      .catch(() => active && setProducts([]))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [selectedDepartmentId]);

  async function tryAddVariant(variant: ProductVariant) {
    // Expiry gate — backend also blocks, but we block early for a clear message.
    if (selectedDepartmentId != null) {
      try {
        const expiry = await api.checkExpiry(variant.id, selectedDepartmentId);
        if (expiry.has_expired_stock) {
          toast.addToast(`Blocked: ${variant.name} has expired stock`, "error", { blocking: true });
          return;
        }
      } catch {
        /* if the expiry check itself fails, let the backend enforce on add */
      }
    }
    if (variant.pricing_mode === "weight_based") {
      onNeedsWeight(variant);
      return;
    }
    const ok = await actions.addVariant(variant, { quantity: 1 });
    if (ok) toast.addToast(`Added ${variant.name}`, "success");
  }

  async function resolveBarcode(code: string) {
    if (!code.trim()) return;
    try {
      const variant = await api.lookupBarcode(code.trim());
      await tryAddVariant(variant);
    } catch {
      toast.addToast(`No product for barcode ${code}`, "warning");
    } finally {
      setBarcode("");
    }
  }

  // Hardware scanner → same resolve path as the manual barcode field.
  useBarcodeScanner((code) => void resolveBarcode(code));

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    const variants: Array<{ product: Product; variant: ProductVariant }> = [];
    for (const p of products) {
      for (const v of p.variants ?? []) {
        if (
          !q ||
          v.name.toLowerCase().includes(q) ||
          v.sku.toLowerCase().includes(q) ||
          p.name.toLowerCase().includes(q)
        ) {
          variants.push({ product: p, variant: v });
        }
      }
    }
    return variants.slice(0, 60);
  }, [products, search]);

  return (
    <div className="entry">
      <div className="entry__inputs">
        <label className="entry__field">
          Search name / SKU
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Type to filter…"
          />
        </label>
        <label className="entry__field">
          Barcode
          <input
            type="text"
            value={barcode}
            onChange={(e) => setBarcode(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void resolveBarcode(barcode);
            }}
            placeholder="Scan or type barcode + Enter"
          />
        </label>
      </div>

      {loading ? (
        <div className="grid grid--empty">Loading products…</div>
      ) : filtered.length === 0 ? (
        <div className="grid grid--empty">No products{search ? " match your search" : ""}</div>
      ) : (
        <div className="grid" role="list">
          {filtered.map(({ variant }) => (
            <button
              key={variant.id}
              role="listitem"
              className="grid__item"
              disabled={busy}
              onClick={() => void tryAddVariant(variant)}
            >
              <span className="grid__name">{variant.name}</span>
              <span className="grid__meta">
                {variant.pricing_mode === "weight_based"
                  ? `${formatPence(variant.sell_price)}/kg`
                  : formatPence(variant.sell_price)}
              </span>
              <span className="grid__sku">{variant.sku}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/* ------------------------------ Loyalty --------------------------------- */

function LoyaltyPanel() {
  const customer = useStore((s) => s.customer);
  const toast = useToast();
  const [q, setQ] = useState("");
  const [results, setResults] = useState<Customer[]>([]);
  const [searching, setSearching] = useState(false);

  async function search() {
    if (!q.trim()) return;
    setSearching(true);
    try {
      setResults(await api.searchCustomers(q.trim()));
    } catch {
      toast.addToast("Customer search failed", "warning");
    } finally {
      setSearching(false);
    }
  }

  if (customer) {
    return (
      <div className="loyalty">
        <span>
          Loyalty: <strong>{customer.full_name || customer.name || customer.email}</strong>
        </span>
        <button className="btn btn--sm" onClick={() => actions.setCustomer(null)}>
          Remove
        </button>
      </div>
    );
  }

  return (
    <div className="loyalty">
      <input
        id="loyalty-search"
        type="search"
        value={q}
        placeholder="Loyalty customer…"
        aria-label="Search loyalty customer"
        onChange={(e) => setQ(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && void search()}
      />
      <button className="btn btn--sm" onClick={() => void search()} disabled={searching}>
        Search
      </button>
      {results.length > 0 && (
        <ul className="loyalty__results">
          {results.map((c) => (
            <li key={c.id}>
              <button
                className="btn btn--sm"
                onClick={() => {
                  actions.setCustomer(c);
                  setResults([]);
                  setQ("");
                }}
              >
                {c.full_name || c.name || c.email}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/* ------------------------------ Payment --------------------------------- */

function PaymentModal({ onClose }: { onClose: () => void }) {
  const order = useStore((s) => s.order);
  const busy = useStore((s) => s.busy);
  const toast = useToast();
  const [method, setMethod] = useState<"cash" | "card">("cash");
  const [tendered, setTendered] = useState("");
  const [ageVerified, setAgeVerified] = useState(false);

  const totalPence = order?.total_pence ?? 0;
  const tenderedPence = Math.round(parseFloat(tendered || "0") * 100);
  const cashOk = method !== "cash" || tenderedPence >= totalPence;

  async function pay() {
    const paid = await actions.checkout({
      payment_method: method,
      cash_tendered_pence: method === "cash" ? tenderedPence : undefined,
      age_verified: ageVerified,
    });
    if (!paid) return;

    // Fetch structured receipt and print (+ open drawer for cash).
    try {
      const receipt = await api.getReceipt(paid.id);
      await window.api?.printer.printReceipt(receipt, {});
      if (method === "cash") {
        await window.api?.drawer.open({});
      }
    } catch {
      toast.addToast("Printed receipt could not be generated", "warning");
    }

    const change =
      paid.change_given_pence != null ? formatPence(paid.change_given_pence) : null;
    toast.addToast(
      `Paid ${formatPence(totalPence)}${change ? ` — change ${change}` : ""}`,
      "success",
    );
    actions.resetSale();
    onClose();
  }

  return (
    <Modal
      open
      title="Take payment"
      onClose={onClose}
      footer={
        <>
          <button className="btn" onClick={onClose}>
            Cancel (Esc)
          </button>
          <button className="btn btn--primary" disabled={busy || !cashOk} onClick={() => void pay()}>
            {busy ? "Processing…" : `Pay ${formatPence(totalPence)}`}
          </button>
        </>
      }
    >
      <div className="pay-methods" role="radiogroup" aria-label="Payment method">
        {(["cash", "card"] as const).map((m) => (
          <label key={m} className={`pay-method ${method === m ? "pay-method--on" : ""}`}>
            <input
              type="radio"
              name="method"
              checked={method === m}
              onChange={() => setMethod(m)}
            />
            {m === "cash" ? "Cash" : "Card"}
          </label>
        ))}
      </div>
      {method === "cash" && (
        <label>
          Cash tendered (£)
          <input
            type="number"
            step="0.01"
            min="0"
            value={tendered}
            autoFocus
            onChange={(e) => setTendered(e.target.value)}
          />
        </label>
      )}
      <label className="checkbox">
        <input type="checkbox" checked={ageVerified} onChange={(e) => setAgeVerified(e.target.checked)} />
        Age verified (if required)
      </label>
      {!cashOk && <p className="form-errors">Cash tendered is less than the total.</p>}
    </Modal>
  );
}

/* ------------------------------ Basket ---------------------------------- */

function BasketPanel({ onPay }: { onPay: () => void }) {
  const order = useStore((s) => s.order);
  const confirmed = useStore((s) => s.confirmed);
  const busy = useStore((s) => s.busy);
  const lines = linesFromOrder(order);

  return (
    <aside className="basket" aria-label="Basket">
      <h2>Basket</h2>
      {lines.length === 0 ? (
        <p className="muted">Scan or select a product to begin.</p>
      ) : (
        <ul className="basket__list">
          {lines.map((l) => (
            <li key={l.id} className="basket__line">
              <div className="basket__line-main">
                <span className="basket__name">{l.name}</span>
                <span className="basket__total">{formatPence(l.lineTotalPence)}</span>
              </div>
              <div className="basket__line-sub">
                <span>
                  {l.weightKg != null
                    ? `${l.weightKg.toFixed(3)} kg`
                    : `${l.quantity} × ${formatPence(l.unitPricePence)}`}
                </span>
                {l.promotionName && <span className="promo">{l.promotionName}</span>}
                <button
                  className="btn btn--sm btn--danger"
                  aria-label={`Remove ${l.name}`}
                  disabled={busy}
                  onClick={() => void actions.removeItem(l.id)}
                >
                  Remove
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}

      <div className="basket__totals">
        <Row label="Subtotal" value={order?.subtotal_display} />
        {confirmed && <Row label="Discounts" value={order?.discount_total_display} />}
        <Row label="Tax" value={order?.tax_total_display} />
        <Row label="Total" value={order?.total_display} strong />
      </div>

      <LoyaltyPanel />

      <div className="basket__actions">
        {!confirmed ? (
          <button
            className="btn btn--primary"
            disabled={busy || lines.length === 0}
            onClick={() => void actions.confirmOrder()}
          >
            Confirm (apply promotions)
          </button>
        ) : (
          <button className="btn btn--primary" disabled={busy} onClick={onPay}>
            Take payment
          </button>
        )}
      </div>
    </aside>
  );
}

function Row({ label, value, strong }: { label: string; value?: string; strong?: boolean }) {
  return (
    <div className={`row ${strong ? "row--strong" : ""}`}>
      <span>{label}</span>
      <span>{value ?? "—"}</span>
    </div>
  );
}

/* ------------------------------ Page ------------------------------------ */

export default function CheckoutPage() {
  const auth = useStore((s) => s.auth);
  const error = useStore((s) => s.error);
  const toast = useToast();
  const [weightVariant, setWeightVariant] = useState<ProductVariant | null>(null);
  const [payOpen, setPayOpen] = useState(false);
  const lastError = useRef<string[] | null>(null);

  // Cashier keyboard shortcuts (handlers read the freshest store state).
  useShortcuts({
    new_sale: () => {
      actions.resetSale();
      toast.addToast("New sale started", "info");
    },
    customer_search: () => document.getElementById("loyalty-search")?.focus(),
    apply_discount: () => {
      const s = checkoutStore.getState();
      if (s.order && !s.confirmed) void actions.confirmOrder();
      else toast.addToast("Confirm a basket to apply discounts", "info");
    },
    void_item: () => {
      const lines = linesFromOrder(checkoutStore.getState().order);
      const last = lines[lines.length - 1];
      if (last) void actions.removeItem(last.id); // 403 (manager) surfaces as a toast
      else toast.addToast("Nothing to void", "info");
    },
    end_of_day: () => toast.addToast("End of day — settle the till and run reports", "info"),
  });

  useEffect(() => {
    if (auth && checkoutStore.getState().departments.length === 0) {
      void actions.loadDepartments();
    }
  }, [auth]);

  // Surface store errors as toasts (once each).
  useEffect(() => {
    if (error && error !== lastError.current) {
      lastError.current = error;
      error.forEach((m) => toast.addToast(m, "error"));
      actions.clearError();
    }
  }, [error, toast]);

  if (!auth) return <LoginForm />;

  return (
    <div className="checkout">
      <div className="checkout__toolbar">
        <DepartmentTabs />
        <div className="checkout__user">
          <span className="muted">{auth.email}</span>
          <button className="btn btn--sm" onClick={() => actions.logout()}>
            Sign out
          </button>
        </div>
      </div>

      <div className="checkout__body">
        <section className="checkout__entry">
          <ProductEntry onNeedsWeight={setWeightVariant} />
        </section>
        <BasketPanel onPay={() => setPayOpen(true)} />
      </div>

      {weightVariant && (
        <WeightPromptModal
          variant={weightVariant}
          onCancel={() => setWeightVariant(null)}
          onConfirm={async (kg) => {
            const v = weightVariant;
            setWeightVariant(null);
            const ok = await actions.addVariant(v, { weightKg: kg });
            if (ok) toast.addToast(`Added ${v.name} (${kg.toFixed(3)} kg)`, "success");
          }}
        />
      )}

      {payOpen && <PaymentModal onClose={() => setPayOpen(false)} />}
    </div>
  );
}
