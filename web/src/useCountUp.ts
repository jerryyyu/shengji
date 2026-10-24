import { useEffect, useRef, useState } from "react";
import { DUR, prefersReducedMotion, tweenNumber } from "./motion";
import type { TweenClock } from "./motion";

export interface CountUpOptions {
  duration?: number;
  /** Jump straight to a lower value (a new round resets points to 0). */
  snapDown?: boolean;
  clock?: TweenClock;
}

/** The number to display for `target`: rolls toward each new target over
 *  `duration` and lands exactly on it. A new target mid-roll restarts from
 *  the number currently shown, so interruptions never jump backward. The
 *  first render shows `target` as is. */
export function useCountUp(target: number, opts: CountUpOptions = {}): number {
  const { duration = DUR.count, snapDown = false, clock } = opts;
  const [shown, setShown] = useState(target);
  const shownRef = useRef(target);
  useEffect(() => {
    const from = shownRef.current;
    const set = (v: number) => {
      shownRef.current = v;
      setShown(v);
    };
    const instant = prefersReducedMotion() || (snapDown && target < from);
    return tweenNumber(from, target, instant ? 0 : duration, set, clock);
  }, [target, duration, snapDown, clock]);
  return shown;
}
