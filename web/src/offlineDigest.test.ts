import { describe, expect, it, vi } from "vitest";

vi.mock("./ws", () => ({ conn: { send: () => true } }));

import { DIGEST_KEY, MAX_COUNT, OfflineDigest, formatCounts, parseCounts, webLocks, type Kv, type Locks } from "./offlineDigest";

/** One page alone with the store (the app), no lock API. */
const one = (kv: () => Kv | null) => new OfflineDigest({ kv, locks: () => null, onePage: () => true });

/** The origin's lock manager, shared by every page: an exclusive queue per name. */
function sharedLocks(): Locks {
  const tails = new Map<string, Promise<void>>();
  return {
    request(name, callback) {
      const run = (tails.get(name) ?? Promise.resolve()).then(callback);
      tails.set(name, run.catch(() => undefined));
      return run;
    },
  };
}

/** A store whose reads wait a tick, so two pages' work can interleave. */
function slowKv(data: Record<string, string>): Kv {
  return {
    get: async (k) => { await new Promise((r) => setTimeout(r, 1)); return data[k] ?? null; },
    set: async (k, v) => { await new Promise((r) => setTimeout(r, 1)); data[k] = v; },
  };
}

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
    const d = one(() => kv);
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
    const d = one(() => kv);
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
    const d = one(() => ({ get: async () => { throw new Error("x"); }, set: async () => {} }));
    const got: unknown[] = [];
    await expect(d.count("started", false)).resolves.toBeUndefined();
    await d.drain((c) => { got.push(c); return true; });
    expect(got).toEqual([]);
    await expect(one(() => null).count("finished", false)).resolves.toBeUndefined();
  });
});

describe("the digest is kept until its transport takes it", () => {
  it("a refused send keeps every count for the next online socket", async () => {
    const kv = memKv({ [DIGEST_KEY]: "2,1,1" });
    const d = one(() => kv);
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
    const d = one(() => slow);
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

describe("two pages over one store", () => {
  it("two connected tabs drain together: the counts go once, and the store ends at zero", async () => {
    const data: Record<string, string> = { [DIGEST_KEY]: "1,1,0" };
    const locks = sharedLocks();
    const tabA = new OfflineDigest({ kv: () => slowKv(data), locks: () => locks, onePage: () => false });
    const tabB = new OfflineDigest({ kv: () => slowKv(data), locks: () => locks, onePage: () => false });
    const wire: string[] = [];
    await Promise.all([tabA.drain((c) => { wire.push(`A:${formatCounts(c)}`); return true; }),
                       tabB.drain((c) => { wire.push(`B:${formatCounts(c)}`); return true; })]);
    expect(wire).toHaveLength(1);
    expect(wire[0].slice(2)).toBe("1,1,0");
    expect(data[DIGEST_KEY]).toBe("0,0,0");
  });

  it("a count made while another tab drains is kept, not wiped", async () => {
    const data: Record<string, string> = { [DIGEST_KEY]: "1,1,0" };
    const locks = sharedLocks();
    const tabA = new OfflineDigest({ kv: () => slowKv(data), locks: () => locks, onePage: () => false });
    const tabB = new OfflineDigest({ kv: () => slowKv(data), locks: () => locks, onePage: () => false });
    const wire: string[] = [];
    const draining = tabA.drain((c) => { wire.push(formatCounts(c)); return true; });
    const counting = tabB.count("started", true);
    await Promise.all([draining, counting]);
    expect(wire).toEqual(["1,1,0"]);
    expect(data[DIGEST_KEY]).toBe("1,0,1");
    await tabB.drain((c) => { wire.push(formatCounts(c)); return true; });
    expect(wire).toEqual(["1,1,0", "1,0,1"]);
    expect(data[DIGEST_KEY]).toBe("0,0,0");
  });

  it("with no lock where other tabs could share the store, nothing is sent and the counts wait", async () => {
    const data: Record<string, string> = { [DIGEST_KEY]: "1,1,0" };
    const d = new OfflineDigest({ kv: () => slowKv(data), locks: () => null, onePage: () => false });
    const wire: unknown[] = [];
    await d.drain((c) => { wire.push(c); return true; });
    await d.count("finished", false);
    expect(wire).toEqual([]);
    expect(data[DIGEST_KEY]).toBe("1,2,0");
  });

  it("reads the browser's Web Locks when it has them, and none otherwise", () => {
    const nav = globalThis.navigator as unknown as { locks?: unknown };
    const had = Object.getOwnPropertyDescriptor(nav, "locks");
    try {
      Object.defineProperty(nav, "locks", { value: undefined, configurable: true });
      expect(webLocks()).toBeNull();
      const calls: unknown[] = [];
      Object.defineProperty(nav, "locks", { configurable: true, value: {
        request: (name: string, opts: unknown, cb: () => Promise<void>) => { calls.push([name, opts]); return cb(); } } });
      const locks = webLocks()!;
      void locks.request("x", async () => {});
      expect(calls).toEqual([["x", { mode: "exclusive" }]]);
    } finally {
      if (had) Object.defineProperty(nav, "locks", had);
      else delete nav.locks;
    }
  });
});
