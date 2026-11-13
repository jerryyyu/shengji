import { useEffect, useRef, useState } from "react";
import { haptic } from "./native";

/** The ring shows only in the last RING_SECS of a decision. */
export const RING_SECS = 10;
/** One light haptic when this many seconds are left. */
export const BUZZ_SECS = 5;

/** Seconds left on your move timer, ticked locally between server states.
 *  `stamp` is the state the number came with: every state restarts the count
 *  from the server's own figure, so the two never drift apart. */
export function useMoveClock(seconds: number | null | undefined, stamp: unknown): number | null {
  const [left, setLeft] = useState<number | null>(seconds ?? null);
  useEffect(() => {
    if (seconds === null || seconds === undefined) {
      setLeft(null);
      return;
    }
    const end = Date.now() + seconds * 1000;
    const tick = () => setLeft(Math.max(0, (end - Date.now()) / 1000));
    tick();
    const id = window.setInterval(tick, 250);
    return () => window.clearInterval(id);
  }, [seconds, stamp]);
  // one buzz per decision, the first time the clock is at BUZZ_SECS or less
  const buzzed = useRef(false);
  useEffect(() => {
    if (left === null || left > BUZZ_SECS) {
      buzzed.current = false;
      return;
    }
    if (!buzzed.current) {
      buzzed.current = true;
      haptic("clock");
    }
  }, [left]);
  return left;
}
