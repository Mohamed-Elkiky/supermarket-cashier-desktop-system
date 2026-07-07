// @vitest-environment node
import { describe, it, expect, afterEach } from "vitest";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const scale = require("../scale.js");

const delay = (ms: number) => new Promise((r) => setTimeout(r, ms));

afterEach(async () => {
  await scale.disconnect();
  scale.__setEmitterForTest(null);
});

describe("scale mock mode", () => {
  it("streams stable readings the renderer can subscribe to", async () => {
    const readings: Array<{ weightKg: number; stable: boolean }> = [];
    scale.__setEmitterForTest((r: { weightKg: number; stable: boolean }) => readings.push(r));

    const res = await scale.connect({ mockIntervalMs: 5 }); // no path -> mock
    expect(res).toEqual({ ok: true, mock: true });

    await delay(40);
    expect(readings.length).toBeGreaterThanOrEqual(2);
    expect(readings.every((r) => r.stable === true)).toBe(true);
    expect(readings.every((r) => typeof r.weightKg === "number" && r.weightKg > 0)).toBe(true);
  });

  it("only surfaces stable readings (unstable are debounced away)", () => {
    const readings: unknown[] = [];
    scale.__setEmitterForTest((r: unknown) => readings.push(r));
    scale.surface({ weightKg: 1.0, stable: false });
    expect(readings).toHaveLength(0);
    scale.surface({ weightKg: 1.0, stable: true });
    expect(readings).toHaveLength(1);
    // duplicate stable value is debounced
    scale.surface({ weightKg: 1.0, stable: true });
    expect(readings).toHaveLength(1);
  });
});
