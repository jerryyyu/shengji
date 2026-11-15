// Card primitives and trump-aware ordering: a port of
// server/shengji/engine/cards.py. Card codes are the server's strings
// ("S2".."SA", "H10", "LJ", "BJ"); two decks make 108 cards.

export type Card = string;
/** An effective suit: S H D C, or "T" for every trump card. */
export type EffSuit = "S" | "H" | "D" | "C" | "T";
/** A trump suit, or null for no trump. */
export type TrumpSuit = "S" | "H" | "D" | "C" | null;

export const RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"] as const;
export type Rank = (typeof RANKS)[number];
export const SUITS = "SHDC";
export const LJ = "LJ";
export const BJ = "BJ";
export const TRUMP = "T";

export function makeDeck(): Card[] {
  const one: Card[] = [];
  for (const s of SUITS) for (const r of RANKS) one.push(s + r);
  one.push(LJ, BJ);
  return [...one, ...one];
}

export function isJoker(code: Card): boolean {
  return code === LJ || code === BJ;
}

export function cardSuit(code: Card): string | null {
  return isJoker(code) ? null : code[0];
}

export function cardRank(code: Card): string | null {
  return isJoker(code) ? null : code.slice(1);
}

export function points(code: Card): number {
  const r = cardRank(code);
  if (r === "5") return 5;
  if (r === "10" || r === "K") return 10;
  return 0;
}

export function totalPoints(codes: Iterable<Card>): number {
  let t = 0;
  for (const c of codes) t += points(c);
  return t;
}

/** Python's default string order on card codes (all ASCII). */
export function codeCmp(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

/** `sorted(cards)` in Python. */
export function sortedCodes(cards: readonly Card[]): Card[] {
  return [...cards].sort(codeCmp);
}

const SUIT_KEY: Record<EffSuit, number> = { S: 0, H: 1, C: 2, D: 3, T: 4 };
const ALL_CODES: Card[] = sortedCodes([...new Set(makeDeck())]);

/**
 * Card comparison and grouping for a fixed trump suit and trump rank.
 * Every card has an effective suit (its own, or "T") and a level within it;
 * levels are consecutive, so tractor adjacency is a level difference of 1.
 */
export class Ordering {
  readonly trumpSuit: TrumpSuit;
  readonly trumpRank: string;
  private readonly eff = new Map<Card, EffSuit>();
  private readonly lvl = new Map<Card, number>();
  private readonly plainLevel = new Map<string, number>();
  private readonly nPlainTrump: number;

  constructor(trumpSuit: TrumpSuit, trumpRank: string) {
    this.trumpSuit = trumpSuit;
    this.trumpRank = trumpRank;
    const plain = RANKS.filter((r) => r !== trumpRank);
    plain.forEach((r, i) => this.plainLevel.set(r, i));
    this.nPlainTrump = trumpSuit ? plain.length : 0;
    for (const code of ALL_CODES) {
      this.eff.set(code, this.computeIsTrump(code) ? TRUMP : (code[0] as EffSuit));
      this.lvl.set(code, this.computeLevel(code));
    }
  }

  private computeIsTrump(code: Card): boolean {
    if (isJoker(code)) return true;
    if (cardRank(code) === this.trumpRank) return true;
    return this.trumpSuit !== null && code[0] === this.trumpSuit;
  }

  private computeLevel(code: Card): number {
    if (!this.computeIsTrump(code)) return this.plainLevel.get(cardRank(code)!)!;
    const base = this.nPlainTrump;
    if (code === BJ) return this.trumpSuit ? base + 3 : base + 2;
    if (code === LJ) return this.trumpSuit ? base + 2 : base + 1;
    if (cardRank(code) === this.trumpRank) {
      if (this.trumpSuit === null) return base;
      return code[0] === this.trumpSuit ? base + 1 : base;
    }
    return this.plainLevel.get(cardRank(code)!)!;
  }

  isTrump(code: Card): boolean {
    return this.effSuit(code) === TRUMP;
  }

  effSuit(code: Card): EffSuit {
    const e = this.eff.get(code);
    if (e === undefined) throw new Error(`unknown card ${code}`);
    return e;
  }

  level(code: Card): number {
    const l = this.lvl.get(code);
    if (l === undefined) throw new Error(`unknown card ${code}`);
    return l;
  }

  /** Display order: plain suits S H C D, then the trump group. */
  compare(a: Card, b: Card): number {
    return (
      SUIT_KEY[this.effSuit(a)] - SUIT_KEY[this.effSuit(b)] ||
      this.level(a) - this.level(b) ||
      codeCmp(a, b)
    );
  }
}

const orderings = new Map<string, Ordering>();

/** A shared Ordering per (trump suit, trump rank); orderings are immutable. */
export function orderingFor(trumpSuit: TrumpSuit, trumpRank: string): Ordering {
  const key = `${trumpSuit ?? "-"}${trumpRank}`;
  let o = orderings.get(key);
  if (!o) {
    o = new Ordering(trumpSuit, trumpRank);
    orderings.set(key, o);
  }
  return o;
}

/** Sort order before trump is known. */
export function naturalCompare(a: Card, b: Card): number {
  const key = (c: Card): [number, number] => {
    if (c === BJ) return [4, 1];
    if (c === LJ) return [4, 0];
    return [{ S: 0, H: 1, C: 2, D: 3 }[c[0] as "S"]!, RANKS.indexOf(c.slice(1) as Rank)];
  };
  const ka = key(a);
  const kb = key(b);
  return ka[0] - kb[0] || ka[1] - kb[1];
}
