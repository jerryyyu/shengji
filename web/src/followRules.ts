// What a follow needs, from what the follower can see: the lead and the
// declared trump. The lead's suit is the offline engine's (a trump-rank card
// or a joker leads trump), not the printed one.
import type { Trump } from "./protocol";
import { type Card, type EffSuit, orderingFor, uniformSuit } from "./offline/engine";

const SUIT_NAME: Record<EffSuit, string> = { S: "♠", H: "♥", D: "♦", C: "♣", T: "trump" };

/** The lead's effective suit, or null when it cannot be read. */
export function leadSuit(lead: readonly Card[], trump: Trump | null): EffSuit | null {
  if (!trump || lead.length === 0) return null;
  const suit = trump.suit === "NT" || trump.suit === null ? null : trump.suit;
  if (suit !== null && !"SHDC".includes(suit)) return null;
  try {
    return uniformSuit(lead, orderingFor(suit as "S" | "H" | "D" | "C" | null, trump.rank));
  } catch {
    return null;
  }
}

/** One line saying what a follow needs: "Follow ♠: play 3 cards". */
export function followHint(lead: readonly Card[], trump: Trump | null): string {
  const n = lead.length;
  const eff = leadSuit(lead, trump);
  const count = `play ${n} ${n === 1 ? "card" : "cards"}`;
  return eff === null ? `Follow the lead: ${count}` : `Follow ${SUIT_NAME[eff]}: ${count}`;
}

/** Whether the chosen cards carry as many of the led suit as a follow must:
 *  all of them when the hand holds enough of the suit, else every one it
 *  holds. Every legal follow passes, so this never blocks one; it is not
 *  sufficient, since pair, tractor and throw obligations stay the server's
 *  call. null, which never blocks, when the lead's suit or the trump cannot
 *  be read. */
export function followsSuit(hand: readonly { id: number; code: string }[], chosen: readonly number[],
                            lead: readonly Card[], trump: Trump | null): boolean | null {
  const eff = leadSuit(lead, trump);
  if (eff === null || trump === null) return null;
  const suit = trump.suit === "NT" || trump.suit === null ? null : trump.suit;
  let ordering;
  try {
    ordering = orderingFor(suit as "S" | "H" | "D" | "C" | null, trump.rank);
  } catch {
    return null;
  }
  const picked = new Set(chosen);
  let held = 0;
  let played = 0;
  for (const c of hand) {
    let cardSuit: EffSuit;
    try {
      cardSuit = ordering.effSuit(c.code);
    } catch {
      return null;
    }
    if (cardSuit !== eff) continue;
    held += 1;
    if (picked.has(c.id)) played += 1;
  }
  return played >= Math.min(lead.length, held);
}
