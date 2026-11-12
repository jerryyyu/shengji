// The follow check dims only cards no legal follow can use, from the
// follower's own hand, the lead and the trump.
import { describe, expect, it } from "vitest";
import type { HandCard, Trump } from "./protocol";
import { MAX_CANDIDATES, followHint, playableIds } from "./followRules";

const hand = (codes: string[]): HandCard[] => codes.map((code, i) => ({ id: i + 1, code }));
const heartsTwo: Trump = { suit: "H", rank: "2", declarer: 0 };
const ids = (h: HandCard[], s: Set<number> | null) => (s === null ? null : h.filter((c) => s.has(c.id)).map((c) => c.code));

describe("playableIds", () => {
  it("holding the led suit, only its cards can follow", () => {
    const h = hand(["S3", "S9", "HA", "D4", "C7"]);
    expect(ids(h, playableIds(h, ["SK"], heartsTwo))).toEqual(["S3", "S9"]);
  });

  it("a pair led owes a pair held in the suit, so the loose spades are out", () => {
    const h = hand(["S3", "S3", "S9", "SJ", "D4"]);
    expect(ids(h, playableIds(h, ["SK", "SK"], heartsTwo))).toEqual(["S3", "S3"]);
  });

  it("short of the led suit or void, every card can be part of a play", () => {
    const short = hand(["S3", "HA", "D4"]);
    expect(playableIds(short, ["SK", "SK"], heartsTwo)).toBeNull();
    const voidHand = hand(["HA", "D4", "C7"]);
    expect(playableIds(voidHand, ["SK"], heartsTwo)).toBeNull();
  });

  it("follows the trump group: trump-rank cards and jokers answer a trump lead", () => {
    const h = hand(["S2", "BJ", "H5", "SA", "C9"]);
    expect(ids(h, playableIds(h, ["HK"], heartsTwo))).toEqual(["S2", "BJ", "H5"]);
    // no trump declared yet: nothing to check against, nothing dimmed
    expect(playableIds(h, ["HK"], null)).toBeNull();
  });

  it("a huge candidate set falls back to the suit rule and never dims a suit card", () => {
    const spades = ["S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10", "SJ", "SQ", "SK", "SA"];
    const h = hand([...spades, ...spades.slice(0, 8), "D4"]);
    const lead = ["S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10", "SJ", "SQ"];
    const got = ids(h, playableIds(h, lead, { suit: "C", rank: "2", declarer: 0 }));
    expect(got).not.toContain("D4");
    expect(got).toHaveLength(20);
    expect(MAX_CANDIDATES).toBeLessThan(10000);
  });
});

describe("followHint", () => {
  it("names the suit and the count", () => {
    expect(followHint(["SK", "SK", "SA"], heartsTwo)).toBe("Follow ♠: play 3 cards");
    expect(followHint(["BJ"], heartsTwo)).toBe("Follow trump: play 1 card");
    expect(followHint(["D4"], null)).toBe("Follow the lead: play 1 card");
  });
});
