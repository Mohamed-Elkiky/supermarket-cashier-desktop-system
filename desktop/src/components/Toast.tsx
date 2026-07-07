import { createContext, useCallback, useContext, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";

export type ToastType = "info" | "success" | "error" | "warning";

export interface ToastItem {
  id: number;
  message: string;
  type: ToastType;
  /** Blocking toasts must be dismissed explicitly (e.g. expired-stock block). */
  blocking?: boolean;
}

interface ToastContextValue {
  toasts: ToastItem[];
  addToast: (message: string, type?: ToastType, opts?: { blocking?: boolean; timeoutMs?: number }) => void;
  dismiss: (id: number) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const nextId = useRef(1);

  const dismiss = useCallback((id: number) => {
    setToasts((list) => list.filter((t) => t.id !== id));
  }, []);

  const addToast = useCallback<ToastContextValue["addToast"]>(
    (message, type = "info", opts = {}) => {
      const id = nextId.current++;
      setToasts((list) => [...list, { id, message, type, blocking: opts.blocking }]);
      if (!opts.blocking) {
        const timeout = opts.timeoutMs ?? 4000;
        window.setTimeout(() => dismiss(id), timeout);
      }
    },
    [dismiss],
  );

  const value = useMemo(() => ({ toasts, addToast, dismiss }), [toasts, addToast, dismiss]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="toast-stack" role="region" aria-label="Notifications" aria-live="assertive">
        {toasts.map((t) => (
          <div key={t.id} className={`toast toast--${t.type}`} role="alert">
            <span className="toast__msg">{t.message}</span>
            <button
              type="button"
              className="toast__close"
              aria-label="Dismiss notification"
              onClick={() => dismiss(t.id)}
            >
              ×
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used within a ToastProvider");
  return ctx;
}
