/**
 * Central, data-driven keyboard-shortcut registry (framework-agnostic).
 *
 * A single map of shortcut -> action id. Screens register handlers for the
 * action ids they support; the dispatcher (useShortcuts) maps a keydown to an
 * action id and invokes the active handler.
 *
 * Rule: shortcuts do NOT fire while the user is typing in a text field, EXCEPT
 * the global function keys (F1/F2/F3/F9/F12). This keeps them from clashing with
 * normal typing and with the barcode scanner (which only buffers single chars).
 */

export type ActionId =
  | "new_sale"
  | "customer_search"
  | "apply_discount"
  | "void_item"
  | "end_of_day"
  | "toggle_help";

export interface ShortcutDef {
  id: ActionId;
  /** Human label for the combo, e.g. "F1", "Shift+?". */
  label: string;
  description: string;
  /** KeyboardEvent.key to match. */
  key: string;
  shift?: boolean;
  /** Global shortcuts fire even while a text field is focused. */
  global?: boolean;
}

export const SHORTCUTS: ShortcutDef[] = [
  { id: "new_sale", label: "F1", description: "Start a new sale", key: "F1", global: true },
  { id: "customer_search", label: "F2", description: "Search loyalty customer", key: "F2", global: true },
  { id: "apply_discount", label: "F3", description: "Apply discounts / promotions", key: "F3", global: true },
  { id: "void_item", label: "F9", description: "Void selected line (manager)", key: "F9", global: true },
  { id: "end_of_day", label: "F12", description: "End of day", key: "F12", global: true },
  { id: "toggle_help", label: "Shift+?", description: "Show keyboard shortcuts", key: "?", shift: true },
];

/** Is the event target an editable field where typing must win? */
export function isEditableTarget(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el || !el.tagName) return false;
  const tag = el.tagName.toUpperCase();
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
  return el.isContentEditable === true;
}

export interface KeyLike {
  key: string;
  shiftKey?: boolean;
}

function keyMatches(def: ShortcutDef, e: KeyLike): boolean {
  return e.key === def.key && !!def.shift === !!e.shiftKey;
}

/**
 * Map a keydown to an action id, honouring the "ignore while typing except
 * global function keys" rule. Returns null if nothing should fire.
 */
export function matchShortcut(e: KeyLike, target: EventTarget | null): ActionId | null {
  const def = SHORTCUTS.find((s) => keyMatches(s, e));
  if (!def) return null;
  if (!def.global && isEditableTarget(target)) return null;
  return def.id;
}
