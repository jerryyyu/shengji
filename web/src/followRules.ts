// What a follow needs, from what the follower can see: the lead and the
// declared trump. The lead's suit is the offline engine's (a trump-rank card
// or a joker leads trump), not the printed one.
import type { Trump } from "./protocol";
import { type Card, type EffSuit, orderingFor, trickWinner, uniformSuit } from "./offline/engine";
import { t } from "./i18n";

const SUIT_NAME: Record<Exclude<EffSuit, "T">, string> = { S: "♠", H: "♥", D: "♦", C: "♣" };

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
  if (eff === null) return t("table.followLead", { n });
  return t("table.followSuit", { n, suit: eff === "T" ? t("table.trumpWord") : SUIT_NAME[eff] });
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

/** The seat taking an unfinished trick so far, by the engine's own trick
 *  comparison (the fixture-held port of Round._resolve_trick); null before a
 *  second play, or when the plays or the trump cannot be read. */
export function winningSeat(plays: readonly { seat: number; cards: readonly string[] }[],
                            trump: Trump | null): number | null {
  if (plays.length < 2 || !trump) return null;
  const suit = trump.suit === "NT" || trump.suit === null ? null : trump.suit;
  if (suit !== null && !"SHDC".includes(suit)) return null;
  try {
    return trickWinner(plays.map((p) => ({ seat: p.seat, cards: [...p.cards] as Card[] })),
                       orderingFor(suit as "S" | "H" | "D" | "C" | null, trump.rank)).seat;
  } catch {
    return null;
  }
}
