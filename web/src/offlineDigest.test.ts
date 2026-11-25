import { describe, expect, it } from "vitest";
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
    await d.drain((c) => got.push(c));
    expect(got).toEqual([{ rounds_started: 2, rounds_finished: 1, nearby_rounds: 1 }]);
    expect(kv.data[DIGEST_KEY]).toBe("0,0,0");
    await d.drain((c) => got.push(c));
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
    await d.drain((c) => got.push(c));
    expect(got).toEqual([]);
    await expect(new OfflineDigest(() => null).count("finished", false)).resolves.toBeUndefined();
  });
});
