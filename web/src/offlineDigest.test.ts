import { describe, expect, it, vi } from "vitest";

vi.mock("./ws", () => ({ conn: { send: () => true } }));

import { DIGEST_KEY, MAX_COUNT, OfflineDigest, formatCounts, parseCounts, type Kv } from "./offlineDigest";

function memKv(init: Record<string, string> = {}): Kv & { data: Record<string, string> } {
  const data = { ...init };
  return {
    data,
    get: async (k) => data[k] ?? null,
    set: async (k, v) => { data[k] = v; },
  };
}

describe("the offline digest", () => {
  it("counts rounds on the device, sends them once and resets", async () => {
    const kv = memKv();
    const d = new OfflineDigest(() => kv);
    await d.count("started", false);
    await d.count("finished", false);
    await d.count("started", true);
    expect(kv.data[DIGEST_KEY]).toBe("2,1,1");
    const got: unknown[] = [];
    await d.drain((c) => { got.push(c); return true; });
    expect(got).toEqual([{ rounds_started: 2, rounds_finished: 1, nearby_rounds: 1 }]);
    expect(kv.data[DIGEST_KEY]).toBe("0,0,0");
    await d.drain((c) => { got.push(c); return true; });
    expect(got).toHaveLength(1);         // nothing new: nothing sent
  });

  it("keeps its counts small", async () => {
    const kv = memKv({ [DIGEST_KEY]: `${MAX_COUNT},0,${MAX_COUNT}` });
    const d = new OfflineDigest(() => kv);
    await d.count("started", true);
    expect(kv.data[DIGEST_KEY]).toBe("99,0,99");
    expect(formatCounts({ rounds_started: 1e9, rounds_finished: -4, nearby_rounds: 2.7 })).toBe("99,0,2");
  });

  it("reads anything else as zero", () => {
    expect(parseCounts("1,2")).toEqual({ rounds_started: 0, rounds_finished: 0, nearby_rounds: 0 });
    expect(parseCounts("100,1,1")).toEqual({ rounds_started: 0, rounds_finished: 0, nearby_rounds: 0 });
    expect(parseCounts(null)).toEqual({ rounds_started: 0, rounds_finished: 0, nearby_rounds: 0 });
  });

  it("a failing store changes nothing and never throws", async () => {
    const d = new OfflineDigest(() => ({ get: async () => { throw new Error("x"); }, set: async () => {} }));
    const got: unknown[] = [];
    await expect(d.count("started", false)).resolves.toBeUndefined();
    await d.drain((c) => { got.push(c); return true; });
    expect(got).toEqual([]);
    await expect(new OfflineDigest(() => null).count("finished", false)).resolves.toBeUndefined();
  });
});

describe("the digest is kept until its transport takes it", () => {
  it("a refused send keeps every count for the next online socket", async () => {
    const kv = memKv({ [DIGEST_KEY]: "2,1,1" });
    const d = new OfflineDigest(() => kv);
    await d.drain(() => false);
    expect(kv.data[DIGEST_KEY]).toBe("2,1,1");
    const got: unknown[] = [];
    await d.drain((c) => { got.push(c); return true; });
    expect(got).toEqual([{ rounds_started: 2, rounds_finished: 1, nearby_rounds: 1 }]);
    expect(kv.data[DIGEST_KEY]).toBe("0,0,0");
  });

  it("the page going offline while the stored counts are read sends nothing and keeps them", async () => {
    let release!: () => void;
    const gate = new Promise<void>((r) => { release = r; });
    const data: Record<string, string> = { [DIGEST_KEY]: "2,1,1" };
    const slow: Kv = { get: async (k) => { await gate; return data[k] ?? null; }, set: async (k, v) => { data[k] = v; } };
    const { Telemetry } = await import("./telemetry");
    let online = true;
    const wire: unknown[] = [];
    const t = new Telemetry((m) => { wire.push(m); return true; }, () => online);
    const d = new OfflineDigest(() => slow);
    const draining = d.drain((c) => t.sendOfflineDigest(c));
    online = false;                      // the app switched to the device's server meanwhile
    release();
    await draining;
    expect(wire).toEqual([]);
    expect(t.pending()).toEqual([]);
    expect(data[DIGEST_KEY]).toBe("2,1,1");
    online = true;                       // the next online socket sends them
    await d.drain((c) => t.sendOfflineDigest(c));
    expect(wire).toHaveLength(1);
    expect(data[DIGEST_KEY]).toBe("0,0,0");
  });
});
