// A live figure's pose over time: a cycle of moves it plays by itself, and
// its special (the `react` pose) on a tap. A move that plays once (hop,
// cheer, react) lasts as long as its own animation (`poseMs`); a resting
// move (idle, sleep) for the time its step names. The cycle runs only while
// the figure is on screen and the page is visible, and never under Reduce
// Motion, where a tap still shows the special, drawn still at its peak.
import { useCallback, useEffect, useRef, useState } from "react";
import type { RefObject } from "react";
import { prefersReducedMotion } from "../motion";
import type { Pose } from "./Companion";
import { DRAWINGS } from "./kinds";
import type { DrawnKind } from "./kinds";

/** One step of a cycle: a pose, and for idle or sleep how long it rests. */
export type CycleStep = readonly [Pose, number?];

/** The stage's cycle: idle, hop, cheer, the special, a short sleep. */
export const PAGE_CYCLE: readonly CycleStep[] = [["idle", 3000], ["hop"], ["idle", 1200], ["cheer"], ["idle", 1200],
  ["react"], ["sleep", 2400]];
/** A once-move whose animation end never comes (a figure off screen) ends
 *  after its length and this much more. */
const END_SLACK_MS = 250;

/** How long `pose` plays for `kind`, in ms (the once-moves' animation lengths). */
export function poseMs(kind: DrawnKind, pose: Pose): number {
  const char = DRAWINGS[kind].char;
  if (pose === "hop") return char ? 500 : 600;
  if (pose === "cheer") return 1200;
  if (pose === "react") return DRAWINGS[kind].reactMs;
  return 0;
}

const once = (p: Pose) => p === "hop" || p === "cheer" || p === "react";

/** The pose of a live figure of `kind` cycling through `cycle` while the
 *  element `on` is on screen. `tap()` plays the special now, from its start
 *  even during one: the figure's `key` changes so its animation restarts
 *  from the top. `play(pose)` plays any once-move now (a
 *  purchase's cheer). While the figure is off screen or the page hidden,
 *  `paused` is true (the owner pauses its animations) and a move that ends
 *  then is counted only once it is back in view. `onPoseEnd` goes to the
 *  figure. */
export function useLivePose(kind: DrawnKind, cycle: readonly CycleStep[], on: RefObject<Element | null>) {
  const still = prefersReducedMotion();
  const [step, setStep] = useState(0);
  const [extra, setExtra] = useState<Pose | null>(null);
  const [nonce, setNonce] = useState(0);
  const [shown, setShown] = useState(true);
  const shownNow = useRef(true);
  const owed = useRef(false);
  const [stepPose, rest] = cycle[step % cycle.length];
  const pose: Pose = extra ?? (still ? "idle" : stepPose);

  // on screen and on a visible page only
  useEffect(() => {
    const el = on.current;
    let inView = true;
    const update = () => {
      const now = inView && document.visibilityState !== "hidden";
      shownNow.current = now;
      setShown(now);
    };
    let io: IntersectionObserver | null = null;
    if (el && typeof IntersectionObserver === "function") {
      io = new IntersectionObserver((entries) => { inView = entries.some((e) => e.isIntersecting); update(); });
      io.observe(el);
    }
    document.addEventListener("visibilitychange", update);
    update();
    return () => { io?.disconnect(); document.removeEventListener("visibilitychange", update); };
  }, [on]);

  const finish = useCallback(() => {
    if (extra !== null) {
      setExtra(null);
      // a tap that restarted the cycle's own move stood in for it: move on past it
      if (!still && extra === stepPose && once(stepPose)) setStep((s) => s + 1);
      return;
    }
    if (once(stepPose)) setStep((s) => s + 1);
  }, [extra, stepPose, still]);
  // a move that ends while the figure is out of view is counted when it is back
  const end = useCallback(() => {
    if (!shownNow.current) {
      owed.current = true;
      return;
    }
    finish();
  }, [finish]);
  useEffect(() => {
    if (shown && owed.current) {
      owed.current = false;
      finish();
    }
  }, [shown, finish]);

  // a resting step moves on after its time; a once-move after its animation
  // (onPoseEnd), or its length and some slack when no end comes
  useEffect(() => {
    if (!shown) return;
    if (extra !== null) {
      if (still) return;           // the still frame ends itself (Companion's own timer)
      const t = window.setTimeout(end, poseMs(kind, extra) + END_SLACK_MS);
      return () => window.clearTimeout(t);
    }
    if (still) return;
    const t = window.setTimeout(once(stepPose) ? end : () => setStep((s) => s + 1),
      once(stepPose) ? poseMs(kind, stepPose) + END_SLACK_MS : rest ?? 0);
    return () => window.clearTimeout(t);
  }, [shown, still, extra, nonce, stepPose, rest, step, kind, end]);

  const play = useCallback((p: Pose) => {
    setExtra(p);
    setNonce((n) => n + 1);
  }, []);
  const tap = useCallback(() => {
    setExtra("react");
    setNonce((n) => n + 1);
  }, []);
  return { pose, tap, play, onPoseEnd: end, key: nonce, paused: !shown };
}
