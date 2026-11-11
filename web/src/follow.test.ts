import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { effectiveSuit, leadToFollow, TRUMP, unplayableIds } from "./follow";
import type { HandCard, Trump } from "./protocol";
import engineFixture from "./follow.engine.fixture.json";

const hand = (...codes: string[]): HandCard[] => codes.map((code, id) => ({ id, code }));
/** Codes of the cards left pickable. */
const open = (h: HandCard[], lead: string[], trump: Trump | null) => {
  const blocked = unplayableIds(h, lead, trump);
  return h.filter((c) => !blocked.has(c.id)).map((c) => c.code);
};
const HEARTS_2: Trump = { suit: "H", rank: "2", declarer: 0 };
const SPADES_7: Trump = { suit: "S", rank: "7", declarer: 0 };
const NT_5: Trump = { suit: "NT", rank: "5", declarer: null };

describe("effective suit (the engine's Ordering.eff_suit)", () => {
  it("makes jokers, every trump-rank card and the trump suit trump", () => {
    for (const c of ["BJ", "LJ", "S2", "D2", "H2", "H3", "HA"]) expect(effectiveSuit(c, HEARTS_2)).toBe(TRUMP);
    for (const [c, s] of [["S3", "S"], ["DA", "D"], ["C10", "C"]]) expect(effectiveSuit(c, HEARTS_2)).toBe(s);
  });

  it("in no-trump only jokers and the rank are trump; a 10 rank is matched whole", () => {
    expect(effectiveSuit("H5", NT_5)).toBe(TRUMP);
    expect(effectiveSuit("LJ", NT_5)).toBe(TRUMP);
    expect(effectiveSuit("H6", NT_5)).toBe("H");
    const tens: Trump = { suit: "D", rank: "10", declarer: 1 };
    expect(effectiveSuit("C10", tens)).toBe(TRUMP);
    expect(effectiveSuit("C1", tens)).toBe("C");
  });
});

describe("following a single", () => {
  it("holding the led suit, only that suit can go", () => {
    const h = hand("S3", "S9", "D4", "C5", "H6", "BJ");
    expect(open(h, ["SK"], HEARTS_2)).toEqual(["S3", "S9"]);
  });

  it("a trump-rank card of the led suit's printing is trump, not that suit", () => {
    // spades are led at level 2 with hearts trump: S2 is trump and cannot follow
    const h = hand("S2", "S9", "D4");
    expect(open(h, ["SK"], HEARTS_2)).toEqual(["S9"]);
  });

  it("a trump lead is followed by any trump: jokers, rank cards of every suit and the trump suit", () => {
    const h = hand("BJ", "D2", "H9", "S3", "C4", "LJ");
    expect(open(h, ["HK"], HEARTS_2)).toEqual(["BJ", "D2", "H9", "LJ"]);
    expect(open(h, ["LJ"], HEARTS_2)).toEqual(["BJ", "D2", "H9", "LJ"]);
    expect(open(h, ["C2"], HEARTS_2)).toEqual(["BJ", "D2", "H9", "LJ"]);
  });

  it("void in the led suit, anything goes", () => {
    const h = hand("D4", "C5", "BJ");
    expect(open(h, ["SK"], HEARTS_2)).toEqual(["D4", "C5", "BJ"]);
  });

  it("in no-trump a heart that is not the rank follows hearts, and the rank does not", () => {
    const h = hand("H5", "H6", "S5", "BJ", "D3");
    expect(open(h, ["HA"], NT_5)).toEqual(["H6"]);
    expect(open(h, ["BJ"], NT_5)).toEqual(["H5", "S5", "BJ"]);
  });
});

describe("following a pair", () => {
  it("holding a pair in the led suit, only cards of a pair in it can go", () => {
    const h = hand("D9", "D9", "DJ", "D5", "S3", "S3", "BJ");
    expect(open(h, ["DQ", "DQ"], SPADES_7)).toEqual(["D9", "D9"]);
  });

  it("two or more of the suit but no pair: any of them, and nothing else", () => {
    const h = hand("D9", "DJ", "D5", "S3", "S3");
    expect(open(h, ["DQ", "DQ"], SPADES_7)).toEqual(["D9", "DJ", "D5"]);
  });

  it("one card of the suit: it must go, the other card is free, so nothing is dimmed", () => {
    const h = hand("D9", "S3", "S3", "C4");
    expect(open(h, ["DQ", "DQ"], SPADES_7)).toEqual(["D9", "S3", "S3", "C4"]);
  });

  it("void: nothing is dimmed", () => {
    const h = hand("S3", "S3", "C4");
    expect(open(h, ["DQ", "DQ"], SPADES_7)).toEqual(["S3", "S3", "C4"]);
  });

  it("a trump pair is answered by a trump pair; off-suit rank cards are not a pair", () => {
    // spades trump at 7: D7 and C7 are both trump but different cards, so no pair;
    // the only trump pair is LJ LJ
    const h = hand("D7", "C7", "S4", "LJ", "LJ", "H3", "H3");
    expect(open(h, ["SA", "SA"], SPADES_7)).toEqual(["LJ", "LJ"]);
    // without the jokers: three trump, no pair, so any trump
    const h2 = hand("D7", "C7", "S4", "H3", "H3");
    expect(open(h2, ["SA", "SA"], SPADES_7)).toEqual(["D7", "C7", "S4"]);
  });

  it("two copies of the same trump-rank card are a pair", () => {
    const h = hand("D7", "D7", "C7", "S9");
    expect(open(h, ["BJ", "BJ"], SPADES_7)).toEqual(["D7", "D7"]);
  });
});

describe("leads it leaves to the server", () => {
  it("dims nothing for a throw, a tractor, or two different cards", () => {
    const h = hand("D9", "S3", "S3", "C4");
    expect(open(h, ["DQ", "DQ", "DK", "DK"], SPADES_7)).toHaveLength(4);
    expect(open(h, ["DQ", "DA"], SPADES_7)).toHaveLength(4);
    expect(open(h, ["DQ", "DQ", "DA"], SPADES_7)).toHaveLength(4);
  });

  it("dims nothing without a known trump", () => {
    expect(open(hand("D9", "S3"), ["SK"], null)).toHaveLength(2);
  });
});

describe("the lead to follow", () => {
  it("is the first play of a trick you have not played in", () => {
    expect(leadToFollow(null, 0)).toBeNull();
    expect(leadToFollow({ plays: [] }, 0)).toBeNull();
    expect(leadToFollow({ plays: [{ seat: 1, cards: ["SK"] }] }, 0)).toEqual(["SK"]);
    expect(leadToFollow({ plays: [{ seat: 0, cards: ["SK"] }, { seat: 1, cards: ["S3"] }] }, 0)).toBeNull();
  });
});

describe("against the engine", () => {
  // Cases from the engine's own validate_follow: for each hand, the cards that
  // appear in at least one accepted play of the lead's size.
  interface EngineCase { trump: Trump; hand: string[]; lead: string[]; playable: number[] }
  const big = process.env.FOLLOW_ENGINE_CASES;
  const cases: EngineCase[] = big
    ? JSON.parse(readFileSync(big, "utf8"))
    : (engineFixture as EngineCase[]);

  it(`dims exactly the cards no accepted play holds (${cases.length} cases)`, () => {
    let dimmed = 0;
    for (const c of cases) {
      const h = hand(...c.hand);
      const blocked = unplayableIds(h, c.lead, c.trump);
      const expected = h.map((x) => x.id).filter((id) => !c.playable.includes(id));
      expect([...blocked].sort((a, b) => a - b), JSON.stringify(c)).toEqual(expected);
      dimmed += blocked.size;
    }
    expect(dimmed).toBeGreaterThan(0);
  });
});
