// UI flow telemetry: a few allow-listed events about how people move through
// the app, batched to the server as `client_event`. Nothing here carries a
// name, chat, room code or card: only enum ids and bounded counts, and the
// server drops anything else. Practice games (no server) send nothing, and no
// call here ever throws into the UI.
import { useEffect } from "react";
import { conn } from "./ws";
import { OFFLINE } from "./offlineMode";

export type Screen =
  | "play" | "howto" | "name_sheet" | "duo_sheet" | "room" | "waiting_table"
  | "offer" | "table" | "round_end" | "leaderboard" | "me" | "games" | "game";

export type TapId =
  | "play" | "play_bots" | "create_room" | "duo" | "join_code" | "start_with_bots"
  | "leave_queue" | "wait_people_on" | "wait_people_off" | "table_start"
  | "offer_join" | "offer_wait" | "offer_chip" | "next_round" | "round_end_leave"
  | "menu_leave" | "chip_leave" | "leave_confirm" | "leave_keep" | "howto_open"
  | "signin_open" | "coach_on" | "coach_off" | "invite_share" | "copy_code";

export type LeadKind = "single" | "pair" | "tractor" | "throw";

export interface TurnDone {
  phase: "play" | "bury";
  lead?: LeadKind;
  need: number;
  ms_to_first_tap?: number;
  ms_total: number;
  sel_changes: number;
  disabled_play_taps: number;
  refused: number;
  coach: boolean;
  nth_turn: number;
  by: "you" | "timer" | "bot";
}

type Event =
  | { e: "screen"; t: number; name: Screen; prev?: Screen; ms_on_prev?: number }
  | ({ e: "turn_done"; t: number } & TurnDone)
  | { e: "tap"; t: number; id: TapId }
  | { e: "notice"; t: number; code: string; where: Screen | "toast" | "other" };

export const FLUSH_MS = 10_000;
export const FLUSH_AT = 20;
/** The server drops a message over 2 kB whole; batches stay under this. */
export const MAX_BYTES = 1900;
/** Events kept while the socket is down; the oldest go first. */
const MAX_BUFFER = 100;
const SEEN_KEY = "shengji.telemetry.seen";

type Send = (msg: unknown) => boolean;

function now(): number {
  try {
    return Math.max(0, Math.round(performance.now()));
  } catch {
    return 0;
  }
}

function readFirstVisit(): boolean {
  try {
    const first = localStorage.getItem(SEEN_KEY) === null;
    if (first) localStorage.setItem(SEEN_KEY, "1");
    return first;
  } catch {
    return false;
  }
}

/** phone (portrait), phone-land (a phone on its side) or wide. */
export function formFactor(): "phone" | "phone-land" | "wide" {
  try {
    const w = window.innerWidth, h = window.innerHeight;
    if (w >= 700 && h >= 500) return "wide";
    return w > h ? "phone-land" : "phone";
  } catch {
    return "wide";
  }
}

export class Telemetry {
  private buf: Event[] = [];
  private timer: ReturnType<typeof setTimeout> | null = null;
  private screen: Screen | null = null;
  private screenAt = 0;
  private readonly firstVisit: boolean;
  private readonly send: Send;
  private readonly enabled: boolean;

  constructor(send: Send, enabled: boolean) {
    this.send = send;
    this.enabled = enabled;
    this.firstVisit = enabled ? readFirstVisit() : false;
  }

  private push(ev: Event): void {
    if (!this.enabled) return;
    try {
      this.buf.push(ev);
      if (this.buf.length > MAX_BUFFER) this.buf.splice(0, this.buf.length - MAX_BUFFER);
      if (this.buf.length >= FLUSH_AT) this.flush();
      else if (this.timer === null) this.timer = setTimeout(() => this.flush(), FLUSH_MS);
    } catch {
      /* telemetry never breaks the UI */
    }
  }

  /** Send everything buffered, in batches under MAX_BYTES; what the socket
   *  cannot take now waits for the next flush. */
  flush(): void {
    if (this.timer !== null) {
      clearTimeout(this.timer);
      this.timer = null;
    }
    if (!this.enabled) return;
    try {
      while (this.buf.length > 0) {
        const batch: Event[] = [];
        const base = { type: "client_event", v: 1, form: formFactor(), first_visit: this.firstVisit };
        let size = JSON.stringify({ ...base, events: [] }).length;
        while (batch.length < FLUSH_AT && batch.length < this.buf.length) {
          const add = JSON.stringify(this.buf[batch.length]).length + 1;
          if (batch.length > 0 && size + add > MAX_BYTES) break;
          batch.push(this.buf[batch.length]);
          size += add;
        }
        if (!this.send({ ...base, events: batch })) break;
        this.buf.splice(0, batch.length);
      }
    } catch {
      /* the buffer stays for the next try */
    }
  }

  /** The screen in view changed; the same screen again is no event. */
  screenView(name: Screen): void {
    if (name === this.screen) return;
    const t = now();
    const prev = this.screen;
    this.screen = name;
    const ms = t - this.screenAt;
    this.screenAt = t;
    this.push(prev === null
      ? { e: "screen", t, name }
      : { e: "screen", t, name, prev, ms_on_prev: ms });
  }

  current(): Screen | null {
    return this.screen;
  }

  tap(id: TapId): void {
    this.push({ e: "tap", t: now(), id });
  }

  notice(code: string, where: Screen | "toast" | "other" = this.screen ?? "other"): void {
    this.push({ e: "notice", t: now(), code, where });
  }

  turnDone(turn: TurnDone): void {
    this.push({ e: "turn_done", t: now(), ...turn, nth_turn: Math.min(30, Math.max(1, turn.nth_turn)) });
  }

  /** Events waiting to go (tests). */
  pending(): readonly Event[] {
    return this.buf;
  }
}

function liveSend(msg: unknown): boolean {
  // the message is outside the game protocol's ClientMsg union on purpose:
  // nothing in the game reads it
  return conn.send(msg as Parameters<typeof conn.send>[0]);
}

export const telemetry = new Telemetry(liveSend, !OFFLINE);

if (typeof window !== "undefined" && !OFFLINE) {
  try {
    window.addEventListener("pagehide", () => telemetry.flush());
  } catch {
    /* no window events */
  }
}

/** This component is the screen while it is mounted; when it unmounts and
 *  was still the screen, the one before it is again (an overlay closing). */
export function useScreen(name: Screen, active = true): void {
  useEffect(() => {
    if (!active) return;
    const before = telemetry.current();
    telemetry.screenView(name);
    return () => {
      if (telemetry.current() === name && before !== null && before !== name) telemetry.screenView(before);
    };
  }, [name, active]);
}

let turnsThisLoad = 0;

/** 1 for your first turn since the page loaded, then 2, 3, … */
export function nextTurnNumber(): number {
  turnsThisLoad += 1;
  return Math.min(30, turnsThisLoad);
}

/** The shape of a lead, from its card codes. A pair is two equal cards; an
 *  even run of pairs reads as a tractor, though the client cannot tell a
 *  tractor from a throw of separate pairs; anything else is a throw. */
export function leadKind(cards: readonly string[]): LeadKind {
  if (cards.length === 1) return "single";
  const counts = new Map<string, number>();
  for (const c of cards) counts.set(c, (counts.get(c) ?? 0) + 1);
  const allPairs = [...counts.values()].every((n) => n === 2);
  if (cards.length === 2 && allPairs) return "pair";
  if (cards.length >= 4 && allPairs) return "tractor";
  return "throw";
}

/** One of your turns as it happens, folded into a `turn_done` at its end. */
export class TurnClock {
  private started = 0;
  private firstTap: number | null = null;
  selChanges = 0;
  disabledTaps = 0;
  refused = 0;

  readonly phase: "play" | "bury";
  readonly need: number;
  readonly lead: LeadKind | undefined;
  readonly coach: boolean;
  readonly nth: number;

  constructor(phase: "play" | "bury", need: number, lead: LeadKind | undefined,
              coach: boolean, nth: number) {
    this.phase = phase;
    this.need = need;
    this.lead = lead;
    this.coach = coach;
    this.nth = nth;
    this.started = now();
  }

  select(): void {
    this.selChanges += 1;
    if (this.firstTap === null) this.firstTap = now() - this.started;
  }

  finish(by: "you" | "timer" | "bot"): TurnDone {
    const turn: TurnDone = {
      phase: this.phase, need: this.need, ms_total: now() - this.started,
      sel_changes: this.selChanges, disabled_play_taps: this.disabledTaps,
      refused: this.refused, coach: this.coach, nth_turn: this.nth, by,
    };
    if (this.lead !== undefined) turn.lead = this.lead;
    if (this.firstTap !== null) turn.ms_to_first_tap = this.firstTap;
    return turn;
  }
}
