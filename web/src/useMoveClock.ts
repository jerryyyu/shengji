import { useEffect, useRef, useState } from "react";
import { haptic } from "./native";

/** The move timer's full length (server.py MOVE_TIMER): the ring starts full
 *  at this many seconds. */
export const MOVE_SECS = 60;
/** The ring turns red, and Play glows, in the last LOW_SECS of a decision. */
export const LOW_SECS = 10;
/** One light haptic when this many seconds are left. */
export const BUZZ_SECS = 5;

/** A move timer's sample: the seconds left, and the deadline they count to
 *  (a Date.now() time, in ms). The deadline changes only when a server state
 *  restarts the count, so a redraw between ticks can tell a fresh server
 *  figure from the same one read again. */
export interface MoveClockSample { left: number | null; end: number | null }

/** Seconds left on a move timer (yours, or another seat's), ticked locally between server states.
 *  `stamp` is the state the number came with: every state restarts the count
 *  from the server's own figure, so the two never drift apart. It ticks as
 *  each whole second is reached, when the number shown changes: the ring's
 *  drain is its own animation (MoveClock.tsx), started from `end`. */
export function useMoveClockSample(seconds: number | null | undefined, stamp: unknown,
                                   buzz = true): MoveClockSample {
  const [sample, setSample] = useState<MoveClockSample>(() => (
    seconds === null || seconds === undefined ? { left: null, end: null }
      : { left: seconds, end: Date.now() + seconds * 1000 }));
  useEffect(() => {
    if (seconds === null || seconds === undefined) {
      setSample((s) => (s.left === null && s.end === null ? s : { left: null, end: null }));
      return;
    }
    const end = Date.now() + seconds * 1000;
    let id = 0;
    const tick = () => {
      const ms = Math.max(0, end - Date.now());
      setSample({ left: ms / 1000, end });
      if (ms > 0) id = window.setTimeout(tick, ms % 1000 || 1000);
    };
    tick();
    return () => window.clearTimeout(id);
  }, [seconds, stamp]);
  const left = sample.left;
  // one buzz per decision, the first time the clock is at BUZZ_SECS or less
  const buzzed = useRef(false);
  useEffect(() => {
    if (left === null || left > BUZZ_SECS) {
      buzzed.current = false;
      return;
    }
    if (!buzzed.current) {
      buzzed.current = true;
      if (buzz) haptic("clock");
    }
  }, [left, buzz]);
  return sample;
}

/** The seconds left alone, for a caller that draws no ring. */
export function useMoveClock(seconds: number | null | undefined, stamp: unknown,
                             buzz = true): number | null {
  return useMoveClockSample(seconds, stamp, buzz).left;
}
