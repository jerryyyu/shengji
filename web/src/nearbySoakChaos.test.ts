// The whole-app soak's phase triggers on fixture frames and log lines, and
// its page faults: frame loss at the bridge and the frozen main thread.
import { describe, expect, it } from "vitest";
import {
  BridgeFaults, busyWait, CHAOS_GAP_MS, ChaosPacer, frameTriggers, lineTriggers, ROUND_CALM_MS, type Bridge,
} from "./nearbySoakChaos";

type Frame = Record<string, unknown> & { type: string };

const hand = (codes: string[]) => codes.map((code, id) => ({ id: id + 10, code }));

const room = (over: Partial<Frame> = {}): Frame => ({
  type: "room", room: "ABCDEF", you: 1, host: 0,
  players: [{ seat: 0, name: "Host" }, { seat: 1, name: "P1" }], nearby: { ready: [], bots_in: null, locked: false }, ...over,
});

const state = (over: Partial<Frame> = {}): Frame => ({
  type: "state", room: "ABCDEF", you: 1, phase: "play", turn: 0, ready: [], passed: [],
  hand: hand(["S2", "S3"]), trump: { suit: "H", rank: "2" }, banker: 0, trick: { leader: 1, plays: [] }, last_trick: null,
  current_declaration: null, declare_options: [],
  players: [0, 1, 2, 3].map((seat) => ({ seat, name: `S${seat}`, is_bot: seat > 1, connected: true, controller: "human", away: false })),
  ...over,
});

describe("the phase triggers", () => {
  it("match each phase once, on the frame that reaches it", () => {
    expect(frameTriggers(null, room(), 5)).toEqual(["lobby"]);
    expect(frameTriggers(room(), room(), 5)).toEqual([]);
    expect(frameTriggers(room(), state({ phase: "deal", hand: hand(["S2"]) }), 5)).toEqual(["start"]);
    const d4 = state({ phase: "deal", hand: hand(["S2", "S3", "S4", "S5"]) });
    const d5 = state({ phase: "deal", hand: hand(["S2", "S3", "S4", "S5", "S6"]) });
    expect(frameTriggers(d4, d5, 5)).toEqual(["deal_card"]);
    expect(frameTriggers(d5, d5, 5)).toEqual([]);
    expect(frameTriggers(d5, state({ phase: "declare" }), 30)).toEqual(["declare_open"]);
    const bury = state({ phase: "bury", turn: 1 });
    expect(frameTriggers(state({ phase: "declare" }), bury, 30)).toEqual(["own_bury"]);
    expect(frameTriggers(state({ phase: "declare" }), { ...bury, turn: 0 }, 30)).toEqual([]);
    const last = state({ hand: hand(["S2"]) });
    expect(frameTriggers(state(), last, 30)).toEqual(["last_trick"]);
    expect(frameTriggers(last, last, 30)).toEqual([]);
    expect(frameTriggers(last, state({ phase: "round_end", round_result: { game_over: false } }), 30)).toEqual(["round_end"]);
    expect(frameTriggers(last, state({ phase: "round_end", round_result: { point_scored: true } }), 30)).toEqual(["round_end", "game_over"]);
  });

  it("match this phone's move going out, a join's handshake and the driver's Leave in the log", () => {
    expect(lineTriggers({ from: "socket", text: "out play" })).toEqual(["after_move"]);
    expect(lineTriggers({ from: "socket", text: "out ping" })).toEqual([]);
    expect(lineTriggers({ from: "join", text: "join sent (no token)" })).toEqual(["join_handshake"]);
    expect(lineTriggers({ from: "join", text: "attempt (resume)" })).toEqual(["join_handshake"]);
    expect(lineTriggers({ from: "soak", text: "flow: leave (leaver, play, link open)" })).toEqual(["leave"]);
  });
});

describe("the page faults", () => {
  it("loses frames at the bridge in one direction: a send reads as sent, a delivery never arrives", async () => {
    let t = 0;
    const sent: string[] = [];
    const got: string[] = [];
    const b: Bridge = {
      nativePromise: (_p, _m, o) => { sent.push((o as { text: string }).text); return Promise.resolve("sent"); },
      fromNative: (r) => { got.push(String(r.data?.text)); },
    };
    const f = new BridgeFaults("ShengjiNearby", () => t);
    expect(f.install(b)).toBe(true);
    f.loss("out", "play", 1);
    await expect(b.nativePromise!("ShengjiNearby", "send", { peer: "host", text: '{"type":"play","card_ids":[1]}' })).resolves.toBeUndefined();
    await b.nativePromise!("ShengjiNearby", "send", { peer: "host", text: '{"type":"play","card_ids":[2]}' });
    await b.nativePromise!("ShengjiNearby", "send", { peer: "host", text: '{"type":"ping"}' });
    expect(sent).toEqual(['{"type":"play","card_ids":[2]}', '{"type":"ping"}']);
    f.oneway("in", 5000);
    b.fromNative!({ methodName: "addListener", data: { peer: "host", text: '{"type":"state"}' } });
    // a log line from the plugin is not a frame
    b.fromNative!({ methodName: "addListener", data: { text: "drop host" } });
    t = 6000;
    b.fromNative!({ methodName: "addListener", data: { peer: "host", text: '{"type":"state"}' } });
    expect(got).toEqual(["drop host", '{"type":"state"}']);
    expect(f.lost).toEqual({ in: 1, out: 1 });
    expect(new BridgeFaults().install({})).toBe(false);
  });

  it("freezes the main thread for the time asked, capped at 50 s", () => {
    let t = 0;
    busyWait(3000, () => (t += 100));
    expect(t).toBeGreaterThanOrEqual(3000);
    t = 0;
    busyWait(120_000, () => (t += 1000));
    expect(t).toBeLessThanOrEqual(51_000);
  });
});


describe("the chaos pace", () => {
  /** A seeded stand-in for Math.random. */
  const seeded = (seed: number) => () => {
    seed = (seed * 1_103_515_245 + 12_345) % 2 ** 31;
    return seed / 2 ** 31;
  };

  /** Two hours of a soak on a fake clock: a phase trigger every 6 s, a
   *  round's end every 8 min, and the background timer as the page arms it. */
  function soak(seed: number) {
    let t = 0;
    const p = new ChaosPacer(() => t, seeded(seed));
    const faults: { at: number; by: "aimed" | "bg" }[] = [];
    const roundEnds: number[] = [];
    let bgAt = t + p.backgroundDelay();
    for (t = 0; t <= 2 * 3600_000; t += 1000) {
      if (t % 6000 === 0 && p.aimed()) faults.push({ at: t, by: "aimed" });
      if (t >= bgAt) {
        if (p.background()) faults.push({ at: t, by: "bg" });
        bgAt = t + p.backgroundDelay();
      }
      if (t > 0 && t % 480_000 === 0) {
        roundEnds.push(t);
        p.roundEnded();
      }
    }
    return { faults, roundEnds };
  }

  it("keeps faults at least CHAOS_GAP_MS apart, about one a minute", () => {
    for (const seed of [1, 7, 42]) {
      const { faults } = soak(seed);
      const gaps = faults.slice(1).map((f, i) => f.at - faults[i].at);
      expect(Math.min(...gaps)).toBeGreaterThanOrEqual(CHAOS_GAP_MS);
      // about one a minute over two hours, calm stretches included
      expect(faults.length).toBeGreaterThanOrEqual(80);
      expect(faults.length).toBeLessThanOrEqual(130);
      // both the phase triggers and the background timer still fire
      expect(faults.some((f) => f.by === "aimed")).toBe(true);
      expect(faults.some((f) => f.by === "bg")).toBe(true);
    }
  });

  it("is calm for ROUND_CALM_MS after a round's end", () => {
    const { faults, roundEnds } = soak(3);
    for (const end of roundEnds) {
      expect(faults.filter((f) => f.at > end && f.at < end + ROUND_CALM_MS)).toEqual([]);
    }
  });

  it("starts with a gap, so a reload's resumed soak does not fault at once", () => {
    let t = 0;
    const p = new ChaosPacer(() => t, () => 0);
    expect(p.background()).toBe(false);
    expect(p.aimed()).toBe(false);
    t = CHAOS_GAP_MS;
    expect(p.background()).toBe(true);
    expect(p.background()).toBe(false);
  });
});
