// The follow hint names the lead's effective suit and its card count, from
// the lead and the trump alone.
import { describe, expect, it } from "vitest";
import type { Trump } from "./protocol";
import { followHint, followsSuit, leadSuit, winningSeat } from "./followRules";
import { IllegalPlay, RANKS, makeDeck, orderingFor, validateFollow } from "./offline/engine";

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
  const trump: Trump = { suit: "S", rank: "2", declarer: 1 };
  const hand = ["C4", "C6", "C9", "D3", "D7", "D10", "H2", "S5"].map((code, i) => ({ id: i + 1, code }));
  const lead = ["DA", "DA", "DK"];
  it("refuses off-suit cards while the hand holds enough of the suit", () => {
    expect(followsSuit(hand, [1, 2, 3], lead, trump)).toBe(false);
    expect(followsSuit(hand, [4, 5, 1], lead, trump)).toBe(false);
    expect(followsSuit(hand, [4, 5, 6], lead, trump)).toBe(true);
  });
  it("asks only for every card of the suit when the hand is short", () => {
    const short = hand.filter((c) => c.code !== "D10");
    expect(followsSuit(short, [4, 5, 1], lead, trump)).toBe(true);
    expect(followsSuit(short, [4, 1, 2], lead, trump)).toBe(false);
  });
  it("lets anything go when the hand holds none of the suit", () => {
    const none = hand.filter((c) => c.code[0] !== "D");
    expect(followsSuit(none, [1, 2, 3], lead, trump)).toBe(true);
  });
  it("counts a trump-rank card and a joker as trump, not their printed suit", () => {
    const tHand = [{ id: 1, code: "H2" }, { id: 2, code: "C4" }, { id: 3, code: "BJ" }, { id: 4, code: "S9" }];
    expect(followsSuit(tHand, [2], ["S9"], trump)).toBe(false);
    expect(followsSuit(tHand, [1], ["S9"], trump)).toBe(true);
    expect(followsSuit(tHand, [3], ["SK"], trump)).toBe(true);
    // a heart lead cannot be followed by the heart-printed trump-rank card
    expect(followsSuit([{ id: 1, code: "H2" }, { id: 2, code: "HK" }], [1], ["H5"], trump)).toBe(false);
  });
  it("never blocks when the lead or the trump cannot be read", () => {
    expect(followsSuit(hand, [1, 2, 3], lead, null)).toBeNull();
    expect(followsSuit(hand, [1, 2, 3], [], trump)).toBeNull();
    expect(followsSuit(hand, [1, 2, 3], ["DA", "CA"], trump)).toBeNull();
    expect(followsSuit(hand, [1], ["D4"], { suit: "X", rank: "2", declarer: 0 })).toBeNull();
  });

  // Against the offline engine (a port of the server's follow rules): any
  // play the engine accepts passes, and any it blocks the engine refuses.
  it("never blocks a follow the engine accepts, over many random deals", () => {
    let seed = 0x5eed;
    const rand = () => { seed = (seed * 1103515245 + 12345) & 0x7fffffff; return seed / 0x80000000; };
    const pick = <T,>(xs: readonly T[]) => xs[Math.floor(rand() * xs.length)];
    const shuffle = <T,>(xs: T[]) => { for (let i = xs.length - 1; i > 0; i--) { const j = Math.floor(rand() * (i + 1)); [xs[i], xs[j]] = [xs[j], xs[i]]; } return xs; };
    let accepted = 0;
    let blocked = 0;
    for (let deal = 0; deal < 400; deal++) {
      const tSuit = pick(["S", "H", "D", "C", "NT"] as const);
      const t: Trump = { suit: tSuit, rank: pick(RANKS), declarer: 0 };
      const ordering = orderingFor(tSuit === "NT" ? null : tSuit, t.rank);
      const deck = shuffle(makeDeck());
      const eff = ordering.effSuit(pick(deck));
      const n = 1 + Math.floor(rand() * 4);
      const pool = deck.filter((c) => ordering.effSuit(c) === eff);
      const ld = pool.slice(0, n);
      const rest = [...deck];
      for (const c of ld) rest.splice(rest.indexOf(c), 1);
      const size = 4 + Math.floor(rand() * 22);
      const codes = rest.slice(0, size);
      const h = codes.map((code, i) => ({ id: i + 1, code }));
      const suitIds = h.filter((c) => ordering.effSuit(c.code) === eff).map((c) => c.id);
      const otherIds = h.filter((c) => ordering.effSuit(c.code) !== eff).map((c) => c.id);
      for (let trial = 0; trial < 30; trial++) {
        const k = Math.floor(rand() * (n + 1));
        const chosen = [...shuffle([...suitIds]).slice(0, k), ...shuffle([...otherIds])].slice(0, n);
        if (chosen.length !== n) continue;
        const play = chosen.map((id) => h[id - 1].code);
        let legal = true;
        try { validateFollow(play, codes, ld, ordering); } catch (e) {
          if (!(e instanceof IllegalPlay)) throw e;
          legal = false;
        }
        const verdict = followsSuit(h, chosen, ld, t);
        expect(verdict).not.toBeNull();
        if (legal) { accepted += 1; expect(verdict, `${t.suit}${t.rank} lead ${ld} play ${play}`).toBe(true); }
        if (verdict === false) { blocked += 1; expect(legal).toBe(false); }
      }
    }
    expect(accepted).toBeGreaterThan(1000);
    expect(blocked).toBeGreaterThan(1000);
  });
});

describe("winningSeat", () => {
  const trump: Trump = heartsTwo;
  it("names the play taking an open trick: higher in suit, then a trump ruff", () => {
    expect(winningSeat([{ seat: 1, cards: ["S5"] }], trump)).toBeNull();
    expect(winningSeat([{ seat: 1, cards: ["S5"] }, { seat: 2, cards: ["SK"] }], trump)).toBe(2);
    expect(winningSeat([{ seat: 1, cards: ["S5"] }, { seat: 2, cards: ["SK"] }, { seat: 3, cards: ["H3"] }], trump)).toBe(3);
    // an off-suit card never takes it, however high
    expect(winningSeat([{ seat: 1, cards: ["S5"] }, { seat: 2, cards: ["DA"] }], trump)).toBe(1);
    // a pair lead is not beaten by two singles of the suit
    expect(winningSeat([{ seat: 0, cards: ["S5", "S5"] }, { seat: 1, cards: ["SK", "SA"] }], trump)).toBe(0);
  });
  it("is null without a trump", () => {
    expect(winningSeat([{ seat: 1, cards: ["S5"] }, { seat: 2, cards: ["SK"] }], null)).toBeNull();
  });
});
