// The coach for a newcomer's first turns: what to tap and how many, the cards
// that follow the lead, and a nudge when the turn sits idle. A newcomer is a
// browser that has made fewer than COACH_PLAYS plays of its own; a play the
// bot made for an absent player does not count.
import type { HandCard, Trump } from "./protocol";
import { leadSuit } from "./followRules";
import { type EffSuit, orderingFor } from "./offline/engine";

export const PLAYS_KEY = "shengji.plays";
/** Plays of your own after which the coach no longer shows. */
export const COACH_PLAYS = 3;
/** An idle turn this long, nothing chosen, gets the nudge. */
export const NUDGE_MS = 20_000;

/** Plays this browser has made, or COACH_PLAYS when storage cannot be read,
 *  so a blocked store never coaches forever. */
export function playsMade(): number {
  try {
    const n = Number(localStorage.getItem(PLAYS_KEY) ?? "0");
    return Number.isFinite(n) && n >= 0 ? n : 0;
  } catch {
    return COACH_PLAYS;
  }
}

/** Counts one play of yours; stops counting once the coach is done. */
export function recordPlay(): number {
  const n = Math.min(playsMade() + 1, COACH_PLAYS);
  try {
    localStorage.setItem(PLAYS_KEY, String(n));
  } catch {
    // a blocked store already reads as done
  }
  return n;
}

export function isNewcomer(plays: number): boolean {
  return plays < COACH_PLAYS;
}

const SUIT_WORD: Record<EffSuit, string> = { S: "♠", H: "♥", D: "♦", C: "♣", T: "trump" };

function effOf(code: string, trump: Trump): EffSuit | null {
  const suit = trump.suit === "NT" || trump.suit === null ? null : trump.suit;
  if (suit !== null && !"SHDC".includes(suit)) return null;
  try {
    return orderingFor(suit as "S" | "H" | "D" | "C" | null, trump.rank).effSuit(code);
  } catch {
    return null;
  }
}

export interface Coach {
  text: string;
  /** Cards that follow the lead, when only they can make the play; null
   *  when any card may be part of it (a lead, or too few of the suit). */
  follow: Set<number> | null;
}

const cards = (n: number) => `${n} ${n === 1 ? "card" : "cards"}`;

/** What to tell a newcomer on their turn: leading, or following `lead`. */
export function coachFor(hand: readonly HandCard[], lead: readonly string[] | null, trump: Trump | null): Coach {
  if (!lead || lead.length === 0) {
    return { text: "Your lead: tap a card, then Play", follow: null };
  }
  const need = lead.length;
  const eff = leadSuit(lead, trump);
  if (eff === null || trump === null) {
    return { text: `Your turn: tap ${cards(need)}, then Play`, follow: null };
  }
  const word = SUIT_WORD[eff];
  const inSuit = hand.filter((c) => effOf(c.code, trump) === eff).map((c) => c.id);
  if (inSuit.length >= need) {
    return { text: `Your turn: tap ${need} ${word} ${need === 1 ? "card" : "cards"} (lit up), then Play`, follow: new Set(inSuit) };
  }
  if (inSuit.length > 0) {
    return {
      text: `Your turn: tap your ${inSuit.length} ${word} and ${cards(need - inSuit.length)} more, then Play`,
      follow: null,
    };
  }
  return { text: `No ${word} left: tap any ${cards(need)}, then Play`, follow: null };
}
