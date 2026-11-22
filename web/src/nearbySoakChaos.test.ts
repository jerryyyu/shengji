// The whole-app soak's phase triggers on fixture frames and log lines, and
// its page faults: frame loss at the bridge and the frozen main thread.
import { describe, expect, it } from "vitest";
import { BridgeFaults, busyWait, frameTriggers, lineTriggers, type Bridge } from "./nearbySoakChaos";

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

