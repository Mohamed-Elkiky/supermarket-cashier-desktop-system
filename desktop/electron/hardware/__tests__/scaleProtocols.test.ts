// @vitest-environment node
import { describe, it, expect } from "vitest";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { PARSERS, getParser, extractWeightKg } = require("../scaleProtocols.js");

describe("continuous parser", () => {
  const p = PARSERS.continuous;

  it("parses a stable gross reading", () => {
    expect(p.parse("ST,GS,+  1.234kg")).toEqual({ weightKg: 1.234, stable: true });
  });

  it("parses an unstable reading", () => {
    expect(p.parse("US,GS,+  1.200kg")).toEqual({ weightKg: 1.2, stable: false });
  });

  it("converts grams to kilograms", () => {
    expect(p.parse("ST,GS,+  500g")).toEqual({ weightKg: 0.5, stable: true });
  });

  it("handles a negative (tare) reading", () => {
    expect(p.parse("ST,GS,-  0.100kg")).toEqual({ weightKg: -0.1, stable: true });
  });

  it("tolerates trailing CRLF/whitespace", () => {
    expect(p.parse("ST,GS,+  2.500kg\r\n")).toEqual({ weightKg: 2.5, stable: true });
  });

  it("returns null for malformed / statusless / empty lines", () => {
    expect(p.parse("garbage")).toBeNull();
    expect(p.parse("GS,+1.234kg")).toBeNull(); // no ST/US status
    expect(p.parse("")).toBeNull();
    expect(p.parse("ST,GS,")).toBeNull(); // status but no weight
    expect(p.parse(null)).toBeNull();
  });
});

describe("poll parser", () => {
  const p = PARSERS.poll;

  it("parses a stable reply", () => {
    expect(p.parse("S 1.234 kg")).toEqual({ weightKg: 1.234, stable: true });
  });

  it("parses an unstable reply", () => {
    expect(p.parse("U 1.200 kg")).toEqual({ weightKg: 1.2, stable: false });
  });

  it("converts grams", () => {
    expect(p.parse("S 250 g")).toEqual({ weightKg: 0.25, stable: true });
  });

  it("handles negative weight", () => {
    expect(p.parse("S -0.500 kg")).toEqual({ weightKg: -0.5, stable: true });
  });

  it("returns null for malformed / statusless lines", () => {
    expect(p.parse("xyz")).toBeNull();
    expect(p.parse("1.234 kg")).toBeNull(); // no stability marker
    expect(p.parse("")).toBeNull();
  });
});

describe("getParser + extractWeightKg", () => {
  it("selects the right parser and defaults to continuous", () => {
    expect(getParser("poll").name).toBe("poll");
    expect(getParser("continuous").name).toBe("continuous");
    expect(getParser("unknown").name).toBe("continuous");
  });

  it("extracts kg from arbitrary text", () => {
    expect(extractWeightKg("weight is 1.5kg now")).toBe(1.5);
    expect(extractWeightKg("nothing here")).toBeNull();
  });
});
