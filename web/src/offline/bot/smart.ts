// Memory-aware bot: a port of shengji/ai/smart.py at its default settings
// (the served SmartBot). HeuristicBot plus card counting, boss detection,
// void inference and safer point feeding, all from public information.
import { type Card, type EffSuit, type Ordering, TRUMP, points } from "../engine/cards";
import { type Component, counter, decompose } from "../engine/combos";
import { suitCards, uniformSuit } from "../engine/legal";
import { HeuristicBot, LEAD_SUITS, PLAIN_SUITS, PLAIN_TOP, maxBy } from "./heuristic";
import { Memory } from "./memory";
import type { BotView } from "./view";

/** Trump-spend threshold when the win isn't guaranteed. */
const CONTEST_PTS = 10;

export class SmartBot extends HeuristicBot {
  constructor() {
    super();
    this.declareMin = 8;
    this.declareFinal = 6;
  }

  // ---------------------------------------------------------------- bury
  protected buryPointsMult(trumpCount: number, hasBigJoker: boolean): number {
    if (trumpCount >= 11 && hasBigJoker) return 1.5;
    if (trumpCount < 9 || !hasBigJoker) return 6.0;
    return 2.5;
  }

  protected buryShortBonus(suitLen: number): number {
    if (suitLen <= 3) return ({ 1: 15.0, 2: 12.0, 3: 8.0 } as Record<number, number>)[suitLen];
    return super.buryShortBonus(suitLen);
  }

  // ------------------------------------------------------------- helpers
  /** Boss components per ruff-safe plain suit, in S H D C order. */
  bossComponents(view: BotView, o: Ordering, mem: Memory): Map<EffSuit, Component[]> {
    const opps = [0, 1, 2, 3].filter((s) => s % 2 !== view.seat % 2);
    const out = new Map<EffSuit, Component[]>();
    for (const s of PLAIN_SUITS) {
      const cards = suitCards(view.hand, s, o);
      if (!cards.length || mem.ruffRisk(s, opps)) continue;
      const comps: Component[] = [];
      for (const comp of decompose(cards, o).components) {
        const topCode = maxBy(comp.cards, (c) => [o.level(c)]);
        const boss = comp.pairLen ? mem.pairIsBoss(topCode) : mem.isBoss(topCode);
        if (boss) comps.push(comp);
      }
      if (comps.length) out.set(s, comps);
    }
    return out;
  }

  // ---------------------------------------------------------------- lead
  protected lead(view: BotView, o: Ordering): Card[] {
    const mem = new Memory(view, o);
    const hand = view.hand;
    const opps = [0, 1, 2, 3].filter((s) => s % 2 !== view.seat % 2);
    const bySuit = new Map<EffSuit, Card[]>(LEAD_SUITS.map((s) => [s, suitCards(hand, s, o)]));
    const suit = (s: EffSuit): Card[] => bySuit.get(s)!;
    const boss = this.bossComponents(view, o, mem);

    type Entry = [[number, number, number], Card[]];
    const entry = (comp: Component): Entry => {
      let pts = 0;
      for (const c of comp.cards) pts += points(c);
      return [[comp.pairLen, pts, comp.top], [...comp.cards]];
    };

    // 0) Safe throw: several boss components in one suit.
    let bestThrow: Card[] | null = null;
    for (const comps of boss.values()) {
      if (comps.length >= 2) {
        const cards = comps.flatMap((c) => c.cards);
        if (bestThrow === null || cards.length > bestThrow.length) bestThrow = cards;
      }
    }
    if (bestThrow && bestThrow.length) return bestThrow;

    // 1) The longest ruff-safe tractor.
    let bestTr: Card[] | null = null;
    for (const s of PLAIN_SUITS) {
      if (mem.ruffRisk(s, opps)) continue;
      for (const comp of decompose(suit(s), o).components) {
        if (comp.pairLen >= 2 && (bestTr === null || comp.cards.length > bestTr.length)) bestTr = [...comp.cards];
      }
    }

    // 2) Boss pairs, then the tractor, then boss singles.
    const bossPaired: Entry[] = [];
    const bossSingle: Entry[] = [];
    for (const comps of boss.values()) for (const c of comps) if (c.pairLen) bossPaired.push(entry(c));
    for (const comps of boss.values()) for (const c of comps) if (!c.pairLen) bossSingle.push(entry(c));
    if (bossPaired.length) return maxBy(bossPaired, (e) => e[0])[1];
    if (bestTr && bestTr.length) return bestTr;
    if (bossSingle.length) return maxBy(bossSingle, (e) => e[0])[1];

    // 4) Plain suits no opponent has shown void in.
    const safe: [number, EffSuit][] = PLAIN_SUITS.filter((s) => suit(s).length && !opps.some((op) => mem.voids[op].has(s))).map((s) => [
      suit(s).length,
      s,
    ]);

    // Control leads: a late top trump pair, a good ruff-safe pair, emptying a
    // short suit, then a high non-point card from the longest safe suit.
    if (hand.length <= 12) {
      const tp: [number, Card][] = [];
      for (const [c, k] of counter(suit(TRUMP))) if (k >= 2) tp.push([o.level(c), c]);
      if (tp.length) {
        const [, c] = maxBy(tp, (x) => x);
        return [c, c];
      }
    }
    const ruffSafe = PLAIN_SUITS.filter((s) => suit(s).length && !mem.ruffRisk(s, opps));
    const pairs: [number, Card, EffSuit][] = [];
    for (const s of ruffSafe) for (const [c, k] of counter(suit(s))) if (k >= 2) pairs.push([o.level(c), c, s]);
    if (pairs.length) {
      const [lv, c] = maxBy(pairs, (x) => x);
      if (lv >= PLAIN_TOP + 1 - 5) return [c, c];
    }
    for (const s of ruffSafe) {
      if (suit(s).length <= 2) return [this.lowest(suit(s), o, { avoidPoints: true })];
    }
    if (safe.length) {
      const [, s2] = maxBy(safe, (x) => x);
      const nonpoint = suit(s2).filter((c) => points(c) === 0);
      if (nonpoint.length) return [maxBy(nonpoint, (c) => [o.level(c)])];
    }
    if (safe.length) {
      const [, s] = maxBy(safe, (x) => x);
      return [this.lowest(suit(s), o, { avoidPoints: true })];
    }
    const plain: [number, EffSuit][] = PLAIN_SUITS.filter((s) => suit(s).length).map((s) => [suit(s).length, s]);
    if (plain.length) {
      const [, s] = maxBy(plain, (x) => x);
      return [this.lowest(suit(s), o, { avoidPoints: true })];
    }
    return [this.lowest(suit(TRUMP), o, { avoidPoints: true })];
  }

  // -------------------------------------------------------------- follow
  protected follow(view: BotView, o: Ordering): Card[] {
    const mem = new Memory(view, o);
    const hand = view.hand;
    const seat = view.seat;
    const trick = view.trick!;
    const lead = trick.plays[0].cards;
    const nPlayed = trick.plays.length;
    const toAct: number[] = [];
    for (let i = nPlayed + 1; i < 4; i++) toAct.push((trick.leader + i) % 4);
    const oppToAct = toAct.filter((s) => s % 2 !== seat % 2);

    const w = this.currentWinner(trick.plays, o);
    const partnerWinning = w.seat % 2 === seat % 2;
    let trickPts = 0;
    for (const tp of trick.plays) for (const c of tp.cards) trickPts += points(c);

    if (partnerWinning) {
      // Feed points only when no one still to act can beat the partner.
      const secure = !mem.beatRisk(w.suit, w.top, oppToAct);
      return this.forcedFollow(hand, lead, o, secure);
    }

    const winning = this.cheapestWinning(hand, lead, w.suit, w.top, o);
    if (winning !== null) {
      const wSuit = o.effSuit(winning[0]);
      const usesTrump = wSuit === TRUMP && uniformSuit(lead, o) !== TRUMP;
      if (!usesTrump) {
        // In-suit wins are cheap tempo, unless the trick is pointless and the
        // win burns a premium trump (trump-rank card or joker).
        const premium = wSuit === TRUMP && Math.min(...winning.map((c) => o.level(c))) >= PLAIN_TOP + 1;
        if (!(premium && trickPts === 0)) return winning;
      }
      // Spending trump: memory decides whether it is worth it.
      const wTop = decompose(winning, o).topLevel();
      const holds = !mem.beatRisk(wSuit, wTop, oppToAct);
      const contestAt = hand.length <= 6 ? 0 : CONTEST_PTS;
      if (trickPts >= contestAt || (holds && trickPts > 0)) return winning;
    }
    return this.forcedFollow(hand, lead, o, false);
  }
}
