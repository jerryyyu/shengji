import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./ws", () => ({ conn: { send: () => true } }));

import type { GameState, Phase } from "./protocol";
import { telemetry } from "./telemetry";
import { OPEN_ROUND_KEY, RoundTracker, type RoundDeps } from "./roundTelemetry";
import { OfflineDigest, type Kv } from "./offlineDigest";
import { PLAYED_KEY, type Store } from "./telemetryStamps";

function memStore(): Store & { data: Record<string, string> } {
  const data: Record<string, string> = {};
  return { data, getItem: (k) => data[k] ?? null, setItem: (k, v) => { data[k] = v; }, removeItem: (k) => { delete data[k]; } };
}
function memKv(): Kv & { data: Record<string, string> } {
  const data: Record<string, string> = {};
  return { data, get: async (k) => data[k] ?? null, set: async (k, v) => { data[k] = v; } };
}

let done = 0;
function state(phase: Phase, over: Partial<GameState> = {}): GameState {
  return {
    type: "state", room: "ROOM", you: 0, phase, players: [0, 1, 2, 3].map((seat) => ({
      seat, name: seat === 0 ? "Me" : `Bot ${seat}`, is_bot: seat !== 0, connected: true, team: seat % 2,
      controller: seat === 0 ? "human" : "bot",
    })), hand: [], levels: ["2", "2"], games_won: [0, 0], banker: 0, trump: null, turn: null,
    declare_options: [], current_declaration: null, passed: [], trick: null, last_trick: null,
    attacker_points: 0, kitty_count: 8, round_result: null, message: null, notice: null, tricks_done: done, ...over,
  } as unknown as GameState;
}
/** A play-phase state after one more resolved trick, its last trick the
 *  same four cards every time (two decks: alike tricks happen). */
function afterTrick(): GameState {
  done += 1;
  return state("play", { tricks_done: done,
                         last_trick: { leader: 0, winner: 1, plays: [{ seat: 0, cards: ["SA"] }] } } as Partial<GameState>);
}
function ended(winner: 0 | 1): GameState {
  return state("round_end", { tricks_done: done, round_result: { winner_team: winner } } as Partial<GameState>);
}

let store: ReturnType<typeof memStore>;
let tab: ReturnType<typeof memStore>;
let kv: ReturnType<typeof memKv>;
let mode: { offline: boolean; nearby: boolean };
/** A page's tracker: the device's storage is shared, `session` is its tab's. */
function tracker(session = tab): RoundTracker {
  const deps: RoundDeps = { online: () => !mode.offline && !mode.nearby, offline: () => mode.offline,
                            nearby: () => mode.nearby, store: () => store, session: () => session,
                            digest: new OfflineDigest({ kv: () => kv, locks: () => null, onePage: () => true }) };
  return new RoundTracker(deps);
}
const events = () => telemetry.pending().filter((e) => e.e === "round_start" || e.e === "round_finish");

beforeEach(() => {
  telemetry.reset();
  store = memStore();
  tab = memStore();
  kv = memKv();
  done = 0;
  mode = { offline: false, nearby: false };
});

describe("rounds as the page sees them", () => {
  it("a casual round with three bots starts at its deal and finishes at its end, won", () => {
    const r = tracker();
    r.observe(state("deal"));
    r.observe(state("declare"));
    r.observe(afterTrick());
    const again = afterTrick();
    r.observe(again);
    r.observe(again);          // the same state twice is still two tricks
    r.observe(afterTrick());
    r.observe(afterTrick());   // alike last tricks, each counted by the server's count
    r.observe(ended(0));
    r.observe(ended(0));       // a second round_end state says nothing more
    expect(events()).toEqual([
      expect.objectContaining({ e: "round_start", mode: "casual", bots: 3, nth_round_this_load: 1 }),
      expect.objectContaining({ e: "round_finish", mode: "casual", by: "end", won: true, tricks_played: 4 }),
    ]);
    expect(tab.data[OPEN_ROUND_KEY]).toBeUndefined();
    expect(store.data[PLAYED_KEY]).toBe("1");
  });

  it("the next round counts up, a ranked table reads as ranked, a lost round as lost", () => {
    const r = tracker();
    r.observe(state("deal", { matched: true }));
    r.observe(ended(1));
    r.observe(state("deal", { matched: true }));
    r.observe(ended(1));
    expect(events().map((e) => [e.e, (e as { mode?: string }).mode, (e as { won?: boolean }).won,
                                (e as { nth_round_this_load?: number }).nth_round_this_load]))
      .toEqual([["round_start", "ranked", undefined, 1], ["round_finish", "ranked", false, undefined],
                ["round_start", "ranked", undefined, 2], ["round_finish", "ranked", false, undefined]]);
  });

  it("a code, a Duo or a Continue makes a friends' table; Play a casual one", () => {
    const r = tracker();
    r.noteEntry("friend");
    r.observe(state("deal"));
    r.left();
    r.noteEntry("queue");
    r.observe(state("deal", { room: "NEXT" }));
    expect(events()).toEqual([
      expect.objectContaining({ e: "round_start", mode: "friend" }),
      expect.objectContaining({ e: "round_finish", mode: "friend", by: "left", tricks_played: 0 }),
      expect.objectContaining({ e: "round_start", mode: "casual" }),
    ]);
    expect(events()[1]).not.toHaveProperty("won");
  });

  it("a table taken away mid-round ends nothing: no finish now, and no closed later", () => {
    const r = tracker();
    r.observe(state("deal"));
    r.observe(null);
    r.closed();
    expect(events().map((e) => e.e)).toEqual(["round_start"]);
    expect(tab.data[OPEN_ROUND_KEY]).toBeUndefined();
  });

  it("a round first seen mid-play is not tracked", () => {
    const r = tracker();
    r.observe(afterTrick());
    r.observe(ended(0));
    r.left();
    expect(events()).toEqual([]);
  });

  it("a reconnect that skips tricks takes the server's count", () => {
    const r = tracker();
    r.observe(state("deal", { tricks_done: 0 } as Partial<GameState>));
    r.observe(state("play", { tricks_done: 7 } as Partial<GameState>));
    r.observe(state("round_end", { tricks_done: 25, round_result: { winner_team: 1 } } as Partial<GameState>));
    expect(events()[1]).toMatchObject({ e: "round_finish", by: "end", tricks_played: 25, won: false });
  });

  it("a round with any state lacking the server's count has no count, said as none", () => {
    const r = tracker();
    r.observe(state("deal", { tricks_done: 0 } as Partial<GameState>));
    r.observe(state("play", { tricks_done: undefined }));         // an older server
    r.observe(state("play", { tricks_done: 3 } as Partial<GameState>));
    expect(tab.data[OPEN_ROUND_KEY]).toBe("casual:u");
    r.left();
    expect(events()[1]).toEqual(expect.objectContaining({ e: "round_finish", by: "left" }));
    expect(events()[1]).not.toHaveProperty("tricks_played");
  });

  it("two tabs: one tab's open round is never the other's, and both finish as they played", () => {
    const tabA = memStore(), tabB = memStore();
    const a = tracker(tabA);
    a.observe(state("deal", { tricks_done: 0 } as Partial<GameState>));
    a.observe(afterTrick());
    const b = tracker(tabB);                                      // a second tab opens
    b.takeLastOpen();
    b.sayLastClosed();
    a.observe(ended(0));
    expect(events().map((e) => [e.e, (e as { by?: string }).by])).toEqual([["round_start", undefined], ["round_finish", "end"]]);
    expect(tabA.data[OPEN_ROUND_KEY]).toBeUndefined();
  });

  it("the page closing mid-round says closed now; a reload of the tab after a lost page says it once", () => {
    const r = tracker();
    r.observe(state("deal", { tricks_done: 0 } as Partial<GameState>));
    r.observe(afterTrick());
    expect(tab.data[OPEN_ROUND_KEY]).toBe("casual:1");
    // the page went with no pagehide; the same tab loads again
    telemetry.reset();
    const next = tracker();
    next.takeLastOpen();
    expect(tab.data[OPEN_ROUND_KEY]).toBeUndefined();
    next.sayLastClosed();
    next.sayLastClosed();
    expect(events()).toEqual([expect.objectContaining({ e: "round_finish", mode: "casual", by: "closed", tricks_played: 1 })]);
    // and with a pagehide
    telemetry.reset();
    next.observe(state("deal"));
    next.closed();
    expect(events().map((e) => (e as { by?: string }).by)).toEqual([undefined, "closed"]);
    expect(tab.data[OPEN_ROUND_KEY]).toBeUndefined();
  });

  it("a stored round that is not one of ours is ignored", () => {
    tab.data[OPEN_ROUND_KEY] = "Jerry:3";
    const r = tracker();
    r.takeLastOpen();
    r.sayLastClosed();
    tab.data[OPEN_ROUND_KEY] = "offline:3";
    r.takeLastOpen();
    r.sayLastClosed();
    expect(events()).toEqual([]);
  });

  it("offline and nearby rounds are only counted, never sent", async () => {
    mode.offline = true;
    const r = tracker();
    r.observe(state("deal"));
    r.observe(afterTrick());
    r.observe(ended(0));
    r.noteRoom({ type: "room", room: "NEAR", nearby: { ready: [], bots_in: null, locked: false } } as never);
    r.observe(state("deal", { room: "NEAR" }));
    r.left();
    mode.offline = false;
    mode.nearby = true;
    r.observe(state("deal", { room: "OTHER" }));
    await new Promise((res) => setTimeout(res, 0));
    expect(events()).toEqual([]);
    expect(kv.data["shengji.telemetry.offline"]).toBe("3,1,2");
    expect(tab.data[OPEN_ROUND_KEY]).toBeUndefined();
  });
});
