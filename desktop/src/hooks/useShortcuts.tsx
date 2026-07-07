import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { SHORTCUTS, matchShortcut, type ActionId } from "../services/shortcuts";
import { Modal } from "../components/Modal";

export type ShortcutHandlers = Partial<Record<ActionId, () => void>>;

interface ShortcutsContextValue {
  register(handlers: ShortcutHandlers): () => void;
  openHelp(): void;
  isHelpOpen: boolean;
}

const ShortcutsContext = createContext<ShortcutsContextValue | null>(null);

/**
 * Installs a SINGLE window keydown listener, maps the event to an action id via
 * the registry, and dispatches to the most-recently-registered handler for that
 * action. Renders the Shift+? help overlay (generated from the registry, so it
 * never goes stale).
 */
export function ShortcutsProvider({ children }: { children: ReactNode }) {
  const stackRef = useRef<ShortcutHandlers[]>([]);
  const [helpOpen, setHelpOpen] = useState(false);

  const register = useCallback((handlers: ShortcutHandlers) => {
    stackRef.current.push(handlers);
    return () => {
      stackRef.current = stackRef.current.filter((h) => h !== handlers);
    };
  }, []);

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      const id = matchShortcut(e, e.target);
      if (!id) return;
      if (id === "toggle_help") {
        e.preventDefault();
        setHelpOpen((o) => !o);
        return;
      }
      for (let i = stackRef.current.length - 1; i >= 0; i--) {
        const handler = stackRef.current[i][id];
        if (handler) {
          e.preventDefault();
          handler();
          return;
        }
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  const openHelp = useCallback(() => setHelpOpen(true), []);

  return (
    <ShortcutsContext.Provider value={{ register, openHelp, isHelpOpen: helpOpen }}>
      {children}
      <Modal open={helpOpen} title="Keyboard shortcuts" onClose={() => setHelpOpen(false)}>
        <ul className="shortcut-help">
          {SHORTCUTS.map((s) => (
            <li key={s.id}>
              <kbd>{s.label}</kbd>
              <span>{s.description}</span>
            </li>
          ))}
        </ul>
      </Modal>
    </ShortcutsContext.Provider>
  );
}

/** Register the active screen's shortcut handlers. Latest values are always used. */
export function useShortcuts(handlers: ShortcutHandlers): void {
  const ctx = useContext(ShortcutsContext);
  const ref = useRef(handlers);
  ref.current = handlers;
  const keySignature = Object.keys(handlers).sort().join(",");

  useEffect(() => {
    if (!ctx) return;
    // A stable wrapper that always reads the freshest handler implementations.
    const wrapper: ShortcutHandlers = {};
    for (const key of Object.keys(ref.current) as ActionId[]) {
      wrapper[key] = () => ref.current[key]?.();
    }
    return ctx.register(wrapper);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ctx, keySignature]);
}

export function useHelpOverlay(): { open(): void; isOpen: boolean } {
  const ctx = useContext(ShortcutsContext);
  return { open: () => ctx?.openHelp(), isOpen: ctx?.isHelpOpen ?? false };
}
