import { describe, it, expect, afterEach } from "vitest";
import { createBarcodeScanner, type BarcodeScanner } from "../barcodeScanner";

let mockTime = 1000;
let current: BarcodeScanner | null = null;

function makeScanner(config = {}) {
  mockTime = 1000;
  const scanner = createBarcodeScanner(config, () => mockTime);
  current = scanner;
  scanner.start();
  return scanner;
}

/** Dispatch a keydown after advancing the mock clock by `gapMs`. */
function press(key: string, gapMs = 0): KeyboardEvent {
  mockTime += gapMs;
  const event = new KeyboardEvent("keydown", { key, cancelable: true, bubbles: true });
  window.dispatchEvent(event);
  return event;
}

function pressBurst(text: string, gapMs = 10): void {
  text.split("").forEach((ch, i) => press(ch, i === 0 ? 500 : gapMs));
}

afterEach(() => {
  current?.stop();
  current = null;
});

describe("BarcodeScanner", () => {
  it("emits exactly one barcode for a fast burst terminated by Enter", () => {
    const scanner = makeScanner();
    const codes: string[] = [];
    scanner.subscribe((c) => codes.push(c));

    pressBurst("5012345678900", 10); // each keystroke 10ms apart (< 30ms)
    press("Enter");

    expect(codes).toEqual(["5012345678900"]);
  });

  it("ignores the same characters typed slowly by a human", () => {
    const scanner = makeScanner();
    const codes: string[] = [];
    scanner.subscribe((c) => codes.push(c));

    "5012345678900".split("").forEach((ch) => press(ch, 200)); // 200ms gaps
    press("Enter");

    expect(codes).toEqual([]);
  });

  it("ignores a burst shorter than minLength", () => {
    const scanner = makeScanner({ minLength: 3 });
    const codes: string[] = [];
    scanner.subscribe((c) => codes.push(c));

    press("A", 500);
    press("B", 10);
    press("Enter");

    expect(codes).toEqual([]);
  });

  it("suppresses buffered burst keystrokes and the terminator from inputs", () => {
    const scanner = makeScanner();
    scanner.subscribe(() => {});

    const events: KeyboardEvent[] = [];
    "5012345".split("").forEach((ch, i) => events.push(press(ch, i === 0 ? 500 : 10)));
    const enter = press("Enter");

    // First char can't be judged yet (leaks), continuation chars are suppressed.
    expect(events[0].defaultPrevented).toBe(false);
    expect(events[3].defaultPrevented).toBe(true);
    expect(enter.defaultPrevented).toBe(true);
  });

  it("does not preventDefault when suppressInput is disabled", () => {
    const scanner = makeScanner({ suppressInput: false });
    const codes: string[] = [];
    scanner.subscribe((c) => codes.push(c));

    const events: KeyboardEvent[] = [];
    "5012345".split("").forEach((ch, i) => events.push(press(ch, i === 0 ? 500 : 10)));
    const enter = press("Enter");

    expect(events.every((e) => !e.defaultPrevented)).toBe(true);
    expect(enter.defaultPrevented).toBe(false);
    expect(codes).toEqual(["5012345"]); // still detected, just not suppressed
  });

  it("strips configured prefix and suffix", () => {
    const scanner = makeScanner({ prefix: "*", suffix: "#", minLength: 3 });
    const codes: string[] = [];
    scanner.subscribe((c) => codes.push(c));

    pressBurst("*12345#", 10);
    press("Enter");

    expect(codes).toEqual(["12345"]);
  });

  it("supports multiple subscribers (pub/sub)", () => {
    const scanner = makeScanner();
    const a: string[] = [];
    const b: string[] = [];
    scanner.subscribe((c) => a.push(c));
    scanner.subscribe((c) => b.push(c));

    pressBurst("999888777", 10);
    press("Enter");

    expect(a).toEqual(["999888777"]);
    expect(b).toEqual(["999888777"]);
  });
});
