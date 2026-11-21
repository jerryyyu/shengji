// @vitest-environment node
// The simulator's model of the joiner page's reconnect (--page ws) keeps
// ws.ts's timings, and a seed shows what they do to a held hello: the
// attempt is cut at 5 s while its hello waits on a stalled host, and the
// next one starts 6 s after it.
import { describe, expect, it } from "vitest";
import { CONNECT_MS, LONG_LIVED_MS, NEARBY_BACKOFF_MAX_MS } from "./ws";
import { BACKOFF_FIRST_S, BACKOFF_MAX_S, CONNECT_S, LONG_LIVED_S } from "../scripts/nearby-chaos/pageModel";
import { runGame } from "../scripts/nearby-chaos/sim";

describe("the simulator's page model", () => {
  it("copies ws.ts's connect timer, long-lived retry and nearby backoff cap", () => {
    expect(CONNECT_S * 1000).toBe(CONNECT_MS);
    expect(LONG_LIVED_S * 1000).toBe(LONG_LIVED_MS);
    expect(BACKOFF_MAX_S * 1000).toBe(NEARBY_BACKOFF_MAX_MS);
    expect(BACKOFF_FIRST_S).toBe(0.5);
  });

  it("seed 1: a hello held by a stalled host, the attempt cut at 5 s, the retry 6 s after it began", async () => {
    const r = await runGame({
      seed: 1, bugs: [], seconds: 60, bound: 15, hostile: false, verbose: false, page: "ws",
      schedule: [
        { t: 25, kind: "stallPhone", who: "H", dur: 9, arg: 0 },
        { t: 25.05, kind: "drop", who: "J1", dur: 0, arg: 0 },
      ],
    });
    const at = (re: RegExp) => {
      const line = r.trace.find((l) => re.test(l));
      return line === undefined ? NaN : Number(line.split(" ")[0]);
    };
    const cut = r.trace.find((l) => / J1 page: attempt \d+ cut at 5 s/.test(l));
    expect(cut).toBeDefined();
    const n = Number(/attempt (\d+) cut/.exec(cut!)![1]);
    const began = at(new RegExp(` J1 page: attempt ${n}$`));
    const hello = at(/resume: link up in \d+ ms; hello sent/);
    const cutAt = Number(cut!.split(" ")[0]);
    const next = at(new RegExp(` J1 page: attempt ${n + 1}$`));
    expect(hello).toBeGreaterThan(began);
    expect(hello).toBeLessThan(cutAt);
    expect(cutAt - began).toBeCloseTo(5, 2);
    expect(next - began).toBeCloseTo(6, 2);
    expect(r.violation).toBeNull();
  });
});
