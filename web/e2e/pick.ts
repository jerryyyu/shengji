// A legal move for the seat the suite plays, from the state the page was sent:
// the offline engine's own rules, so the suite never waits on a refused play.
import { orderingFor, submultisets, suitCards, uniformSuit, validateFollow, type Card } from "../src/offline/engine";

interface HandCard { id: number; code: string }
interface Trump { suit: string | null; rank: string }

function idsFor(hand: HandCard[], codes: Card[]): number[] {
  const left = [...hand];
  return codes.map((code) => {
    const i = left.findIndex((c) => c.code === code);
    return left.splice(i, 1)[0].id;
  });
}

/** Card ids to play: the lowest single on a lead, else the first legal follow. */
export function pickPlay(hand: HandCard[], lead: Card[] | null, trump: Trump): number[] {
  const suit = trump.suit === "NT" || trump.suit === null ? null : (trump.suit as "S" | "H" | "D" | "C");
  const ordering = orderingFor(suit, trump.rank);
  const codes = hand.map((c) => c.code);
  if (!lead || lead.length === 0) return [hand[0].id];
  const n = lead.length;
  const eff = uniformSuit(lead, ordering);
  const inSuit = eff === null ? [] : suitCards(codes, eff, ordering);
  if (inSuit.length <= n) {
    const rest = [...codes];
    for (const c of inSuit) rest.splice(rest.indexOf(c), 1);
    return idsFor(hand, [...inSuit, ...rest.slice(0, n - inSuit.length)]);
  }
  for (const play of submultisets(inSuit, n)) {
    try {
      validateFollow(play, codes, lead, ordering);
      return idsFor(hand, play);
    } catch { /* not legal: next */ }
  }
  return idsFor(hand, inSuit.slice(0, n));
}
