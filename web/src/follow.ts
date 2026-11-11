// Which hand cards cannot be played when following a single or a pair: a
// client-side mirror of the engine's follow rule (validate_follow in
// server/shengji/engine/legal.py) for those two leads only. The server stays
// the authority; anything this module is not certain about it leaves open,
// so a card is dimmed only when every legal play excludes it.

import type { HandCard, Trump } from "./protocol";

/** The engine's effective-suit tag for a trump card. */
export const TRUMP = "T";

/** A card's effective suit: jokers, every card of the trump rank and every
 *  card of the trump suit are trump; anything else is its printed suit. */
export function effectiveSuit(code: string, trump: Trump): string {
  if (code === "LJ" || code === "BJ") return TRUMP;
  if (code.slice(1) === trump.rank) return TRUMP;
  if (trump.suit !== null && trump.suit !== "NT" && code[0] === trump.suit) return TRUMP;
  return code[0];
}

/** Ids of the cards in `hand` that no legal follow to `lead` can contain.
 *
 *  - A single: holding the led effective suit, only those cards can go.
 *  - A pair (two identical cards): holding two or more of the led suit, only
 *    those can go; holding a pair in it as well, the play must be a pair
 *    (two identical cards), so a card without its twin cannot go either.
 *    With one card of the led suit that card must go, but the other is free,
 *    so nothing is dimmed.
 *  - Anything else (a throw, a tractor) is left to the server: empty set. */
export function unplayableIds(hand: HandCard[], lead: string[], trump: Trump | null): Set<number> {
  const blocked = new Set<number>();
  if (!trump || !trump.rank) return blocked;
  const isSingle = lead.length === 1;
  const isPair = lead.length === 2 && lead[0] === lead[1];
  if (!isSingle && !isPair) return blocked;
  const led = effectiveSuit(lead[0], trump);
  const inSuit = hand.filter((c) => effectiveSuit(c.code, trump) === led);
  if (inSuit.length < lead.length) return blocked;
  for (const c of hand) {
    if (effectiveSuit(c.code, trump) !== led) blocked.add(c.id);
  }
  if (isPair) {
    const count = new Map<string, number>();
    for (const c of inSuit) count.set(c.code, (count.get(c.code) ?? 0) + 1);
    const holdsPair = [...count.values()].some((n) => n >= 2);
    if (holdsPair) {
      for (const c of inSuit) if ((count.get(c.code) ?? 0) < 2) blocked.add(c.id);
    }
  }
  return blocked;
}

/** The lead you are following, or null when you lead or have already played. */
export function leadToFollow(trick: { plays: { seat: number; cards: string[] }[] } | null, you: number): string[] | null {
  if (!trick || trick.plays.length === 0) return null;
  if (trick.plays.some((p) => p.seat === you)) return null;
  return trick.plays[0].cards;
}
