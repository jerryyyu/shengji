// UI flow telemetry: a few allow-listed events about how people move through
// the app, batched to the server as `client_event`. Nothing here carries a
// name, chat, room code or card: only enum ids, buckets and bounded counts,
// and the server drops anything else. Practice games (no server) send no
// events: while the page is offline or in a nearby game nothing is
// collected, and what was buffered on either side of a switch is dropped
// there; only the counts of offlineDigest.ts reach the next online socket.
// No call here ever throws into the UI.
import { useEffect } from "react";
import { conn } from "./ws";
import { NEARBY_SESSION, OFFLINE, subscribeOffline } from "./offlineMode";
import { subscribeLink, type DropCause } from "./link";
import { setReviewReporter, type Trigger as ReviewTrigger } from "./reviewPrompt";
import { isZh } from "./i18n";
import { DeviceStamps, playedBefore, type Lang } from "./telemetryStamps";

export type Screen =
  | "play" | "howto" | "name_sheet" | "duo_sheet" | "room" | "waiting_table"
  | "offer" | "table" | "round_end" | "leaderboard" | "me" | "games" | "game";

export type TapId =
  | "play" | "play_bots" | "create_room" | "duo" | "join_code" | "start_with_bots"
  | "leave_queue" | "wait_people_on" | "wait_people_off" | "table_start"
  | "offer_join" | "offer_wait" | "offer_chip" | "next_round" | "round_end_leave"
  | "menu_leave" | "chip_leave" | "leave_confirm" | "leave_keep" | "howto_open"
  | "signin_open" | "coach_on" | "coach_off" | "invite_share" | "copy_code" | "app_store_badge";

/** Where the identity sheet (the name, and Sign in) was opened. */
export type SigninFrom =
  | "play_line" | "chip" | "me_row" | "me_signin" | "leaderboard_row" | "round_end" | "lapsed" | "report"
  | "moved";

/** A provider sign-in: its button tapped, the account confirmed, a refusal,
 *  or the provider's sheet dismissed. */
export type SigninStep = "provider_tap" | "done" | "error" | "closed";
export type Provider = "google" | "apple";

/** The iOS app's own account: made, signed in again from the Keychain, the
 *  device left a guest, an identity linked onto it, the "Switch to …?"
 *  confirm shown, or the device's account given way to the identity's. */
export type DeviceStep = "created" | "restored" | "fell_back_guest" | "linked" | "conflict_shown" | "switched";

export type Platform = "ios_app" | "pwa" | "web";

export type LeadKind = "single" | "pair" | "tractor" | "throw";

/** The client's view of a round's table: a ranked (matched) one, a casual
 *  queue table, a friends' table (a code, a Duo, a saved game's Continue),
 *  a tutorial, or the device's own server. Offline and nearby rounds are
 *  never sent as rounds, only counted in the offline digest. */
export type RoundMode = "ranked" | "casual" | "friend" | "tutorial" | "offline" | "nearby";
/** What ended a round as the page saw it: its round end, your Leave, or
 *  the page closing mid-round (said on the next load). */
export type RoundBy = "end" | "left" | "closed";

export interface OfflineCounts {
  rounds_started: number;
  rounds_finished: number;
  nearby_rounds: number;
}

/** app_open's time to the first open socket is capped here. */
export const MAX_SOCKET_MS = 120_000;
/** round_start's count of rounds since the page loaded stops here. */
export const MAX_ROUNDS_PER_LOAD = 50;

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
  | { e: "tap"; t: number; id: TapId; from?: SigninFrom }
  | { e: "signin"; t: number; step: SigninStep; provider?: Provider }
  | { e: "device_account"; t: number; step: DeviceStep; first_round_before: boolean }
  | { e: "app_open"; t: number; cold: boolean; ms_to_socket?: number }
  | { e: "round_start"; t: number; mode: RoundMode; bots: number; nth_round_this_load: number }
  | { e: "round_finish"; t: number; mode: RoundMode; by: RoundBy; won?: boolean; tricks_played?: number }
  | ({ e: "offline_digest"; t: number } & OfflineCounts)
  | { e: "howto_step"; t: number; step: number; done: boolean }
  | { e: "notice"; t: number; code: string; where: Screen | "toast" | "other"; cause?: DropCause; ms?: number }
  | { e: "review_prompt"; t: number; trigger: ReviewTrigger; version: string };

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

/** ios_app (the Capacitor shell on iOS), pwa (the site opened from a
 *  home-screen icon) or web (a browser tab). */
export function platform(): Platform {
  try {
    const cap = (window as unknown as { Capacitor?: { isNativePlatform?: () => boolean; getPlatform?: () => string } }).Capacitor;
    if (cap?.isNativePlatform?.() === true && cap.getPlatform?.() === "ios") return "ios_app";
    const standalone = window.matchMedia?.("(display-mode: standalone)")?.matches === true
      || (navigator as Navigator & { standalone?: boolean }).standalone === true;
    return standalone ? "pwa" : "web";
  } catch {
    return "web";
  }
}

function lang(): Lang {
  try {
    return isZh() ? "zh" : "en";
  } catch {
    return "en";
  }
}

const clamp = (n: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, Math.round(n)));

export class Telemetry {
  private buf: Event[] = [];
  private timer: ReturnType<typeof setTimeout> | null = null;
  private screen: Screen | null = null;
  private screenAt = 0;
  private seen: boolean | null = null;
  private readonly send: Send;
  private readonly on: () => boolean;
  /** The device's first-seen and session buckets, stamped on each batch. */
  readonly stamps: DeviceStamps;

  /** `enabled` is read at each event and flush, so a page whose mode
   *  changes collects only while it is on. */
  constructor(send: Send, enabled: boolean | (() => boolean), stamps: DeviceStamps = new DeviceStamps()) {
    this.send = send;
    this.on = typeof enabled === "function" ? enabled : () => enabled;
    this.stamps = stamps;
  }

  private get enabled(): boolean {
    return this.on();
  }

  /** Whether events are collected now (online, no nearby game). */
  enabledNow(): boolean {
    try {
      return this.on();
    } catch {
      return false;
    }
  }

  /** Whether this is the device's first visit, read once collection is on. */
  private get firstVisit(): boolean {
    this.seen ??= readFirstVisit();
    return this.seen;
  }

  /** Drop everything buffered and the screen timing: the events belong to
   *  the mode that is ending, and the next screen starts a fresh sequence. */
  reset(): void {
    if (this.timer !== null) clearTimeout(this.timer);
    this.timer = null;
    this.buf = [];
    this.screen = null;
    this.screenAt = 0;
  }

  /** The identity behind the socket is changing: what was buffered goes on
   *  the old socket if it takes it, and whatever it refuses is dropped with
   *  the screen timing, so nothing of the identity before is sent under the
   *  next one's sid and account kind. */
  handover(): void {
    this.flush();
    this.reset();
  }

  private push(ev: Event): void {
    if (!this.enabled) return;
    try {
      this.stamps.touch();
      this.buf.push(ev);
      if (this.buf.length > MAX_BUFFER) this.buf.splice(0, this.buf.length - MAX_BUFFER);
      if (this.buf.length >= FLUSH_AT) this.flush();
      else if (this.timer === null) this.timer = setTimeout(() => this.flush(), FLUSH_MS);
    } catch {
      /* telemetry never breaks the UI */
    }
  }

  /** Send everything buffered, in batches under MAX_BYTES; what the socket
   *  cannot take now waits for the next flush. `last` sends what an online
   *  page buffered as it turns offline, on the socket that is still its own. */
  flush(last = false): void {
    if (this.timer !== null) {
      clearTimeout(this.timer);
      this.timer = null;
    }
    if (!this.enabled && !last) return;
    try {
      while (this.buf.length > 0) {
        const batch: Event[] = [];
        const buckets = this.bucketStamps();
        const base = { type: "client_event", v: 1, form: formFactor(), platform: platform(),
                       first_visit: this.firstVisit, ...buckets };
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

  /** The batch's bucket stamps; a bucket the device cannot tell is left out. */
  private bucketStamps(): { days_since_first?: string; session_n?: string; lang: Lang } {
    const out: { days_since_first?: string; session_n?: string; lang: Lang } = { lang: lang() };
    try {
      const days = this.stamps.days();
      const session = this.stamps.sessionN();
      if (days !== null) out.days_since_first = days;
      if (session !== null) out.session_n = session;
    } catch {
      /* the stamps are best effort */
    }
    return out;
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

  /** The identity sheet opened, and from where. */
  signinOpen(from: SigninFrom): void {
    this.push({ e: "tap", t: now(), id: "signin_open", from });
  }

  /** A step of a provider sign-in. */
  signin(step: SigninStep, provider?: Provider): void {
    this.push(provider ? { e: "signin", t: now(), step, provider } : { e: "signin", t: now(), step });
  }

  /** A step of the iOS app's own account, and whether this device had
   *  started a round before it. */
  deviceAccount(step: DeviceStep): void {
    this.push({ e: "device_account", t: now(), step, first_round_before: playedBefore() });
  }

  /** The page loaded (`cold`) with its first socket open `ms` after the
   *  navigation began, or a page already loaded came back into view after
   *  a session's idle gap. */
  appOpen(cold: boolean, ms?: number): void {
    this.push(ms === undefined ? { e: "app_open", t: now(), cold }
      : { e: "app_open", t: now(), cold, ms_to_socket: clamp(ms, 0, MAX_SOCKET_MS) });
  }

  roundStart(mode: RoundMode, bots: number, nth: number): void {
    this.push({ e: "round_start", t: now(), mode, bots: clamp(bots, 0, 3),
                nth_round_this_load: clamp(nth, 1, MAX_ROUNDS_PER_LOAD) });
  }

  /** A round ended as the page saw it; `won` only at its round end, and
   *  no trick count when the round's count is unknown. */
  roundFinish(mode: RoundMode, by: RoundBy, tricks?: number, won?: boolean): void {
    const ev: Event = { e: "round_finish", t: now(), mode, by };
    if (tricks !== undefined) ev.tricks_played = clamp(tricks, 0, 25);
    if (won !== undefined && by === "end") ev.won = won;
    this.push(ev);
  }

  /** The rounds played on the device since the last digest, in a batch of
   *  its own on the socket now: true only when the socket took it. Never
   *  buffered, so counts kept for a later try are never sent twice. */
  sendOfflineDigest(c: OfflineCounts): boolean {
    if (!this.enabledNow()) return false;
    try {
      this.stamps.touch();
      const ev: Event = { e: "offline_digest", t: now(), rounds_started: clamp(c.rounds_started, 0, 99),
                          rounds_finished: clamp(c.rounds_finished, 0, 99), nearby_rounds: clamp(c.nearby_rounds, 0, 99) };
      return this.send({ type: "client_event", v: 1, form: formFactor(), platform: platform(),
                         first_visit: this.firstVisit, ...this.bucketStamps(), events: [ev] }) === true;
    } catch {
      return false;
    }
  }

  /** A How to play step in view, or its last step's Start playing (`done`). */
  howtoStep(step: number, done: boolean): void {
    this.push({ e: "howto_step", t: now(), step: clamp(step, 1, 20), done });
  }

  notice(code: string, where: Screen | "toast" | "other" = this.screen ?? "other"): void {
    this.push({ e: "notice", t: now(), code, where });
  }

  /** The page lost an open socket, and why. */
  disconnected(cause: DropCause): void {
    this.push({ e: "notice", t: now(), code: "disconnected", where: this.screen ?? "other", cause });
  }

  /** A socket opened again, `ms` after the last one was lost. */
  reconnected(ms: number): void {
    this.push({ e: "notice", t: now(), code: "reconnected", where: this.screen ?? "other",
                ms: Math.max(0, Math.round(ms)) });
  }

  /** The iOS app asked for Apple's rating sheet (reviewPrompt.ts): which
   *  bar it crossed, and the app version asked for. */
  reviewPrompt(trigger: ReviewTrigger, version: string): void {
    this.push({ e: "review_prompt", t: now(), trigger, version });
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

export const telemetry = new Telemetry(liveSend, () => !OFFLINE && !NEARBY_SESSION);

// A rating ask goes out while the page collects; one made offline waits in
// the native store for the next online page.
setReviewReporter((trigger, version) => {
  if (OFFLINE || NEARBY_SESSION) return false;
  telemetry.reviewPrompt(trigger, version);
  return true;
});

// The socket manager's drops and recoveries; they wait in the buffer while
// the socket is down and go with the next flush.
subscribeLink((ev) => {
  if (ev.kind === "down") telemetry.disconnected(ev.cause);
  else telemetry.reconnected(ev.ms);
});

// At a switch between the game server and the on-device one, what the online
// page buffered goes on its socket first, then nothing of either side is kept.
subscribeOffline(() => {
  if (OFFLINE || NEARBY_SESSION) telemetry.flush(true);
  telemetry.reset();
});

/** What runs just before the page goes, ahead of the last flush (the
 *  round tracker's mid-round close). */
const beforeHide = new Set<() => void>();

export function onPageHide(fn: () => void): () => void {
  beforeHide.add(fn);
  return () => { beforeHide.delete(fn); };
}

if (typeof window !== "undefined") {
  try {
    window.addEventListener("pagehide", () => {
      for (const fn of [...beforeHide]) {
        try { fn(); } catch { /* telemetry never breaks the page */ }
      }
      telemetry.flush();
    });
  } catch {
    /* no window events */
  }
}

/** The milliseconds since this page's navigation began. */
function sinceNavigation(): number {
  try {
    return performance.now();
  } catch {
    return 0;
  }
}

// app_open: once per page load, when its first socket opens (an offline
// page has none to send it on), and again when a loaded page comes back
// into view after a session's idle gap (the app brought back from the
// background with no reload).
let opened = false;
try {
  (conn as { subscribeStatus?: (fn: (s: string) => void) => () => void }).subscribeStatus?.((s) => {
    if (opened || s !== "open" || !telemetry.enabledNow()) return;
    opened = true;
    telemetry.appOpen(true, sinceNavigation());
  });
} catch {
  /* a socket stand-in without status */
}
if (typeof document !== "undefined") {
  try {
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState !== "visible" || !opened || !telemetry.enabledNow()) return;
      if (telemetry.stamps.touch()) telemetry.appOpen(false);
    });
  } catch {
    /* no document events */
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
