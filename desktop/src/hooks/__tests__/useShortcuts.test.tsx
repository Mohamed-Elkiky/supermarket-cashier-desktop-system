import { describe, it, expect, afterEach, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { matchShortcut, isEditableTarget } from "../../services/shortcuts";
import { ShortcutsProvider, useShortcuts } from "../useShortcuts";

describe("shortcut matching (dispatcher logic)", () => {
  it("maps each cashier key to the right action id", () => {
    expect(matchShortcut({ key: "F1" }, null)).toBe("new_sale");
    expect(matchShortcut({ key: "F2" }, null)).toBe("customer_search");
    expect(matchShortcut({ key: "F3" }, null)).toBe("apply_discount");
    expect(matchShortcut({ key: "F9" }, null)).toBe("void_item");
    expect(matchShortcut({ key: "F12" }, null)).toBe("end_of_day");
    expect(matchShortcut({ key: "?", shiftKey: true }, null)).toBe("toggle_help");
  });

  it("returns null for unknown keys", () => {
    expect(matchShortcut({ key: "a" }, null)).toBeNull();
    expect(matchShortcut({ key: "?" }, null)).toBeNull(); // needs shift
  });

  it("ignores non-global shortcuts while an input is focused, but not function keys", () => {
    const input = document.createElement("input");
    expect(isEditableTarget(input)).toBe(true);
    // Shift+? is suppressed while typing…
    expect(matchShortcut({ key: "?", shiftKey: true }, input)).toBeNull();
    // …but the global function keys still fire.
    expect(matchShortcut({ key: "F1" }, input)).toBe("new_sale");
    expect(matchShortcut({ key: "F9" }, input)).toBe("void_item");
  });
});

/* --------------------------- provider behaviour ------------------------- */

let container: HTMLDivElement | null = null;
let root: Root | null = null;

afterEach(() => {
  act(() => root?.unmount());
  container?.remove();
  container = null;
  root = null;
});

function render(ui: React.ReactElement) {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  act(() => root!.render(ui));
}

function fireKey(key: string, shiftKey = false) {
  act(() => {
    window.dispatchEvent(new KeyboardEvent("keydown", { key, shiftKey, bubbles: true, cancelable: true }));
  });
}

function Consumer({ onNewSale }: { onNewSale: () => void }) {
  useShortcuts({ new_sale: onNewSale });
  return <div>consumer</div>;
}

describe("ShortcutsProvider", () => {
  it("dispatches a registered handler for F1", () => {
    const fn = vi.fn();
    render(
      <ShortcutsProvider>
        <Consumer onNewSale={fn} />
      </ShortcutsProvider>,
    );
    fireKey("F1");
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it("toggles the help overlay on Shift+?", () => {
    render(
      <ShortcutsProvider>
        <div>app</div>
      </ShortcutsProvider>,
    );
    expect(document.querySelector(".shortcut-help")).toBeNull();
    fireKey("?", true);
    expect(document.querySelector(".shortcut-help")).not.toBeNull();
    fireKey("?", true);
    expect(document.querySelector(".shortcut-help")).toBeNull();
  });
});
