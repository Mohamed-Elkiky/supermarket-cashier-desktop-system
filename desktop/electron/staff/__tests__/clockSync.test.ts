// @vitest-environment node
import { describe, it, expect, beforeAll, afterAll, beforeEach } from "vitest";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const db = require("../../db/database.js");
const clockSync = require("../clockSync.js");

function makeClient(opts: { failTimes?: number } = {}) {
  let failTimes = opts.failTimes ?? 0;
  const calls: Array<{ eventType: string; client_uuid: string }> = [];
  return {
    calls,
    async postClockEvent(eventType: string, body: { client_uuid: string }) {
      calls.push({ eventType, client_uuid: body.client_uuid });
      if (failTimes > 0) {
        failTimes -= 1;
        throw new Error("network down");
      }
      return { clocked_in: eventType === "clock_in" };
    },
  };
}

let tmpDir: string;

beforeAll(async () => {
  tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "pos-clock-test-"));
  await db.init({ dbPath: path.join(tmpDir, "clock.db"), showFirstRunDialog: false });
});

afterAll(() => {
  try {
    db.close();
  } catch {
    /* ignore */
  }
  fs.rmSync(tmpDir, { recursive: true, force: true });
});

beforeEach(() => {
  db.ensureReady().prepare("DELETE FROM pending_clock_events").run();
});

describe("clock-event offline queue + replay", () => {
  it("persists a clock event enqueued while offline", () => {
    clockSync.enqueue({ client_uuid: "c1", event_type: "clock_in", occurred_at: "2026-07-07T09:00:00Z" });
    const pending = db.listPendingClockEvents();
    expect(pending).toHaveLength(1);
    expect(pending[0].event_type).toBe("clock_in");
  });

  it("drains the queue on reconnect, carrying client_uuid", async () => {
    clockSync.enqueue({ client_uuid: "c2", event_type: "clock_in", occurred_at: "t" });
    clockSync.enqueue({ client_uuid: "c3", event_type: "clock_out", occurred_at: "t" });
    const client = makeClient();
    const res = await clockSync.replayClockEvents(client);
    expect(res.drained).toBe(2);
    expect(db.listPendingClockEvents()).toHaveLength(0);
    expect(client.calls.map((c) => c.client_uuid)).toEqual(["c2", "c3"]);
  });

  it("does not duplicate the same client_uuid", async () => {
    clockSync.enqueue({ client_uuid: "dup", event_type: "clock_in", occurred_at: "t" });
    clockSync.enqueue({ client_uuid: "dup", event_type: "clock_in", occurred_at: "t" });
    expect(db.listPendingClockEvents()).toHaveLength(1);
    const client = makeClient();
    await clockSync.replayClockEvents(client);
    await clockSync.replayClockEvents(client);
    expect(client.calls.filter((c) => c.client_uuid === "dup")).toHaveLength(1);
  });

  it("retries a failing replay without dropping the event", async () => {
    clockSync.enqueue({ client_uuid: "r1", event_type: "clock_in", occurred_at: "t" });
    const client = makeClient({ failTimes: 1 });
    const first = await clockSync.replayClockEvents(client);
    expect(first.failed).toBe(1);
    const pending = db.listPendingClockEvents();
    expect(pending).toHaveLength(1);
    expect(pending[0].attempts).toBe(1);

    const second = await clockSync.replayClockEvents(client);
    expect(second.drained).toBe(1);
    expect(db.listPendingClockEvents()).toHaveLength(0);
  });
});
