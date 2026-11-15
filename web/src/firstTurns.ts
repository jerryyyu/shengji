// The coach for a newcomer's first turns: what to tap and how many, the cards
// that follow the lead, and a nudge when the turn sits idle. A newcomer is a
// browser that has made fewer than COACH_PLAYS plays of its own (a play the
// bot made for an absent player does not count), and, when signed in, an
// account that has sat in fewer than NEWCOMER_ROUNDS rounds anywhere, so a
// fresh store on a new device does not coach a player the account knows.
import { useEffect, useState } from "react";
import { type AuthState, useAuth } from "./auth";
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

/** Rounds an account has sat in after which it is no newcomer. */
export const NEWCOMER_ROUNDS = 3;

/** Whether the account side lets auto coach: a signed-in account only while
 *  it has sat in fewer than NEWCOMER_ROUNDS rounds; anyone else (a guest,
 *  sign-in off, unreachable or not yet answered) leaves it to the browser's
 *  count, as does a server that sends no round count. */
export function accountNewcomer(auth: Pick<AuthState, "status" | "user">): boolean {
  if (auth.status !== "in" || auth.user === null) return true;
  const rounds = auth.user.rounds_played;
  return rounds === null || rounds === undefined || rounds < NEWCOMER_ROUNDS;
}

/** The player's coach switch: "on" coaches every turn, "off" never, and
 *  absent ("auto") coaches a newcomer's first COACH_PLAYS plays. */
export const COACH_KEY = "shengji.coach";
export type CoachSetting = "auto" | "on" | "off";

// the switch for this session when the store refuses a write
let sessionSetting: CoachSetting | null = null;
const coachListeners = new Set<(s: CoachSetting) => void>();

export function coachSetting(): CoachSetting {
  if (sessionSetting !== null) return sessionSetting;
  try {
    const v = localStorage.getItem(COACH_KEY);
    return v === "on" || v === "off" ? v : "auto";
  } catch {
    return "auto";
  }
}

export function setCoachSetting(s: "on" | "off"): void {
  try {
    localStorage.setItem(COACH_KEY, s);
    sessionSetting = null;
  } catch {
    sessionSetting = s;
  }
  for (const fn of coachListeners) fn(s);
}

export function subscribeCoach(fn: (s: CoachSetting) => void): () => void {
  coachListeners.add(fn);
  return () => { coachListeners.delete(fn); };
}

/** Drops a switch held only in memory; storage keeps whatever it has. */
export function forgetSessionCoach(): void {
  sessionSetting = null;
}

/** Whether your turns get the coach, given the switch, your plays here and
 *  whether the account is new (`accountNewcomer`); "on" and "off" win. */
export function coachShows(setting: CoachSetting, plays: number, newAccount = true): boolean {
  return setting === "auto" ? newAccount && isNewcomer(plays) : setting === "on";
}

/** Whether the signed-in account (or the guest) still counts as new. */
export function useAccountNewcomer(): boolean {
  return accountNewcomer(useAuth());
}

/** The live coach switch, shared by the table and the menu row that flips it. */
export function useCoachSetting(): CoachSetting {
  const [setting, setLocal] = useState(coachSetting);
  useEffect(() => subscribeCoach(setLocal), []);
  return setting;
}

/** Whether the coach is on now, and a flip that pins it the other way. */
export function useCoach(): [boolean, () => void] {
  const on = coachShows(useCoachSetting(), playsMade(), useAccountNewcomer());
  return [on, () => setCoachSetting(on ? "off" : "on")];
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
