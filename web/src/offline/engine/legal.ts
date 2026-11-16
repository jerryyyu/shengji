// Lead/follow legality and trick comparison: a port of
// server/shengji/engine/legal.py, with the exact IllegalPlay messages.
//
// Follow rules: play as many cards as the lead. Holding enough of the led
// effective suit, every card comes from it, pairs are owed up to the number
// led (as many as held), and a single-tractor lead owes a tractor of that
// length when one is held. Holding some but not enough, play them all and
// fill freely. Void, play anything; an all-trump shape match contends.
import { type Card, type EffSuit, type Ordering, TRUMP, sortedCodes } from "./cards";
import { type Component, counter, decompose, decomposeMatching, findTractorRuns, hasTractor, pairCount } from "./combos";

export class IllegalPlay extends Error {
  constructor(message: string) {
    super(message);
    this.name = "IllegalPlay";
  }
}

/** A Python `assert` in the reference engine: a caller contract violation. */
export class EngineAssertion extends Error {
  constructor(message = "AssertionError") {
    super(message);
    this.name = "AssertionError";
  }
}

export function suitCards(hand: readonly Card[], eff: EffSuit, ordering: Ordering): Card[] {
  return hand.filter((c) => ordering.effSuit(c) === eff);
}

export function isSubmultiset(small: readonly Card[], big: readonly Card[]): boolean {
  if (!small.length) return true;
  const cb = counter(big);
  for (const [c, n] of counter(small)) if ((cb.get(c) ?? 0) < n) return false;
  return true;
}

export function checkInHand(hand: readonly Card[], play: readonly Card[]): void {
  if (!play.length || !isSubmultiset(play, hand)) throw new IllegalPlay("You don't hold those cards.");
}

export function uniformSuit(play: readonly Card[], ordering: Ordering): EffSuit | null {
  const suits = new Set(play.map((c) => ordering.effSuit(c)));
  return suits.size === 1 ? [...suits][0] : null;
}

export interface LeadVerdict {
  /** The cards actually played: the attempt, or a failed throw's forced component. */
  actual: Card[];
  /** The failed-throw message, or null when the lead stands. */
  message: string | null;
}

/**
 * Validate a lead against the other three hands. Singles, pairs and tractors
 * always stand. A multi-component throw fails when any component can be beaten
 * in-suit by another hand; the leader then plays the lowest beatable component
 * (by pair length, then level; first in component order on a tie).
 */
export function validateLead(
  play: readonly Card[],
  hand: readonly Card[],
  otherHands: readonly (readonly Card[])[],
  ordering: Ordering,
): LeadVerdict {
  checkInHand(hand, play);
  const eff = uniformSuit(play, ordering);
  if (eff === null) throw new IllegalPlay("A lead must be a single suit (throws included).");
  const dec = decompose(play, ordering);
  if (dec.components.length === 1) return { actual: [...play], message: null };
  let lowest: Component | null = null;
  for (const comp of dec.components) {
    for (const other of otherHands) {
      const oc = suitCards(other, eff, ordering);
      let beaten: boolean;
      if (comp.pairLen === 0) {
        beaten = oc.some((c) => ordering.level(c) > comp.top);
      } else if (comp.pairLen === 1) {
        beaten = false;
        for (const [c, n] of counter(oc)) if (n >= 2 && ordering.level(c) > comp.top) beaten = true;
      } else {
        beaten = findTractorRuns(oc, ordering, comp.pairLen).some(
          (r) => ordering.level(r[r.length - 1]) > comp.top,
        );
      }
      if (beaten) {
        if (
          lowest === null ||
          comp.pairLen < lowest.pairLen ||
          (comp.pairLen === lowest.pairLen && comp.top < lowest.top)
        ) {
          lowest = comp;
        }
      }
    }
  }
  if (lowest !== null) {
    return { actual: [...lowest.cards], message: "Throw failed — forced to play " + lowest.cards.join("+") };
  }
  return { actual: [...play], message: null };
}

/** Throws IllegalPlay when `play` is not a legal response to `lead`. */
export function validateFollow(
  play: readonly Card[],
  hand: readonly Card[],
  lead: readonly Card[],
  ordering: Ordering,
): void {
  checkInHand(hand, play);
  if (play.length !== lead.length) throw new IllegalPlay(`Must play exactly ${lead.length} card(s).`);
  const eff = uniformSuit(lead, ordering);
  if (eff === null) throw new EngineAssertion("lead is not one effective suit");
  const hSuit = suitCards(hand, eff, ordering);
  const pSuit = suitCards(play, eff, ordering);
  if (hSuit.length >= lead.length) {
    if (pSuit.length !== play.length) throw new IllegalPlay("You must follow suit.");
    const leadDec = decompose(lead, ordering);
    if (leadDec.nPairs) {
      const needPairs = Math.min(leadDec.nPairs, pairCount(hSuit));
      if (pairCount(play) < needPairs) throw new IllegalPlay("You must play pairs from the led suit.");
    }
    if (leadDec.components.length === 1 && leadDec.components[0].kind === "tractor") {
      const k = leadDec.components[0].pairLen;
      if (hasTractor(hSuit, ordering, k) && decompose(play, ordering).maxPairRun() < k) {
        throw new IllegalPlay(`You must follow with a tractor of ${k} pairs.`);
      }
    }
  } else if (!isSubmultiset(hSuit, play)) {
    throw new IllegalPlay("You must play all your cards of the led suit.");
  }
}

/**
 * Does `challenger` beat the current best play? Returns [wins, top]. It must be
 * one suit and match the lead's shape; then it wins by a higher top in the
 * incumbent's suit, or by being trump over non-trump.
 */
export function beats(
  challenger: readonly Card[],
  lead: readonly Card[],
  incumbentSuit: EffSuit,
  incumbentTop: number,
  ordering: Ordering,
): [boolean, number] {
  const eff = uniformSuit(challenger, ordering);
  if (eff === null) return [false, 0];
  let top: number;
  if (challenger.length === 1 && lead.length === 1) {
    top = ordering.level(challenger[0]);
  } else {
    const chDec = decomposeMatching(challenger, ordering, decompose(lead, ordering).shape());
    if (chDec === null) return [false, 0];
    top = chDec.topLevel();
  }
  if (eff === incumbentSuit) return [top > incumbentTop, top];
  if (eff === TRUMP) return [true, top];
  return [false, 0];
}

// Candidate enumeration. The fixture generator
// (server/scripts/gen_offline_engine_fixtures.py) enumerates in this exact
// order: distinct codes in string order, copies of each code ascending,
// depth first.

const LEAD_SUIT_ORDER: EffSuit[] = ["S", "H", "C", "D", "T"];

function distinct(cards: readonly Card[]): [Card[], number[]] {
  const cnt = counter(cards);
  const codes = sortedCodes([...cnt.keys()]);
  return [codes, codes.map((c) => cnt.get(c)!)];
}

/** Number of distinct sub-multisets of `cards` with `n` cards. */
export function countSubmultisets(cards: readonly Card[], n: number): number {
  const [, counts] = distinct(cards);
  let ways = new Array<number>(n + 1).fill(0);
  ways[0] = 1;
  for (const k of counts) {
    const nxt = new Array<number>(n + 1).fill(0);
    for (let total = 0; total <= n; total++) {
      if (!ways[total]) continue;
      for (let t = 0; t <= Math.min(k, n - total); t++) nxt[total + t] += ways[total];
    }
    ways = nxt;
  }
  return ways[n];
}

/** Every distinct sub-multiset of `cards` with `n` cards, in canonical order. */
export function submultisets(cards: readonly Card[], n: number): Card[][] {
  const [codes, counts] = distinct(cards);
  const out: Card[][] = [];
  const cur: Card[] = [];
  const rec = (i: number, left: number): void => {
    if (left === 0) {
      out.push([...cur]);
      return;
    }
    if (i === codes.length) return;
    for (let t = 0; t <= Math.min(counts[i], left); t++) {
      for (let x = 0; x < t; x++) cur.push(codes[i]);
      rec(i + 1, left - t);
      cur.length -= t;
    }
  };
  rec(0, n);
  return out;
}

/** The hand's effective-suit groups, in S H C D T order, empty ones skipped. */
export function leadGroups(hand: readonly Card[], ordering: Ordering): Card[][] {
  return LEAD_SUIT_ORDER.map((eff) => suitCards(hand, eff, ordering)).filter((g) => g.length);
}

export function countLeadCandidates(hand: readonly Card[], ordering: Ordering): number {
  let n = 0;
  for (const g of leadGroups(hand, ordering)) for (let k = 1; k <= g.length; k++) n += countSubmultisets(g, k);
  return n;
}

/** Every lead attempt the engine accepts: each non-empty single-suit sub-multiset. */
export function leadCandidates(hand: readonly Card[], ordering: Ordering): Card[][] {
  const out: Card[][] = [];
  for (const g of leadGroups(hand, ordering)) for (let k = 1; k <= g.length; k++) out.push(...submultisets(g, k));
  return out;
}
