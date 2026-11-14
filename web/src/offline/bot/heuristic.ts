// Rule-based baseline bot: a port of shengji/ai/heuristic.py. Every choice
// keeps Python's iteration order and tie-breaking (hand order, Counter
// first-occurrence order, stable sorts, first-wins min/max, tuple order with
// strings compared by code point), so it makes the same decision as Python.
import { type Card, type EffSuit, type Ordering, TRUMP, cardRank, isJoker, points } from "../engine/cards";
import { type Component, type Decomposition, counter, decompose, findTractorRuns, pairCount } from "../engine/combos";
import { EngineAssertion, IllegalPlay, beats, suitCards, uniformSuit, validateFollow } from "../engine/legal";
import { type TrickPlay, trickWinner } from "../engine/round";
import { type BotView, viewOrdering } from "./view";

export const PLAIN_SUITS: EffSuit[] = ["S", "H", "D", "C"];
export const LEAD_SUITS: EffSuit[] = ["S", "H", "D", "C", TRUMP];

type Key = (number | string | boolean)[];

/** Python tuple comparison over numbers, booleans and strings. */
export function cmpKey(a: Key, b: Key): number {
  for (let i = 0; i < a.length; i++) {
    const x = a[i];
    const y = b[i];
    if (x === y) continue;
    if (typeof x === "string" && typeof y === "string") return x < y ? -1 : 1;
    return Number(x) < Number(y) ? -1 : 1;
  }
  return 0;
}

/** Python `min(items, key=key)`: the first minimal item. */
export function minBy<T>(items: readonly T[], key: (x: T) => Key): T {
  if (!items.length) throw new Error("min() arg is an empty sequence");
  let best = items[0];
  let bk = key(best);
  for (let i = 1; i < items.length; i++) {
    const k = key(items[i]);
    if (cmpKey(k, bk) < 0) {
      best = items[i];
      bk = k;
    }
  }
  return best;
}

/** Python `max(items, key=key)`: the first maximal item. */
export function maxBy<T>(items: readonly T[], key: (x: T) => Key): T {
  if (!items.length) throw new Error("max() arg is an empty sequence");
  let best = items[0];
  let bk = key(best);
  for (let i = 1; i < items.length; i++) {
    const k = key(items[i]);
    if (cmpKey(k, bk) > 0) {
      best = items[i];
      bk = k;
    }
  }
  return best;
}

/** Python `sorted(items, key=key)` (stable). */
export function sortedBy<T>(items: readonly T[], key: (x: T) => Key): T[] {
  return items
    .map((x) => [key(x), x] as const)
    .sort((a, b) => cmpKey(a[0], b[0]))
    .map(([, x]) => x);
}

/** Remove the first occurrence of each card in `cards` from `pool`. */
export function take(pool: Card[], cards: readonly Card[]): void {
  for (const c of cards) {
    const i = pool.indexOf(c);
    if (i < 0) throw new Error(`list.remove(x): ${c} not in list`);
    pool.splice(i, 1);
  }
}

function minus(hand: readonly Card[], used: readonly Card[]): Card[] {
  const pool = [...hand];
  take(pool, used);
  return pool;
}

/** The top plain level, len(Ordering.plain_ranks) - 1: twelve plain ranks remain once the trump rank is removed. */
export const PLAIN_TOP = 11;

export function leadSuitGroups(hand: readonly Card[], o: Ordering): Map<EffSuit, Card[]> {
  const groups = new Map<EffSuit, Card[]>(LEAD_SUITS.map((s) => [s, []]));
  for (const c of hand) groups.get(o.effSuit(c))!.push(c);
  return groups;
}

export interface Winner {
  seat: number;
  suit: EffSuit;
  top: number;
}

export class HeuristicBot {
  /** Trump count needed to declare during the deal. */
  declareMin = 9;
  /** Lower bar in the grace window. */
  declareFinal = 7;
  /** When dumping junk, prefer emptying short suits. */
  voidDump = true;

  // ------------------------------------------------------------- declare
  /** The declaration to make now, or null to pass. `final` is the grace-window call. */
  declare(view: BotView, final = false): Card[] | null {
    const options = declareOptions(view);
    if (!options.length) return null;
    const hand = view.hand;
    let best: Card[] | null = null;
    let bestScore = 0;
    for (const opt of options) {
      const code = opt[0];
      let score: number;
      if (isJoker(code)) {
        const nRank = hand.filter((c) => cardRank(c) === view.trumpRank).length;
        score = nRank >= 3 ? 14 + nRank : 0;
      } else {
        const suit = code[0];
        const nTrump = hand.filter((c) => isJoker(c) || cardRank(c) === view.trumpRank || c[0] === suit).length;
        score = nTrump + (opt.length === 2 ? 2 : 0);
      }
      if (score > bestScore) {
        best = opt;
        bestScore = score;
      }
    }
    return bestScore >= (final ? this.declareFinal : this.declareMin) ? best : null;
  }

  // ---------------------------------------------------------------- bury
  /** The eight cards the banker buries. */
  bury(view: BotView): Card[] {
    const o = viewOrdering(view);
    const hand = [...view.hand];
    const cnt = counter(hand);
    const suitLen = counter(hand.map((c) => o.effSuit(c)));
    const top = PLAIN_TOP;
    const trumpLen = suitLen.get(TRUMP) ?? 0;
    const hasBJ = hand.includes("BJ");
    const keepValue = (c: Card): number => {
      if (o.effSuit(c) === TRUMP) return 100 + o.level(c);
      let v = o.level(c);
      if (o.level(c) >= top) v += 40;
      if (cnt.get(c)! >= 2) v += 25;
      v += points(c) * this.buryPointsMult(trumpLen, hasBJ);
      v -= this.buryShortBonus(suitLen.get(o.effSuit(c))!);
      return v;
    };
    return sortedBy(hand, (c) => [keepValue(c)]).slice(0, 8);
  }

  protected buryShortBonus(suitLen: number): number {
    return (8 - Math.min(suitLen, 8)) * 0.5;
  }

  protected buryPointsMult(_trumpCount: number, _hasBigJoker: boolean): number {
    return 2.5;
  }

  // ---------------------------------------------------------------- play
  /** The cards to play now (lead or follow). Always legal for a follow; a lead may be a throw. */
  play(view: BotView): Card[] {
    const o = viewOrdering(view);
    const trick = view.trick;
    if (!trick) throw new EngineAssertion("no trick in progress");
    if (!trick.plays.length) return this.lead(view, o);
    let play = this.follow(view, o);
    try {
      validateFollow(play, view.hand, trick.plays[0].cards, o);
    } catch (e) {
      if (!(e instanceof IllegalPlay)) throw e;
      play = this.forcedFollow(view.hand, trick.plays[0].cards, o, false);
    }
    return play;
  }

  // ---------------------------------------------------------------- lead
  protected lead(view: BotView, o: Ordering): Card[] {
    const hand = view.hand;
    const bySuit = leadSuitGroups(hand, o);
    let bestTr: Card[] | null = null;
    for (const cards of bySuit.values()) {
      const availablePairs = pairCount(cards);
      if (availablePairs < 2) continue;
      for (let k = Math.min(5, availablePairs); k > 1; k--) {
        const runs = findTractorRuns(cards, o, k);
        if (runs.length && (bestTr === null || runs[runs.length - 1].length > bestTr.length)) {
          bestTr = runs[runs.length - 1];
          break;
        }
      }
    }
    if (bestTr && bestTr.length) return bestTr;

    const top = PLAIN_TOP;
    for (const s of PLAIN_SUITS) {
      const aces = bySuit.get(s)!.filter((c) => o.level(c) === top);
      if (aces.length >= 2) return aces.slice(0, 2);
    }
    for (const s of PLAIN_SUITS) {
      const aces = bySuit.get(s)!.filter((c) => o.level(c) === top);
      if (aces.length) return aces.slice(0, 1);
    }
    const pairs: [number, Card][] = [];
    for (const [c, n] of counter(hand)) if (n >= 2 && PLAIN_SUITS.includes(o.effSuit(c))) pairs.push([o.level(c), c]);
    if (pairs.length) {
      const [lv, c] = maxBy(pairs, (p) => p);
      if (lv >= top - 3) return [c, c];
    }
    const plain = PLAIN_SUITS.filter((s) => bySuit.get(s)!.length).map((s) => [bySuit.get(s)!.length, s] as [number, EffSuit]);
    if (plain.length) {
      const [, s] = maxBy(plain, (p) => p);
      return [this.lowest(bySuit.get(s)!, o, { avoidPoints: true })];
    }
    return [this.lowest(bySuit.get(TRUMP)!, o, { avoidPoints: true })];
  }

  // -------------------------------------------------------------- follow
  protected follow(view: BotView, o: Ordering): Card[] {
    const trick = view.trick!;
    const hand = view.hand;
    const seat = view.seat;
    const lead = trick.plays[0].cards;
    const w = this.currentWinner(trick.plays, o);
    const partnerWinning = w.seat % 2 === seat % 2;
    let trickPts = 0;
    for (const tp of trick.plays) for (const c of tp.cards) trickPts += points(c);
    const isLast = trick.plays.length === 3;
    if (partnerWinning) {
      const strong = w.suit === TRUMP || w.top >= PLAIN_TOP;
      return this.forcedFollow(hand, lead, o, strong || isLast);
    }
    const winning = this.cheapestWinning(hand, lead, w.suit, w.top, o);
    if (winning !== null) {
      const usesTrump = o.effSuit(winning[0]) === TRUMP && uniformSuit(lead, o) !== TRUMP;
      const worth = trickPts >= 10 || (isLast && trickPts > 0) || !usesTrump;
      if (worth) return winning;
    }
    return this.forcedFollow(hand, lead, o, false);
  }

  currentWinner(plays: readonly TrickPlay[], o: Ordering): Winner {
    return trickWinner(plays, o);
  }

  /** The cheapest play that would take the trick from the incumbent, or null. */
  cheapestWinning(hand: readonly Card[], lead: readonly Card[], incSuit: EffSuit, incTop: number, o: Ordering): Card[] | null {
    const leadDec = decompose(lead, o);
    const leadSuit = uniformSuit(lead, o);
    if (leadSuit === null) throw new EngineAssertion();
    const hLead = suitCards(hand, leadSuit, o);
    if (leadDec.components.length !== 1) {
      if (leadSuit === TRUMP || hLead.length) return null;
      const trumps = suitCards(hand, TRUMP, o);
      if (trumps.length < lead.length) return null;
      const play = this.trumpShapeMatch(trumps, leadDec, o);
      if (play !== null) {
        const [won] = beats(play, lead, incSuit, incTop, o);
        if (won) return play;
      }
      return null;
    }
    const comp = leadDec.components[0];
    const comboIn = (cards: readonly Card[], minTop: number): Card[] | null => {
      if (comp.kind === "single") {
        const cands = sortedBy(
          cards.filter((c) => o.level(c) > minTop),
          (c) => [o.level(c)],
        );
        return cands.length ? [cands[0]] : null;
      }
      if (comp.kind === "pair") {
        const pairCodes: Card[] = [];
        for (const [c, n] of counter(cards)) if (n >= 2 && o.level(c) > minTop) pairCodes.push(c);
        const cands = sortedBy(pairCodes, (c) => [o.level(c)]);
        return cands.length ? [cands[0], cands[0]] : null;
      }
      const runs = findTractorRuns(cards, o, comp.pairLen).filter((r) => o.level(r[r.length - 1]) > minTop);
      return runs.length ? runs[0] : null;
    };
    if (hLead.length >= lead.length) {
      if (incSuit === leadSuit) return comboIn(hLead, incTop);
      return null;
    }
    if (hLead.length) return null;
    const trumps = suitCards(hand, TRUMP, o);
    if (leadSuit !== TRUMP && trumps.length >= lead.length) {
      const floor = incSuit === TRUMP ? incTop : -1;
      return comboIn(trumps, floor);
    }
    return null;
  }

  /** Cheapest all-trump set matching a throw's shape (runs + singles). */
  protected trumpShapeMatch(trumps: readonly Card[], leadDec: Decomposition, o: Ordering): Card[] | null {
    const runs = leadDec.components
      .filter((c: Component) => c.pairLen)
      .map((c) => c.pairLen)
      .sort((a, b) => b - a);
    const nSingles = leadDec.components.filter((c) => !c.pairLen).length;
    const pool = [...trumps];
    const picked: Card[] = [];
    for (const k of runs) {
      if (k === 1) {
        const codes: Card[] = [];
        for (const [c, n] of counter(pool)) if (n >= 2) codes.push(c);
        const pairs = sortedBy(codes, (c) => [o.level(c)]);
        if (!pairs.length) return null;
        const c = pairs[0];
        picked.push(c, c);
        take(pool, [c, c]);
      } else {
        const rs = findTractorRuns(pool, o, k);
        if (!rs.length) return null;
        picked.push(...rs[0]);
        take(pool, rs[0]);
      }
    }
    for (let i = 0; i < nSingles; i++) {
      if (!pool.length) return null;
      const c = this.lowest(pool, o, { avoidPoints: true });
      picked.push(c);
      take(pool, [c]);
    }
    return picked;
  }

  /** A legal minimal follow, dumping points if asked; cards in `avoid` are kept back when possible. */
  forcedFollow(hand: readonly Card[], lead: readonly Card[], o: Ordering, preferPoints: boolean, avoid: ReadonlySet<Card> = new Set()): Card[] {
    const n = lead.length;
    const leadSuit = uniformSuit(lead, o);
    if (leadSuit === null) throw new EngineAssertion();
    const hSuit = suitCards(hand, leadSuit, o);
    const opts = { avoidPoints: !preferPoints, seekPoints: preferPoints, avoid };
    if (n === 1) return [this.lowest(hSuit.length ? hSuit : hand, o, opts)];
    let picked: Card[] = [];
    let fillPool: Card[];
    if (hSuit.length >= n) {
      const pool = [...hSuit];
      const leadDec = decompose(lead, o);
      if (leadDec.components.length === 1 && leadDec.components[0].kind === "tractor") {
        const runs = findTractorRuns(pool, o, leadDec.components[0].pairLen);
        if (runs.length) {
          picked.push(...runs[0]);
          take(pool, runs[0]);
        }
      }
      const need = Math.min(leadDec.nPairs, pairCount(hSuit)) - pairCount(picked);
      const codes: Card[] = [];
      for (const [c, k] of counter(pool)) if (k >= 2) codes.push(c);
      const pairs = sortedBy(codes, (c) => [avoid.has(c), o.level(c)]);
      for (const c of pairs.slice(0, Math.max(0, need))) {
        picked.push(c, c);
        take(pool, [c, c]);
      }
      fillPool = pool;
    } else {
      picked = [...hSuit];
      fillPool = minus(hand, picked);
    }
    while (picked.length < n) {
      const c = this.lowest(fillPool, o, opts);
      picked.push(c);
      take(fillPool, [c]);
    }
    return picked.slice(0, n);
  }

  /** The card to give up: lowest by the junk or point-seeking key. */
  lowest(
    cards: readonly Card[],
    o: Ordering,
    opts: { avoidPoints?: boolean; seekPoints?: boolean; avoid?: ReadonlySet<Card> } = {},
  ): Card {
    if (cards.length === 1) return cards[0];
    const avoid = opts.avoid ?? new Set<Card>();
    if (opts.seekPoints) {
      return minBy(cards, (c) => [avoid.has(c), -points(c), o.effSuit(c) === TRUMP, o.level(c)]);
    }
    const suitN = this.voidDump ? counter(cards.map((c) => o.effSuit(c))) : null;
    return minBy(cards, (c) => {
      const trumpish = o.effSuit(c) === TRUMP;
      const vlen = suitN && !trumpish ? suitN.get(o.effSuit(c))! : 0;
      if (opts.avoidPoints) return [avoid.has(c), trumpish, points(c) > 0, vlen, o.level(c)];
      return [avoid.has(c), trumpish, vlen, o.level(c)];
    });
  }
}

/** Declarations this seat could make now that beat the current one (Round.declare_options). */
export function declareOptions(view: BotView): Card[][] {
  if (view.phase !== "deal" && view.phase !== "declare") return [];
  const current = view.declaration ? view.declaration.strength : 0;
  const hand = counter(view.hand);
  const options: Card[][] = [];
  for (const code of [...hand.keys()].sort()) {
    const n = hand.get(code)!;
    if (cardRank(code) === view.trumpRank) {
      if (current < 1) options.push([code]);
      if (n >= 2 && current < 2) options.push([code, code]);
    }
    if (code === "LJ" && n >= 2 && current < 3) options.push([code, code]);
    if (code === "BJ" && n >= 2 && current < 4) options.push([code, code]);
  }
  return options;
}
