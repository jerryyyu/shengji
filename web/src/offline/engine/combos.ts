// Decomposition of same-suit plays into singles, pairs and tractors: a port
// of server/shengji/engine/combos.py. Iteration orders follow Python's
// (Counter = first-occurrence order, stable sorts) so that the physical cards
// chosen for tied levels match, not only the shapes.
import { type Card, type Ordering, sortedCodes } from "./cards";

export type ComponentKind = "single" | "pair" | "tractor";

export interface Component {
  kind: ComponentKind;
  cards: Card[];
  /** Highest level in the component. */
  top: number;
  /** 0 for a single, 1 for a pair, k for a tractor of k pairs. */
  pairLen: number;
}

/** Runs of pair lengths (descending) and the number of singles. */
export type Shape = [runs: number[], singles: number];

export class Decomposition {
  readonly components: Component[];
  constructor(components: Component[]) {
    this.components = components;
  }
  get nPairs(): number {
    return this.components.reduce((s, c) => s + c.pairLen, 0);
  }
  get size(): number {
    return this.components.reduce((s, c) => s + c.cards.length, 0);
  }
  shape(): Shape {
    const runs = this.components
      .filter((c) => c.pairLen)
      .map((c) => c.pairLen)
      .sort((a, b) => b - a);
    const singles = this.components.filter((c) => c.pairLen === 0).length;
    return [runs, singles];
  }
  /** Top of the largest component: by pair-run length, then level. */
  topLevel(): number {
    let best = this.components[0];
    for (const c of this.components) {
      if (c.pairLen > best.pairLen || (c.pairLen === best.pairLen && c.top > best.top)) best = c;
    }
    return best.top;
  }
  maxPairRun(): number {
    return this.components.reduce((m, c) => Math.max(m, c.pairLen), 0);
  }
}

/** Python `Counter(cards)`: counts in first-occurrence order. */
export function counter(cards: readonly Card[]): Map<Card, number> {
  const m = new Map<Card, number>();
  for (const c of cards) m.set(c, (m.get(c) ?? 0) + 1);
  return m;
}

function byComponentOrder(a: Component, b: Component): number {
  return b.pairLen - a.pairLen || b.top - a.top;
}

function numericKeys(m: Map<number, unknown>): number[] {
  return [...m.keys()].sort((a, b) => a - b);
}

/** Split `cards` (one effective suit) into tractors, pairs and singles. */
export function decompose(input: readonly Card[], ordering: Ordering): Decomposition {
  const cards = sortedCodes(input);
  const cnt = counter(cards);
  const byLevel = new Map<number, Card[]>();
  const singles: Card[] = [];
  for (const [c, k] of cnt) {
    if (k >= 2) {
      const lv = ordering.level(c);
      const list = byLevel.get(lv);
      if (list) list.push(c);
      else byLevel.set(lv, [c]);
    } else if (k === 1) singles.push(c);
  }
  const comps: Component[] = [];
  const remaining = byLevel;
  while (remaining.size) {
    const levels = numericKeys(remaining);
    let best: number[] = [];
    let i = 0;
    while (i < levels.length) {
      let j = i;
      while (j + 1 < levels.length && levels[j + 1] === levels[j] + 1) j += 1;
      if (j - i + 1 > best.length) best = levels.slice(i, j + 1);
      i = j + 1;
    }
    const chosen: Card[] = [];
    for (const lv of best) {
      const list = remaining.get(lv)!;
      chosen.push(list.shift()!);
      if (!list.length) remaining.delete(lv);
    }
    if (chosen.length >= 2) {
      comps.push({
        kind: "tractor",
        cards: chosen.flatMap((c) => [c, c]),
        top: best[best.length - 1],
        pairLen: chosen.length,
      });
    } else {
      comps.push({ kind: "pair", cards: [chosen[0], chosen[0]], top: best[0], pairLen: 1 });
    }
  }
  for (const c of singles) comps.push({ kind: "single", cards: [c], top: ordering.level(c), pairLen: 0 });
  comps.sort(byComponentOrder);
  return new Decomposition(comps);
}

/**
 * Decompose `cards` (one effective suit) to match `shape`, or null. Unlike
 * the greedy `decompose` this searches: runs may split longer tractors and
 * spare pairs may break into singles.
 */
export function decomposeMatching(cards: readonly Card[], ordering: Ordering, shape: Shape): Decomposition | null {
  const [runsNeeded, nSingles] = shape;
  if (cards.length !== 2 * runsNeeded.reduce((s, k) => s + k, 0) + nSingles) return null;
  const cnt = counter(cards);
  const byLevel = new Map<number, Card[]>();
  for (const [c, k] of cnt) {
    if (k >= 2) {
      const lv = ordering.level(c);
      const list = byLevel.get(lv);
      if (list) list.push(c);
      else byLevel.set(lv, [c]);
    }
  }
  const backtrack = (i: number, avail: Map<number, Card[]>): Component[] | null => {
    if (i === runsNeeded.length) return [];
    const k = runsNeeded[i];
    for (const start of numericKeys(avail)) {
      let ok = true;
      for (let d = 0; d < k; d++) if (!avail.has(start + d)) ok = false;
      if (!ok) continue;
      const nxt = new Map<number, Card[]>();
      for (const [lv, cs] of avail) nxt.set(lv, [...cs]);
      const chosen: Card[] = [];
      for (let d = 0; d < k; d++) {
        const lv = start + d;
        const list = nxt.get(lv)!;
        chosen.push(list.pop()!);
        if (!list.length) nxt.delete(lv);
      }
      const rest = backtrack(i + 1, nxt);
      if (rest !== null) {
        const comp: Component = {
          kind: k >= 2 ? "tractor" : "pair",
          cards: chosen.flatMap((c) => [c, c]),
          top: start + k - 1,
          pairLen: k,
        };
        return [comp, ...rest];
      }
    }
    return null;
  };
  const runComps = backtrack(0, byLevel);
  if (runComps === null) return null;
  const used = counter(runComps.flatMap((c) => c.cards));
  const singles: Component[] = [];
  // (cnt - used).elements(): first-occurrence order, positive remainders.
  for (const [c, k] of cnt) {
    const left = k - (used.get(c) ?? 0);
    for (let t = 0; t < left; t++) singles.push({ kind: "single", cards: [c], top: ordering.level(c), pairLen: 0 });
  }
  const comps = [...runComps, ...singles].sort(byComponentOrder);
  return new Decomposition(comps);
}

export function pairCount(cards: readonly Card[]): number {
  let n = 0;
  for (const k of counter(cards).values()) n += Math.floor(k / 2);
  return n;
}

/**
 * Every k-pair tractor in `cards` (one suit), lowest first. A level holding
 * several pair codes (off-suit trump-rank pairs) contributes each of them:
 * the Cartesian product over the window, codes sorted within a level.
 */
export function findTractorRuns(cards: readonly Card[], ordering: Ordering, k: number): Card[][] {
  const byLevel = new Map<number, Card[]>();
  for (const [c, n] of counter(cards)) {
    if (n >= 2) {
      const lv = ordering.level(c);
      const list = byLevel.get(lv);
      if (list) list.push(c);
      else byLevel.set(lv, [c]);
    }
  }
  for (const codes of byLevel.values()) codes.sort();
  const out: Card[][] = [];
  for (const start of numericKeys(byLevel)) {
    const window: Card[][] = [];
    let ok = true;
    for (let d = 0; d < k; d++) {
      const codes = byLevel.get(start + d);
      if (!codes) {
        ok = false;
        break;
      }
      window.push(codes);
    }
    if (!ok) continue;
    // itertools.product order: the last position varies fastest.
    let combos: Card[][] = [[]];
    for (const codes of window) {
      const next: Card[][] = [];
      for (const prefix of combos) for (const c of codes) next.push([...prefix, c]);
      combos = next;
    }
    for (const combo of combos) out.push(combo.flatMap((c) => [c, c]));
  }
  return out;
}

export function hasTractor(cards: readonly Card[], ordering: Ordering, k: number): boolean {
  return findTractorRuns(cards, ordering, k).length > 0;
}
