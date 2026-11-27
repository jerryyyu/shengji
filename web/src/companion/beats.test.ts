// The game events the table companions answer, read from the state the
// table already has, and the limits on what a figure adds of its own.
import { describe, expect, it } from "vitest";
import type { GameState, StatePlayer, TrickPlay } from "../protocol";
import { BEAT_BUDGET, BIG_GAP_MS, BeatLog, LEANS, WATCH_GAP_MS, aim, canWatch, kittyCapture, lastPlay, reachOf, reactions, tractorLed, trickTaken, underBudget, yourTurn } from "./beats";
import type { Layout } from "./seatZones";

const player = (seat: number, over: Partial<StatePlayer> = {}): StatePlayer =>
  ({ seat, name: `P${seat}`, is_bot: false, connected: true, team: (seat % 2) as 0 | 1, is_banker: false, ...over } as StatePlayer);
const state = (over: Partial<GameState> = {}): GameState => ({
  you: 0, phase: "play", players: [0, 1, 2, 3].map((s) => player(s)), turn: 1, banker: 1,
  trick: { leader: 1, plays: [] }, last_trick: null, round_result: null, ...over,
} as unknown as GameState);
const play = (seat: number, cards: string[], shape?: TrickPlay["shape"]): TrickPlay => ({ seat, cards, ...(shape ? { shape } : {}) });
const taken = (winner: number, points: number, n = 0) => ({ leader: 1, winner, points, plays: [play(1, [`H${n}`])] });

describe("the events", () => {
  it("your turn: your play, or your bury as banker", () => {
    expect(yourTurn(state({ turn: 0 }))).toBe(true);
    expect(yourTurn(state({ turn: 1 }))).toBe(false);
    expect(yourTurn(state({ turn: null, phase: "declare" }))).toBe(false);
    expect(yourTurn(state({ turn: 0, phase: "bury" }))).toBe(false);
    expect(yourTurn(state({ turn: 0, phase: "bury", players: [player(0, { is_banker: true }), player(1), player(2), player(3)] }))).toBe(true);
  });

  it("who is playing: the newest card of the trick, with a key of its own; none outside play or with no card down", () => {
    expect(lastPlay(state())).toBeNull();
    const one = lastPlay(state({ trick: { leader: 1, plays: [play(1, ["H3"])] } }))!;
    const two = lastPlay(state({ trick: { leader: 1, plays: [play(1, ["H3"]), play(2, ["H4"])] } }))!;
    expect([one.seat, two.seat]).toEqual([1, 2]);
    expect(one.key).not.toBe(two.key);
    expect(lastPlay(state({ phase: "round_end", trick: { leader: 1, plays: [play(1, ["H3"])] } }))).toBeNull();
    expect(lastPlay(state({ trick: null }))).toBeNull();
  });

  it("a tractor led: the lead's shape, once, on the frame it appears", () => {
    const lead = state({ trick: { leader: 2, plays: [play(2, ["S3", "S3", "S4", "S4"], "tractor")] } });
    expect(tractorLed(lead, state())).toBe(2);
    expect(tractorLed(lead, lead)).toBeNull();
    expect(tractorLed(lead, null)).toBeNull();
    expect(tractorLed(state({ trick: { leader: 2, plays: [play(2, ["S3", "S3"], "pair")] } }), state())).toBeNull();
    // a server that sends no shape marks none
    expect(tractorLed(state({ trick: { leader: 2, plays: [play(2, ["S3", "S3", "S4", "S4"])] } }), state())).toBeNull();
  });

  it("the kitty taken: the attackers won the last trick with points buried, at the round's end", () => {
    const end = (over: Partial<GameState>, kitty: number) => state({ phase: "round_end", last_trick: taken(0, 5), round_result: { kitty_points: kitty, winner_team: 0 }, ...over } as unknown as Partial<GameState>);
    expect(kittyCapture(end({}, 20))).toBe(0);
    expect(kittyCapture(end({}, 0))).toBeNull();
    expect(kittyCapture(end({ banker: 0 }, 20))).toBeNull();
    expect(kittyCapture(end({ banker: 0, last_trick: taken(3, 5) }, 20))).toBe(1);
    expect(kittyCapture(end({ banker: null }, 20))).toBeNull();
    expect(kittyCapture(end({ phase: "play" }, 20))).toBeNull();
  });
});

describe("what each seat does on a frame", () => {
  it("a trick by its points: a hop, a cheer from 10, a big jump and the others' droop from 20", () => {
    const limit = { big: -Infinity };
    expect(reactions(state({ last_trick: taken(0, 5) }), state(), 0, limit)).toEqual({ 0: "hop", 2: "hop" });
    expect(reactions(state({ last_trick: taken(0, 10) }), state(), 0, limit)).toEqual({ 0: "cheer", 2: "cheer" });
    expect(limit.big).toBe(-Infinity);
    expect(reactions(state({ last_trick: taken(3, 20) }), state(), 1000, limit)).toEqual({ 0: "droop", 1: "big", 2: "droop", 3: "big" });
    expect(limit.big).toBe(1000);
    expect(reactions(state(), state(), 2000, limit)).toEqual({});
    expect(reactions(state({ last_trick: taken(3, 20) }), null, 2000, limit)).toEqual({});
  });

  it("big plays keep BIG_GAP_MS apart, a tractor's hops with them; an absent player's figure takes none", () => {
    const limit = { big: 0 };
    const lead = state({ trick: { leader: 2, plays: [play(2, ["S3"], "tractor")] } });
    expect(reactions(state({ last_trick: taken(0, 40) }), state(), BIG_GAP_MS - 1, limit)).toEqual({ 0: "cheer", 2: "cheer" });
    expect(reactions(lead, state(), BIG_GAP_MS - 1, limit)).toEqual({});
    expect(limit.big).toBe(0);
    expect(reactions(lead, state(), BIG_GAP_MS, limit)).toEqual({ 0: "chug", 2: "chug" });
    expect(limit.big).toBe(BIG_GAP_MS);
    const gone = state({ last_trick: taken(0, 40), players: [player(0), player(1, { away: true }), player(2, { connected: false }), player(3)] });
    expect(reactions(gone, state(), 3 * BIG_GAP_MS, limit)).toEqual({ 0: "big", 3: "droop" });
  });

  it("a trick taken on the frame a tractor is led keeps the trick's move; nothing big starts at the round's end", () => {
    const both = state({ last_trick: taken(2, 5), trick: { leader: 2, plays: [play(2, ["S3"], "tractor")] } });
    expect(reactions(both, state(), 0, { big: -Infinity })).toEqual({ 0: "hop", 2: "hop" });
    expect(reactions(state({ phase: "round_end", last_trick: taken(1, 30) }), state(), 0, { big: -Infinity })).toEqual({ 1: "cheer", 3: "cheer" });
  });
});

describe("two tricks alike", () => {
  // a double-deck round can hold two tricks of the same cards from the same seats for the same points
  const same = () => ({ leader: 1, winner: 0, points: 25, plays: [play(1, ["H5", "H5"]), play(2, ["HK", "HK"]), play(3, ["H3", "H3"]), play(0, ["HA", "HA"])] });

  it("each is a trick taken where the server counts them: the count moving tells them apart", () => {
    const first = state({ last_trick: same(), tricks_done: 1 });
    const second = state({ last_trick: same(), tricks_done: 2 });
    expect(JSON.stringify(first.last_trick)).toBe(JSON.stringify(second.last_trick));
    expect(trickTaken(first, state({ tricks_done: 0 }))).toBe(true);
    expect(trickTaken(second, first)).toBe(true);
    // the same trick on a later frame (a card of the next one played) is not taken again
    expect(trickTaken(state({ last_trick: same(), tricks_done: 2, turn: 3 }), second)).toBe(false);
    expect(trickTaken(state({ tricks_done: 0 }), second)).toBe(false);
  });

  it("each gets its reaction, the limits kept: 9 s apart both are big plays, 4 s apart the second is the cheer", () => {
    const limit = { big: -Infinity };
    const first = state({ last_trick: same(), tricks_done: 1 });
    const second = state({ last_trick: same(), tricks_done: 2 });
    expect(reactions(first, state({ tricks_done: 0 }), 0, limit)).toEqual({ 0: "big", 1: "droop", 2: "big", 3: "droop" });
    expect(reactions(second, first, 9000, limit)).toEqual({ 0: "big", 1: "droop", 2: "big", 3: "droop" });
    expect(reactions(state({ last_trick: same(), tricks_done: 3 }), second, 13000, limit)).toEqual({ 0: "cheer", 2: "cheer" });
    // and a small one hops each time
    const small = (n: number) => state({ last_trick: { ...same(), points: 0 }, tricks_done: n });
    expect(reactions(small(5), small(4), 0, limit)).toEqual({ 0: "hop", 2: "hop" });
    expect(reactions(small(5), small(5), 0, limit)).toEqual({});
  });

  it("a server that sends no count has the tricks compared: a different trick is taken, the same one is not", () => {
    const limit = { big: -Infinity };
    expect(trickTaken(state({ last_trick: same() }), state())).toBe(true);
    expect(trickTaken(state({ last_trick: same() }), state({ last_trick: same() }))).toBe(false);
    expect(trickTaken(state({ last_trick: { ...same(), points: 30 } }), state({ last_trick: same() }))).toBe(true);
    expect(reactions(state({ last_trick: same() }), state(), 0, limit)).toEqual({ 0: "big", 1: "droop", 2: "big", 3: "droop" });
    expect(reactions(state({ last_trick: same() }), state({ last_trick: same() }), 9000, limit)).toEqual({});
    // one side with a count and one without (a reconnect across versions) is compared too
    expect(trickTaken(state({ last_trick: same(), tricks_done: 2 }), state({ last_trick: same() }))).toBe(false);
  });

  it("a tractor led again as the next trick opens is led again, and the card watched has a key of its own", () => {
    const lead = (n: number) => state({ tricks_done: n, trick: { leader: 2, plays: [play(2, ["S3", "S3", "S4", "S4"], "tractor")] } });
    expect(tractorLed(lead(2), lead(1))).toBe(2);
    expect(tractorLed(lead(2), lead(2))).toBeNull();
    expect(lastPlay(lead(2))!.key).not.toBe(lastPlay(lead(1))!.key);
  });
});

describe("a figure's own limits", () => {
  it("it watches at most once in WATCH_GAP_MS and adds nothing past its share of moves a minute: 8 for yours, 4 for another", () => {
    const log = new BeatLog();
    expect(canWatch(log, 0, true)).toBe(true);
    log.note(0);
    expect(canWatch(log, WATCH_GAP_MS - 1, true)).toBe(false);
    expect(canWatch(log, WATCH_GAP_MS, true)).toBe(true);
    for (let i = 1; i < BEAT_BUDGET.other; i++) log.note(i * 5000);
    expect(underBudget(log, 30000, false)).toBe(false);
    expect(underBudget(log, 30000, true)).toBe(true);
    for (let i = BEAT_BUDGET.other; i < BEAT_BUDGET.you; i++) log.note(i * 5000);
    expect(canWatch(log, 50000, true)).toBe(false);
    // a minute on, the early ones no longer count
    expect(log.count(50000)).toBe(8);
    expect(log.count(60000 + 5000 + 1)).toBe(6);
    expect(canWatch(log, 60000 + 5000 + 1, true)).toBe(true);
  });
});

describe("where a figure looks", () => {
  const layout: Layout = { felt: { w: 800, h: 360 }, plates: { left: { x: 0, y: 140, w: 90, h: 40 }, top: { x: 355, y: 0, w: 90, h: 40 }, right: { x: 710, y: 140, w: 90, h: 40 } },
    tagline: null, row: null, hand: null, obstacles: [] };
  const front = { dir: 1 as const, lean: 0, up: false };

  it("a seat to one side: your team's figure turns to it and leans in; the other team's leans without turning", () => {
    const s = { x: 400, y: 200 };
    expect(aim(s, 44, false, front, "left", true, layout)).toEqual({ dir: -1, lean: LEANS[0], up: false });
    expect(aim(s, 44, false, front, "right", true, layout)).toEqual({ dir: 1, lean: LEANS[0], up: false });
    expect(aim(s, 44, false, front, "left", false, layout)).toEqual({ dir: 1, lean: -LEANS[0], up: false });
    expect(aim(s, 44, false, { ...front, dir: -1 }, "left", false, layout)).toEqual({ dir: -1, lean: LEANS[0], up: false });
  });

  it("a seat over its head: it stretches up; the seat under it: as it stood", () => {
    expect(aim({ x: 380, y: 200 }, 44, false, front, "top", true, layout)).toEqual({ dir: 1, lean: 0, up: true });
    expect(aim({ x: 380, y: 200 }, 44, false, front, "bottom", true, layout)).toEqual(front);
  });

  it("the lean is the largest that stays clear: smaller beside something, none with no room at all", () => {
    const s = { x: 400, y: 200 };
    const wall = (gap: number): Layout => ({ ...layout, obstacles: [{ x: s.x + 44 + gap, y: 100, w: 10, h: 200 }] });
    const lean = (gap: number) => aim(s, 44, false, front, "right", true, wall(gap)).lean;
    expect(lean(7)).toBe(8);
    expect(lean(5)).toBeLessThan(8);
    expect(lean(5)).toBeGreaterThanOrEqual(4);
    expect(lean(4.5)).toBeLessThan(lean(5.5));
  });

  it("a transform's reach is how far it takes the box past itself about its feet", () => {
    expect(reachOf("scale(1.17)", 100)).toEqual({ l: expect.closeTo(8.5, 5), r: expect.closeTo(8.5, 5), up: expect.closeTo(17, 5), down: 0 });
    expect(reachOf("translateY(-26%) rotate(0deg) scale(0.96, 1.08)", 100)).toEqual({ l: 0, r: 0, up: expect.closeTo(34, 5), down: 0 });
    const lean = reachOf("scaleX(-1) translateY(0%) rotate(8deg) scale(1, 1)", 44);
    // leaning the way it faces, mirrored: the head goes left
    expect(lean.l).toBeCloseTo(22 * Math.cos((8 * Math.PI) / 180) + 44 * Math.sin((8 * Math.PI) / 180) - 22, 5);
    expect(lean.r).toBe(0);
  });
});
