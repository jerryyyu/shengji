import { useEffect, useRef } from "react";
import type { RefObject } from "react";
import { SWIPE_EDGE } from "./useTabSwipe";
import { prefersReducedMotion } from "../motion";

/** A touch must start left of this to be a back swipe. The boundary pixel
 *  and everything right of it belong to the tab swipe (`useTabSwipe`), which
 *  ignores a start left of the same line, so one gesture has one owner. */
export const EDGE_PX = SWIPE_EDGE;
/** How far right it must travel to go back; a shorter drag springs back. */
export const BACK_PX = 60;
/** More vertical drift than this, or more vertical than horizontal travel,
 *  is a scroll, never a back swipe. */
export const DRIFT_PX = 40;

/** A sub-page that a swipe from the screen's left edge takes back, as the
 *  iOS edge swipe does. The touches are read on `area`, which must span the
 *  whole width of the screen (the page's own scroller), so a finger put
 *  down on the outermost pixels, beside the centred column, still starts
 *  the swipe; `page` (the column's content) follows the finger while it
 *  drags. `onBack` runs on a drag past `BACK_PX`; anything shorter, more
 *  vertical, or started away from the edge leaves the page as it was, so a
 *  tap or a scroll anywhere else (the swatches, the stage) is untouched. The
 *  listeners are passive and never call preventDefault. Under Reduce Motion
 *  the page does not follow the finger or spring back; the release alone
 *  goes back. */
export function useEdgeSwipeBack(area: RefObject<HTMLElement | null>, page: RefObject<HTMLElement | null>,
                                 onBack: () => void, enabled: boolean): void {
  const back = useRef(onBack);
  back.current = onBack;
  useEffect(() => {
    const el = area.current;
    if (!enabled || !el) return;
    let start: { x: number; y: number } | null = null;
    let dx = 0;
    const still = prefersReducedMotion();
    const follow = (x: number) => {
      const node = page.current;
      if (!node || still) return;
      node.style.transition = x === 0 ? "transform var(--dur-fast, 0.18s) ease-out" : "none";
      node.style.transform = x === 0 ? "" : `translateX(${x}px)`;
    };
    const reset = () => {
      start = null;
      dx = 0;
      follow(0);
    };
    const onStart = (e: TouchEvent) => {
      const t = e.touches[0];
      start = e.touches.length === 1 && t && t.clientX < EDGE_PX ? { x: t.clientX, y: t.clientY } : null;
      dx = 0;
    };
    const onMove = (e: TouchEvent) => {
      if (!start) return;
      const t = e.touches[0];
      if (!t) return;
      const x = t.clientX - start.x;
      const y = Math.abs(t.clientY - start.y);
      if (y > DRIFT_PX || (y > 12 && y > Math.abs(x))) {
        reset();
        return;
      }
      dx = Math.max(0, x);
      follow(dx);
    };
    const onEnd = () => {
      const went = start !== null && dx > BACK_PX;
      reset();
      if (went) back.current();
    };
    el.addEventListener("touchstart", onStart, { passive: true });
    el.addEventListener("touchmove", onMove, { passive: true });
    el.addEventListener("touchend", onEnd, { passive: true });
    el.addEventListener("touchcancel", reset, { passive: true });
    return () => {
      el.removeEventListener("touchstart", onStart);
      el.removeEventListener("touchmove", onMove);
      el.removeEventListener("touchend", onEnd);
      el.removeEventListener("touchcancel", reset);
      follow(0);
    };
  }, [area, page, enabled]);
}
