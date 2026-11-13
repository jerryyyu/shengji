// The follow hint names the lead's effective suit and its card count, from
// the lead and the trump alone.
import { describe, expect, it } from "vitest";
import type { Trump } from "./protocol";
import { followHint, followsSuit, leadSuit } from "./followRules";

const heartsTwo: Trump = { suit: "H", rank: "2", declarer: 0 };

describe("leadSuit", () => {
  it("reads trump-rank cards and jokers as trump, and needs a declared trump", () => {
    expect(leadSuit(["SK"], heartsTwo)).toBe("S");
    expect(leadSuit(["S2", "S2"], heartsTwo)).toBe("T");
    expect(leadSuit(["BJ"], { suit: "NT", rank: "5", declarer: 1 })).toBe("T");
    expect(leadSuit(["SK"], null)).toBeNull();
  });
});

describe("followHint", () => {
  it("names the suit and the count", () => {
    expect(followHint(["SK", "SK", "SA"], heartsTwo)).toBe("Follow ♠: play 3 cards");
    expect(followHint(["BJ"], heartsTwo)).toBe("Follow trump: play 1 card");
    expect(followHint(["D4"], null)).toBe("Follow the lead: play 1 card");
  });
});

describe("followsSuit", () => {
  const trump = { suit: "S", rank: "2", declarer: 1 };
  const hand = ["C4", "C6", "C9", "D3", "D7", "D10", "H2", "S5"].map((code, i) => ({ id: i + 1, code }));
  const lead = ["DA", "DA", "DK"];
  it("refuses off-suit cards while the hand holds enough of the suit", () => {
    expect(followsSuit(hand, [1, 2, 3], lead, trump)).toBe(false);
    expect(followsSuit(hand, [4, 5, 6], lead, trump)).toBe(true);
  });
  it("asks only for every card of the suit when the hand is short", () => {
    const short = hand.filter((c) => c.code !== "D10");
    expect(followsSuit(short, [4, 5, 1], lead, trump)).toBe(true);
    expect(followsSuit(short, [4, 1, 2], lead, trump)).toBe(false);
  });
  it("counts a trump-rank card as trump, not its printed suit", () => {
    const tHand = [{ id: 1, code: "H2" }, { id: 2, code: "C4" }];
    expect(followsSuit(tHand, [2], ["S9"], trump)).toBe(false);
    expect(followsSuit(tHand, [1], ["S9"], trump)).toBe(true);
  });
  it("never blocks when the lead cannot be read", () => {
    expect(followsSuit(hand, [1, 2, 3], lead, null)).toBeNull();
  });
});
