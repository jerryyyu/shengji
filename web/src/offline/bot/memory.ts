// Public-information card memory: a port of the parts of
// shengji/ai/memory.py that SmartBot's decisions read (played cards, shown
// voids, the unseen pool and the boss / ruff / beat queries). Built from the
// public trick history plus the seat's own hand and, for the banker, its own
// buried cards.
import { type Card, type EffSuit, type Ordering, TRUMP, makeDeck, points, sortedCodes } from "../engine/cards";
import type { BotView } from "./view";

const DECK_CODES: Card[] = sortedCodes([...new Set(makeDeck())]);

export class Memory {
  readonly o: Ordering;
  readonly seat: number;
  readonly played = new Map<Card, number>();
  readonly voids: Set<EffSuit>[] = [new Set(), new Set(), new Set(), new Set()];
  /** Unseen copies per code, in sorted-code order. */
  readonly unseen = new Map<Card, number>();

  constructor(view: BotView, o: Ordering, ownKitty = true) {
    this.o = o;
    this.seat = view.seat;
    const tricks = [...view.history];
    if (view.trick && view.trick.plays.length) tricks.push(view.trick);
    for (const trick of tricks) {
      const leadSuit = o.effSuit(trick.plays[0].cards[0]);
      trick.plays.forEach((tp, i) => {
        for (const c of tp.cards) this.played.set(c, (this.played.get(c) ?? 0) + 1);
        if (i === 0) return;
        if (tp.cards.some((c) => o.effSuit(c) !== leadSuit)) this.voids[tp.seat].add(leadSuit);
      });
    }
    const own = new Map<Card, number>();
    const mine = ownKitty && view.banker === view.seat && view.ownBuried.length ? [...view.hand, ...view.ownBuried] : view.hand;
    for (const c of mine) own.set(c, (own.get(c) ?? 0) + 1);
    for (const code of DECK_CODES) {
      const n = 2 - (this.played.get(code) ?? 0) - (own.get(code) ?? 0);
      if (n > 0) this.unseen.set(code, n);
    }
  }

  /** How many unseen cards of `eff` beat `level`. */
  higherUnseen(eff: EffSuit, level: number): number {
    let n = 0;
    for (const [c, k] of this.unseen) if (this.o.effSuit(c) === eff && this.o.level(c) > level) n += k;
    return n;
  }

  /** No unseen card outranks this one. */
  isBoss(code: Card): boolean {
    return this.higherUnseen(this.o.effSuit(code), this.o.level(code)) === 0;
  }

  /** A pair is beaten only by a higher pair: boss iff no higher code has two unseen copies. */
  pairIsBoss(code: Card): boolean {
    const lvl = this.o.level(code);
    const eff = this.o.effSuit(code);
    for (const [c, n] of this.unseen) if (this.o.effSuit(c) === eff && this.o.level(c) > lvl && n >= 2) return false;
    return true;
  }

  pointsLeft(eff: EffSuit | null = null): number {
    let t = 0;
    for (const [c, n] of this.unseen) if (eff === null || this.o.effSuit(c) === eff) t += points(c) * n;
    return t;
  }

  unseenTrumps(): number {
    let n = 0;
    for (const [c, k] of this.unseen) if (this.o.effSuit(c) === TRUMP) n += k;
    return n;
  }

  private suitRemaining(eff: EffSuit): number {
    let n = 0;
    for (const [c, k] of this.unseen) if (this.o.effSuit(c) === eff) n += k;
    return n;
  }

  /** Could any of `seats` trump a lead of `leadSuit`? */
  ruffRisk(leadSuit: EffSuit, seats: readonly number[]): boolean {
    if (leadSuit === TRUMP || this.unseenTrumps() === 0) return false;
    // A suit with two or fewer unseen cards counts as a possible void for any seat.
    return seats.some((s) => this.voids[s].has(leadSuit) || this.suitRemaining(leadSuit) <= 2);
  }

  /** Could any of `seats` beat a card of (eff, level), in suit or by ruffing? */
  beatRisk(eff: EffSuit, level: number, seats: readonly number[]): boolean {
    const inSuit = this.higherUnseen(eff, level) > 0 && seats.some((s) => !this.voids[s].has(eff));
    return inSuit || this.ruffRisk(eff, seats);
  }
}
