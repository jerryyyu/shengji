// The watcher's broadcast of one finished round, as a list of beats: the
// banker's bury, then each play preceded by its lift, then the round end.
// Pure: the screen steps through the beats on a timer at a steady rhythm,
// and back and forward move whole tricks inside the finished round only.
import type { HandCard } from "../protocol";
import type { Replay, ReplayFrame } from "../replay/reducer";
import { compareCards } from "../replay/cards";

export type BeatKind = "bury" | "buryLift" | "start" | "lift" | "play" | "end";

export interface Beat {
  kind: BeatKind;
  /** The replay frame the table shows. */
  frame: number;
  /** 0 before the first lead; a lift belongs to the trick its play opens or joins. */
  trickNo: number;
  /** The seat whose cards rise, and those cards (a lift, or the bury's eight). */
  liftSeat: number | null;
  lift: string[];
}

/** The pace at 1×: a lift, a play, a finished trick left on the felt. */
export const LIFT_MS = 650;
export const PLAY_MS = 600;
export const TRICK_HOLD_MS = 1300;
export const BURY_MS = 1100;

export const SPEEDS = [0.5, 1, 2] as const;
export type Speed = (typeof SPEEDS)[number];

const DEALT = 100;

/** The beats of a finished round. The bury beats exist only when the log
 *  names the eight buried cards and the kitty as dealt. */
export function beatsOf(replay: Replay, buried: string[] | null): Beat[] {
  const { frames, setup } = replay;
  const beats: Beat[] = [];
  const canBury = setup.banker !== null && setup.kitty !== null && buried !== null && buried.length > 0;
  if (canBury) {
    beats.push({ kind: "bury", frame: 0, trickNo: 0, liftSeat: null, lift: [] });
    beats.push({ kind: "buryLift", frame: 0, trickNo: 0, liftSeat: setup.banker, lift: buried! });
  }
  const start = frames.findIndex((f) => f.kind === "start");
  beats.push({ kind: "start", frame: start >= 0 ? start : 0, trickNo: 0, liftSeat: null, lift: [] });
  frames.forEach((f, i) => {
    if (f.kind === "play") {
      const play = f.trick?.plays[f.playNo];
      if (play) beats.push({ kind: "lift", frame: i - 1, trickNo: f.trickNo, liftSeat: play.seat, lift: play.cards });
      beats.push({ kind: "play", frame: i, trickNo: f.trickNo, liftSeat: null, lift: [] });
    } else if (f.kind === "end") {
      beats.push({ kind: "end", frame: i, trickNo: f.trickNo, liftSeat: null, lift: [] });
    }
  });
  return beats;
}

/** How long a beat stays before the next, at `speed`. */
export function beatMs(beat: Beat, frame: ReplayFrame, speed: Speed): number {
  const base = beat.kind === "lift" ? LIFT_MS
    : beat.kind === "play" ? (frame.winner !== null ? TRICK_HOLD_MS : PLAY_MS)
    : beat.kind === "bury" || beat.kind === "buryLift" ? BURY_MS
    : PLAY_MS;
  return Math.round(base / speed);
}

/** ⏮: the start of the trick in view, or of the one before when already
 *  there (the bury and the first lead count as one stretch). */
export function backTrick(beats: Beat[], at: number): number {
  const first = (n: number) => beats.findIndex((b) => b.trickNo === n);
  const n = beats[at]?.trickNo ?? 0;
  const here = first(n);
  if (here >= 0 && here < at) return here;
  return n <= 1 ? 0 : Math.max(0, first(n - 1));
}

/** ⏭: the first beat of the next trick, or the round end; never past it. */
export function forwardTrick(beats: Beat[], at: number): number {
  const n = beats[at]?.trickNo ?? 0;
  const next = beats.findIndex((b, i) => i > at && b.trickNo > n);
  if (next >= 0) return next;
  const end = beats.findIndex((b) => b.kind === "end");
  return end >= 0 ? end : beats.length - 1;
}

/** The hand a tab shows on a beat. During the bury the banker holds the
 *  dealt hand plus the kitty, in the game's order. */
export function handAt(replay: Replay, beat: Beat, seat: number): HandCard[] {
  const frame = replay.frames[beat.frame];
  const { setup } = replay;
  const hand = frame.hands[seat] ?? [];
  if ((beat.kind === "bury" || beat.kind === "buryLift") && seat === setup.banker && setup.kitty) {
    const order = (a: HandCard, b: HandCard) => compareCards(a.code, b.code, setup.trumpSuit, setup.trumpRank);
    return [...hand, ...setup.kitty.map((code, i) => ({ id: DEALT + i, code }))].sort(order);
  }
  return hand;
}

/** The ids in `hand` that rise on this beat for `seat`: the first copy of
 *  each lifted code, so a pair lifts both cards. */
export function liftedIds(hand: HandCard[], beat: Beat, seat: number): Set<number> {
  const out = new Set<number>();
  if (beat.liftSeat !== seat) return out;
  for (const code of beat.lift) {
    const card = hand.find((c) => c.code === code && !out.has(c.id));
    if (card) out.add(card.id);
  }
  return out;
}

/** Tabs in table order from the seat the watcher landed behind. */
export function tabOrder(landing: number): number[] {
  return [0, 1, 2, 3].map((k) => (landing + k) % 4);
}

const SPEED_KEY = "shengji.watch.speed";

export function savedSpeed(): Speed {
  try {
    const v = Number(localStorage.getItem(SPEED_KEY));
    return (SPEEDS as readonly number[]).includes(v) ? (v as Speed) : 1;
  } catch {
    return 1;
  }
}

export function saveSpeed(speed: Speed): void {
  try { localStorage.setItem(SPEED_KEY, String(speed)); } catch { /* the speed is a convenience */ }
}

export function nextSpeed(speed: Speed): Speed {
  return SPEEDS[(SPEEDS.indexOf(speed) + 1) % SPEEDS.length];
}
