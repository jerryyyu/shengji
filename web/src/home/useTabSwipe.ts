import { useEffect, useRef } from "react";
import type { RefObject } from "react";
import { haptic } from "../native";
import { prefersReducedMotion } from "../motion";
import { openTab } from "./route";
import type { Tab } from "./route";

/** The phone tab bar's order, which a swipe walks: left goes to the next. */
export const TAB_ORDER: readonly Tab[] = ["play", "leaderboard", "me"];
/** A touch that starts this close to either screen edge is the app's own
 *  back or forward swipe. */
export const SWIPE_EDGE = 24;
/** Movement before a touch is locked to a sideways swipe or to scrolling. */
export const SWIPE_LOCK = 10;
/** The share of the page's width a release must pass to change tabs. */
export const SWIPE_COMMIT = 0.35;
/** A release at least this fast (px/ms) in the drag's direction changes tabs
 *  however short the drag. */
export const SWIPE_FLICK = 0.5;
/** How long the page eases to rest after a release. */
export const SWIPE_SETTLE_MS = 280;
/** Velocity is measured over this much of the drag's end. */
const VELOCITY_WINDOW_MS = 100;

/** A touch starting on any of these keeps its own meaning: text entry, a
 *  segmented control, a sheet or dialog, the lobby's table preview, or
 *  anything marked `data-no-tab-swipe`. */
const EXCLUDED =
  "input, textarea, select, [contenteditable]:not([contenteditable='false']), .segmented, " +
  ".q-layer, .q-sheet, .q-dlg, .lobby-preview, [data-no-tab-swipe]";
/** While any of these is open the page under it never swipes. */
const OPEN_LAYER = ".q-layer, [aria-modal='true'], dialog[open]";

/** The tab beside `tab` in the swipe's direction: a leftward drag (dx < 0)
 *  brings the next tab in, a rightward one the previous; null past either end. */
export function neighbourTab(tab: Tab, dx: number): Tab | null {
  const i = TAB_ORDER.indexOf(tab) + (dx < 0 ? 1 : -1);
  return TAB_ORDER[i] ?? null;
}

/** A drag past the first or last tab, with resistance: about half the finger's
 *  travel at first and ever stiffer, never more than half the width. */
export function edgeBand(dx: number, width: number): number {
  return (dx * 0.5) / (1 + Math.abs(dx) / width);
}

/** Whether the touch began inside something that scrolls sideways itself. */
function inSideScroller(from: Element, stop: Element): boolean {
  for (let n: Element | null = from; n && n !== stop; n = n.parentElement) {
    if (n.scrollWidth > n.clientWidth + 1) {
      const ox = getComputedStyle(n).overflowX;
      if (ox === "auto" || ox === "scroll") return true;
    }
  }
  return false;
}

const now = () => performance.now();

/** A horizontal swipe across a phone's home page moves to the tab beside it,
 *  by touch only (mouse and pen never start it). The touch must start away
 *  from both screen edges, outside the EXCLUDED controls and anything that
 *  scrolls sideways, with no sheet or dialog open. After SWIPE_LOCK px it
 *  locks: a mostly sideways move (and not one the page's pull to refresh has
 *  taken) is a swipe and from then on stops the page scrolling; anything else
 *  is left to the scroller. The page follows the finger through the
 *  `--tab-swipe-x` custom property on the `.home-body` while `data-tab-swipe` is set,
 *  so a drag never re-renders. A release past SWIPE_COMMIT of the width, or a
 *  SWIPE_FLICK, opens the tab (with a light haptic in the app) and the new
 *  page slides in from where its neighbour would be; otherwise the page
 *  springs back. Past the first or last tab it rubber-bands and never
 *  switches. Under Reduce Motion the page does not move and a swipe switches
 *  at once. */
export function useTabSwipe(body: RefObject<HTMLElement | null>, active: Tab, enabled: boolean): void {
  const activeRef = useRef(active);
  activeRef.current = active;
  useEffect(() => {
    const el = body.current;
    if (!enabled || !el) return;
    type Drag = { x: number; y: number; lock: "x" | null; dx: number; width: number; animate: boolean;
                  samples: { x: number; t: number }[] };
    let g: Drag | null = null;
    let settleTimer = 0;
    const show = (px: number) => el.style.setProperty("--tab-swipe-x", `${px}px`);
    const clear = () => {
      window.clearTimeout(settleTimer);
      delete el.dataset.tabSwipe;
      el.style.removeProperty("--tab-swipe-x");
    };
    const settle = (to: number) => {
      el.dataset.tabSwipe = "settle";
      show(to);
      window.clearTimeout(settleTimer);
      settleTimer = window.setTimeout(clear, SWIPE_SETTLE_MS);
    };
    const offset = (d: Drag) => {
      if (neighbourTab(activeRef.current, d.dx) === null) return edgeBand(d.dx, d.width);
      return Math.max(-d.width, Math.min(d.width, d.dx));
    };
    const onStart = (e: TouchEvent) => {
      g = null;
      if (e.touches.length !== 1) return;
      const t = e.touches[0];
      if (t.clientX < SWIPE_EDGE || t.clientX > window.innerWidth - SWIPE_EDGE) return;
      const from = e.target;
      if (!(from instanceof Element) || from.closest(EXCLUDED)) return;
      if (document.querySelector(OPEN_LAYER) || inSideScroller(from, el)) return;
      const width = el.getBoundingClientRect().width || window.innerWidth;
      g = { x: t.clientX, y: t.clientY, lock: null, dx: 0, width, animate: !prefersReducedMotion(),
            samples: [{ x: t.clientX, t: now() }] };
    };
    const onMove = (e: TouchEvent) => {
      if (!g) return;
      if (e.touches.length !== 1) {
        cancel();
        return;
      }
      const t = e.touches[0];
      const dx = t.clientX - g.x;
      const dy = t.clientY - g.y;
      if (g.lock === null) {
        // a move the page's pull to refresh has taken is vertical
        if (e.defaultPrevented) {
          g = null;
          return;
        }
        if (Math.abs(dx) < SWIPE_LOCK && Math.abs(dy) < SWIPE_LOCK) return;
        if (Math.abs(dx) <= Math.abs(dy)) {
          g = null;
          return;
        }
        g.lock = "x";
        window.clearTimeout(settleTimer);
        if (g.animate) el.dataset.tabSwipe = "drag";
      }
      if (e.cancelable) e.preventDefault();
      g.dx = dx;
      const at = now();
      g.samples.push({ x: t.clientX, t: at });
      while (g.samples.length > 2 && at - g.samples[0].t > VELOCITY_WINDOW_MS) g.samples.shift();
      if (g.animate) show(offset(g));
    };
    const cancel = () => {
      const d = g;
      g = null;
      if (d?.lock && d.animate) settle(0);
    };
    const onEnd = () => {
      const d = g;
      g = null;
      if (!d || d.lock !== "x") return;
      const first = d.samples[0];
      const last = d.samples[d.samples.length - 1];
      const dt = last.t - first.t;
      const v = dt > 0 ? (last.x - first.x) / dt : 0;
      const to = neighbourTab(activeRef.current, d.dx);
      const go = to !== null && d.dx !== 0
        && (Math.abs(d.dx) >= SWIPE_COMMIT * d.width || (Math.abs(v) >= SWIPE_FLICK && Math.sign(v) === Math.sign(d.dx)));
      if (!go) {
        if (d.animate) settle(0);
        return;
      }
      haptic("tab");
      if (!d.animate) {
        clear();
        openTab(to);
        return;
      }
      // the new page starts where it would sit beside the old one, then slides home
      el.dataset.tabSwipe = "drag";
      show(d.dx + (d.dx < 0 ? d.width : -d.width));
      openTab(to);
      void el.offsetWidth;
      settle(0);
    };
    el.addEventListener("touchstart", onStart, { passive: true });
    el.addEventListener("touchmove", onMove, { passive: false });
    el.addEventListener("touchend", onEnd, { passive: true });
    el.addEventListener("touchcancel", cancel, { passive: true });
    return () => {
      el.removeEventListener("touchstart", onStart);
      el.removeEventListener("touchmove", onMove);
      el.removeEventListener("touchend", onEnd);
      el.removeEventListener("touchcancel", cancel);
      clear();
    };
  }, [body, enabled]);
}
