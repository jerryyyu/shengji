import { useEffect, useRef, useState } from "react";
import type { RefObject } from "react";
import { haptic } from "../native";
import { prefersReducedMotion } from "../motion";

/** How far (after resistance) the page must be pulled for a release to
 *  reload it. */
export const PULL_THRESHOLD = 64;
/** Where the page rests while it reloads, the spinner in the gap above. */
export const PULL_HOLD = 52;
/** The spinner stays at least this long, so a fast reload is still seen. */
export const PULL_MIN_MS = 400;
/** A touch that starts this close to the left edge is the app's swipe back. */
export const PULL_EDGE = 20;
/** Movement before a touch counts as a pull or a sideways scroll. */
const SLOP = 6;

/** How long the page eases back up once let go or reloaded. */
export const PULL_SETTLE_MS = 300;

/** `settling` is the ease back up after a release; the page is moved (and
 *  so given a transform) only outside `idle`. */
export type PullPhase = "idle" | "pulling" | "armed" | "refreshing" | "settling";

/** The drag's offset with iOS-style resistance: about one to one at first,
 *  ever stiffer further down. */
export function rubberBand(dy: number): number {
  return dy <= 0 ? 0 : dy / (1 + dy / 320);
}

/** Pull to refresh on a page's own scroller, by touch only (mouse and pen
 *  never start it). A touch that starts at scroll-top, away from the left
 *  edge, and moves down more than sideways pulls the page; letting go past
 *  PULL_THRESHOLD calls `onRefresh` and holds the spinner until it settles
 *  and PULL_MIN_MS has passed. The pull distance is written to the
 *  scroller's `--ptr` (px) and `--ptr-p` (0 to 1) custom properties on each
 *  move rather than through React state, so a drag re-renders only on a
 *  phase change. `animate` is false under Reduce Motion, where the page
 *  snaps instead of easing and the spinner does not spin. */
export function usePullToRefresh(
  scroller: RefObject<HTMLElement | null>, onRefresh: () => Promise<unknown>, enabled: boolean,
) {
  const [phase, setPhase] = useState<PullPhase>("idle");
  const refreshRef = useRef(onRefresh);
  refreshRef.current = onRefresh;
  useEffect(() => {
    const el = scroller.current;
    if (!enabled || !el) return;
    let start: { x: number; y: number } | null = null;
    let pulling = false;
    let armed = false;
    let busy = false;
    let live = true;
    let settleTimer = 0;
    const settle = () => {
      show(0);
      window.clearTimeout(settleTimer);
      if (prefersReducedMotion()) {
        setPhase("idle");
        return;
      }
      setPhase("settling");
      settleTimer = window.setTimeout(() => { if (live) setPhase("idle"); }, PULL_SETTLE_MS);
    };
    const show = (px: number) => {
      el.style.setProperty("--ptr", `${px}px`);
      el.style.setProperty("--ptr-p", String(Math.min(1, px / PULL_THRESHOLD)));
    };
    const reset = () => {
      start = null;
      pulling = false;
      armed = false;
    };
    const onStart = (e: TouchEvent) => {
      if (busy || e.touches.length !== 1 || el.scrollTop > 0) return;
      const t = e.touches[0];
      if (t.clientX < PULL_EDGE) return;
      start = { x: t.clientX, y: t.clientY };
      pulling = false;
      armed = false;
    };
    const onMove = (e: TouchEvent) => {
      if (!start || busy) return;
      if (e.touches.length !== 1) {
        cancel();
        return;
      }
      const t = e.touches[0];
      const dx = t.clientX - start.x;
      const dy = t.clientY - start.y;
      if (!pulling) {
        if (Math.abs(dx) < SLOP && Math.abs(dy) < SLOP) return;
        // a sideways or upward move, or a page already scrolled, is the scroller's own
        if (dy <= 0 || Math.abs(dx) > dy || el.scrollTop > 0) {
          start = null;
          return;
        }
        pulling = true;
        window.clearTimeout(settleTimer);
        setPhase("pulling");
      }
      if (e.cancelable) e.preventDefault();
      const px = rubberBand(dy);
      show(px);
      const past = px >= PULL_THRESHOLD;
      if (past !== armed) {
        armed = past;
        if (past) haptic("refresh");
        setPhase(past ? "armed" : "pulling");
      }
    };
    const cancel = () => {
      if (pulling) settle();
      reset();
    };
    const onEnd = () => {
      if (!pulling) {
        reset();
        return;
      }
      const go = armed;
      reset();
      if (!go) {
        settle();
        return;
      }
      busy = true;
      show(PULL_HOLD);
      setPhase("refreshing");
      const wait = new Promise((r) => setTimeout(r, PULL_MIN_MS));
      let done: Promise<unknown>;
      try {
        done = Promise.resolve(refreshRef.current());
      } catch {
        done = Promise.resolve();
      }
      void Promise.allSettled([done, wait]).then(() => {
        if (!live) return;
        busy = false;
        settle();
      });
    };
    show(0);
    el.addEventListener("touchstart", onStart, { passive: true });
    el.addEventListener("touchmove", onMove, { passive: false });
    el.addEventListener("touchend", onEnd);
    el.addEventListener("touchcancel", cancel);
    return () => {
      live = false;
      window.clearTimeout(settleTimer);
      el.removeEventListener("touchstart", onStart);
      el.removeEventListener("touchmove", onMove);
      el.removeEventListener("touchend", onEnd);
      el.removeEventListener("touchcancel", cancel);
      el.style.removeProperty("--ptr");
      el.style.removeProperty("--ptr-p");
      setPhase("idle");
    };
  }, [scroller, enabled]);
  return { phase, animate: !prefersReducedMotion() };
}
