// What a follower may play, from what they can see: their own hand, the lead
// and the declared trump. The rules themselves are the offline engine's port
// of the server's (validateFollow); this module only asks them questions.
import type { HandCard, Trump } from "./protocol";
import {
  type Card,
  type EffSuit,
  type Ordering,
  IllegalPlay,
  countSubmultisets,
  orderingFor,
  submultisets,
  suitCards,
  uniformSuit,
  validateFollow,
} from "./offline/engine";

/** Above this many candidate plays the check gives up on pairs and tractors
 *  and keeps only the suit rule, which can only leave a card undimmed. */
export const MAX_CANDIDATES = 3000;

const SUIT_NAME: Record<EffSuit, string> = { S: "♠", H: "♥", D: "♦", C: "♣", T: "trump" };

function ordering(trump: Trump | null): Ordering | null {
  if (!trump) return null;
  const suit = trump.suit === "NT" || trump.suit === null ? null : trump.suit;
  if (suit !== null && !"SHDC".includes(suit)) return null;
  try {
    return orderingFor(suit as "S" | "H" | "D" | "C" | null, trump.rank);
  } catch {
    return null;
  }
}

/** The lead's effective suit, or null when it cannot be read. */
export function leadSuit(lead: readonly Card[], trump: Trump | null): EffSuit | null {
  const o = ordering(trump);
  if (!o || lead.length === 0) return null;
  try {
    return uniformSuit(lead, o);
  } catch {
    return null;
  }
}

/** Ids of the hand cards that are part of at least one legal follow of
 *  `lead`, or null when every card is (void or short in the led suit, or the
 *  rules cannot be applied). Never leaves out a card some legal play uses. */
export function playableIds(hand: readonly HandCard[], lead: readonly Card[], trump: Trump | null): Set<number> | null {
  const o = ordering(trump);
  const eff = leadSuit(lead, trump);
  if (!o || eff === null) return null;
  const codes = hand.map((c) => c.code);
  let inSuit: Card[];
  try {
    inSuit = suitCards(codes, eff, o);
  } catch {
    return null;
  }
  // short of the led suit: all of it is owed and any card fills the rest
  if (inSuit.length < lead.length) return null;
  const ok = new Set<Card>();
  if (countSubmultisets(inSuit, lead.length) > MAX_CANDIDATES) {
    for (const c of inSuit) ok.add(c);
  } else {
    for (const play of submultisets(inSuit, lead.length)) {
      if (play.every((c) => ok.has(c))) continue;
      try {
        validateFollow(play, codes, lead, o);
        for (const c of play) ok.add(c);
      } catch (e) {
        if (!(e instanceof IllegalPlay)) return null;
      }
    }
  }
  return new Set(hand.filter((c) => ok.has(c.code)).map((c) => c.id));
}

/** One line saying what a follow needs: "Follow ♠: play 3 cards". */
export function followHint(lead: readonly Card[], trump: Trump | null): string {
  const n = lead.length;
  const eff = leadSuit(lead, trump);
  const count = `play ${n} ${n === 1 ? "card" : "cards"}`;
  return eff === null ? `Follow the lead: ${count}` : `Follow ${SUIT_NAME[eff]}: ${count}`;
}
