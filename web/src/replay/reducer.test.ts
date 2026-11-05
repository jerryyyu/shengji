// The replay reducer, against a real round from a room log (round 3 of one
// game: the viewer, seat 0, is the banker; names neutralized, `decision` and
// `bot_seed` removed as the API does).
import { describe, expect, it } from "vitest";
import fixture from "./round.fixture.json";
import { compareCards } from "./cards";
import { buildReplay, frameOfTrick, stepTrick } from "./reducer";
import type { RoundEvent, RoundReplayDoc } from "./reducer";

const doc = fixture as unknown as RoundReplayDoc;
const rs = doc.events.find((e) => e.e === "round_start")!;
const deck = rs.deck as string[];
const plays = doc.events.filter((e) => e.e === "play") as (RoundEvent & { seat: number; cards: string[] })[];
const sortedCodes = (cs: { code: string }[] | string[]) =>
  cs.map((c) => (typeof c === "string" ? c : c.code)).sort();

function minus(have: string[], take: string[]): string[] {
  const left = [...have];
  for (const c of take) {
    const i = left.indexOf(c);
    if (i >= 0) left.splice(i, 1);
  }
  return left;
}

describe("a finished round, seen by the banker", () => {
  const replay = buildReplay(doc);
  const { frames, setup } = replay;
  const dealt = deck.slice(0, 100).filter((_, i) => i % 4 === 0);
  const kitty = deck.slice(100, 108);
  const bury = doc.events.find((e) => e.e === "bury")!.cards as string[];

  it("reads the setup the viewer saw", () => {
    expect(setup.trumpSuit).toBe("C");
    expect(setup.trumpRank).toBe("4");
    expect(setup.banker).toBe(0);
    expect(setup.declarations).toEqual([{ seat: 3, cards: ["C4"] }]);
    expect(setup.ownBury).toEqual(bury);
    expect(setup.players.map((p) => p.name)).toEqual(["Ana", "Bot 1", "Bot 2", "Bot 3"]);
    expect(replay.complete).toBe(true);
    expect(replay.trickCount).toBe(doc.events.filter((e) => e.e === "trick").length);
    // deal + start + one per play + end
    expect(frames).toHaveLength(2 + plays.length + 1);
  });

  it("deals 25, picks up the kitty and buries 8, sorted trump-last", () => {
    expect(frames[0].kind).toBe("deal");
    expect(sortedCodes(frames[0].hand)).toEqual([...dealt].sort());
    expect(frames[1].kind).toBe("start");
    expect(sortedCodes(frames[1].hand)).toEqual(minus([...dealt, ...kitty], bury).sort());
    const codes = frames[1].hand.map((c) => c.code);
    const resorted = [...codes].sort((a, b) => compareCards(a, b, "C", "4"));
    expect(codes).toEqual(resorted);
  });

  it("stepping forward and back reproduces hand and trick state at every step", () => {
    let hand = minus([...dealt, ...kitty], bury);
    let trickPlays: { seat: number; cards: string[] }[] = [];
    let n = 0;
    for (let i = 2; i < frames.length - 1; i++) {
      const p = plays[i - 2];
      if (trickPlays.length === 4) trickPlays = [];
      if (trickPlays.length === 0) n += 1;
      trickPlays.push({ seat: p.seat, cards: p.cards });
      if (p.seat === 0) hand = minus(hand, p.cards);
      const f = frames[i];
      expect(f.kind).toBe("play");
      expect(f.trickNo).toBe(n);
      expect(f.trick?.plays).toEqual(trickPlays);
      expect(f.trick?.leader).toBe(trickPlays[0].seat);
      expect(sortedCodes(f.hand)).toEqual([...hand].sort());
      expect(f.cardsLeft[p.seat]).toBe(25 - plays.slice(0, i - 1).filter((q) => q.seat === p.seat)
        .reduce((k, q) => k + q.cards.length, 0));
      // The frame a prefix of the log ends on is the same frame: stepping back
      // to step i shows exactly what the round showed then.
      const cut = doc.events.indexOf(p) + 1;
      const prefix = buildReplay({ ...doc, finished: false, events: doc.events.slice(0, cut) });
      const tail = prefix.frames[prefix.frames.length - 1];
      expect(tail.hand).toEqual(f.hand);
      expect(tail.trick).toEqual(f.trick);
    }
  });

  it("marks each trick's winner and counts the attackers' points", () => {
    const tricks = doc.events.filter((e) => e.e === "trick");
    const completed = frames.filter((f) => f.kind === "play" && f.winner !== null);
    expect(completed.map((f) => f.winner)).toEqual(tricks.map((t) => t.winner));
    const fromTricks = tricks.filter((t) => Number(t.winner) % 2 !== 0)
      .reduce((k, t) => k + Number(t.points), 0);
    expect(frames[frames.length - 2].attackerPoints).toBe(fromTricks);
  });

  it("ends on round_end with the result and empty hands", () => {
    const end = frames[frames.length - 1];
    expect(end.kind).toBe("end");
    expect(end.result?.attacker_points).toBe(110);
    expect(end.result?.winner_team).toBe(1);
    expect(end.result?.new_levels).toEqual(["4", "4"]);
    expect(end.hand).toEqual([]);
    expect(end.hands.every((h) => h !== null && h.length === 0)).toBe(true);
    expect(setup.finished).toBe(true);
    expect(setup.kitty).toEqual(kitty);
  });

  it("knows every hand in a finished round", () => {
    expect(frames[1].hands.map((h) => h?.length)).toEqual([25, 25, 25, 25]);
  });

  it("steps by trick and jumps to trick N", () => {
    const t3 = frameOfTrick(replay, 3);
    expect(frames[t3].trickNo).toBe(3);
    expect(frames[t3].playNo).toBe(0);
    const endOf3 = stepTrick(replay, t3, 1);
    expect(frames[endOf3].trickNo).toBe(3);
    expect(frames[endOf3].winner).not.toBeNull();
    expect(stepTrick(replay, endOf3, -1)).toBe(t3);
    expect(stepTrick(replay, t3, -1)).toBe(frameOfTrick(replay, 2));
    expect(stepTrick(replay, 0, -1)).toBe(0);
    expect(stepTrick(replay, frames.length - 2, 1)).toBe(frames.length - 1);
  });
});

/** The filter as the server applies it before round_end: the viewer's own
 *  deal positions only; the kitty and the other hands hidden. */
function unfinishedFor(seat: number, upToPlay: number): RoundReplayDoc {
  const cut = doc.events.indexOf(plays[upToPlay]) + 1;
  const events = doc.events.slice(0, cut).map((e) => {
    if (e.e === "round_start") {
      return { ...e, deck: (e.deck as string[]).map((c, i) => (i < 100 && i % 4 === seat ? c : null)) };
    }
    if (e.e === "bury" && e.seat !== seat) return { ...e, cards: null };
    return e;
  });
  return { ...doc, seat, finished: false, events };
}

describe("an unfinished round", () => {
  const replay = buildReplay(unfinishedFor(1, 21));   // trick 6, second play
  const { frames } = replay;
  const last = frames[frames.length - 1];

  it("shows only the viewer's hand and the cards played", () => {
    expect(replay.complete).toBe(false);
    expect(frames.some((f) => f.kind === "end")).toBe(false);
    expect(replay.setup.kitty).toBeNull();
    expect(replay.setup.ownBury).toBeNull();
    for (const f of frames) {
      expect(f.hands[0]).toBeNull();
      expect(f.hands[2]).toBeNull();
      expect(f.hands[3]).toBeNull();
      expect(f.hands[1]).not.toBeNull();
      expect(f.result).toBeNull();
    }
    expect(last.trickNo).toBe(6);
    expect(last.trick?.plays).toEqual(plays.slice(20, 22).map((p) => ({ seat: p.seat, cards: p.cards })));
    const mine = deck.slice(0, 100).filter((_, i) => i % 4 === 1);
    const played = plays.slice(0, 22).filter((p) => p.seat === 1).flatMap((p) => p.cards);
    expect(sortedCodes(last.hand)).toEqual(minus(mine, played).sort());
  });

  it("accepts a viewer hand sent as `hand` instead of a masked deck", () => {
    const d = unfinishedFor(1, 3);
    const mine = deck.slice(0, 100).filter((_, i) => i % 4 === 1);
    d.events = d.events.map((e) => {
      if (e.e !== "round_start") return e;
      const { deck: _drop, ...rest } = e;
      void _drop;
      return { ...rest, hand: mine };
    });
    const r = buildReplay(d);
    expect(sortedCodes(r.frames[0].hand)).toEqual([...mine].sort());
    expect(r.frames[0].hands[0]).toBeNull();
  });
});
