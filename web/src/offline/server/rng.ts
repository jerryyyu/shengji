// The offline deal's shuffle: mulberry32 driving a Fisher-Yates pass. The
// parity fixtures (server/scripts/gen_offline_server_fixtures.py) hand the
// Python engine this exact shuffle, so a seed deals the same decks in both.
import { type Card, makeDeck } from "../engine/cards";

export class DeckRng {
  private state: number;

  constructor(seed: number) {
    this.state = seed >>> 0;
  }

  nextU32(): number {
    this.state = (this.state + 0x6d2b79f5) >>> 0;
    let t = this.state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return (t ^ (t >>> 14)) >>> 0;
  }

  shuffle<T>(items: T[]): void {
    for (let i = items.length - 1; i > 0; i--) {
      const j = this.nextU32() % (i + 1);
      [items[i], items[j]] = [items[j], items[i]];
    }
  }

  /** A fresh 108-card deck in this generator's next order. */
  deck(): Card[] {
    const deck = makeDeck();
    this.shuffle(deck);
    return deck;
  }
}

/** A seed from the platform's CSPRNG, for real offline games. */
export function randomSeed(): number {
  const buf = new Uint32Array(1);
  globalThis.crypto.getRandomValues(buf);
  return buf[0];
}
