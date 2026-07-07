"use strict";

/**
 * Pluggable weighing-scale protocol parsers.
 *
 * Every parser implements the same interface:
 *     parse(rawLine: string) -> { weightKg: number, stable: boolean } | null
 * returning null for blank / malformed lines. Parsers are pure (no serial I/O)
 * so they are fully unit-testable, and new scale models can be added by dropping
 * another parser in PARSERS.
 */

// Matches an optional sign, a decimal number, and a kg/g unit anywhere in a line.
const WEIGHT_RE = /([+-]?)\s*(\d+(?:\.\d+)?)\s*(kg|g)\b/i;

function extractWeightKg(text) {
  const m = WEIGHT_RE.exec(text);
  if (!m) return null;
  const sign = m[1] === "-" ? -1 : 1;
  let value = parseFloat(m[2]);
  if (!Number.isFinite(value)) return null;
  if (m[3].toLowerCase() === "g") value = value / 1000;
  return sign * value;
}

function round3(n) {
  return Math.round(n * 1000) / 1000;
}

/**
 * "continuous" — the scale streams weight lines continuously, e.g.
 *   "ST,GS,+  1.234kg"  (ST = stable, US = unstable; GS = gross)
 */
const continuousParser = {
  name: "continuous",
  parse(rawLine) {
    if (typeof rawLine !== "string") return null;
    const line = rawLine.trim();
    if (!line) return null;
    const stability = /\b(ST|US)\b/i.exec(line);
    if (!stability) return null; // continuous frames always carry a status
    const weightKg = extractWeightKg(line);
    if (weightKg === null) return null;
    return { weightKg: round3(weightKg), stable: stability[1].toUpperCase() === "ST" };
  },
};

/**
 * "poll" — the app sends an ENQ / weight-request byte and reads one reply, e.g.
 *   "S 1.234 kg"   (leading S = stable, U = unstable). Commas also tolerated.
 */
const pollParser = {
  name: "poll",
  parse(rawLine) {
    if (typeof rawLine !== "string") return null;
    const line = rawLine.trim();
    if (!line) return null;
    const stability = /^\s*([SU])[\s,]/i.exec(line);
    if (!stability) return null;
    const weightKg = extractWeightKg(line);
    if (weightKg === null) return null;
    return { weightKg: round3(weightKg), stable: stability[1].toUpperCase() === "S" };
  },
};

const PARSERS = {
  continuous: continuousParser,
  poll: pollParser,
};

/** Look up a parser by protocol name; defaults to the continuous parser. */
function getParser(protocol) {
  return PARSERS[protocol] || continuousParser;
}

/** The byte the poll protocol sends to request a reading (ENQ). */
const ENQ = Buffer.from([0x05]);

module.exports = { PARSERS, getParser, extractWeightKg, round3, ENQ };
