import { useEffect } from "react";
import type { MutableRefObject, RefObject } from "react";
import { haptic } from "../native";
import { currentTranslate, prefersReducedMotion } from "../motion";
import { WIDE } from "../home/route";

/** Movement before a touch is locked to a vertical drag or let go. */
export const SHEET_LOCK = 8;
/** The share of the sheet's height a release must pass to dismiss it. */
export const SHEET_DISMISS = 0.25;
/** A downward release at least this fast (px/ms) dismisses however short. */
export const SHEET_FLICK = 0.5;
/** How long the sheet slides out, or springs back, after a release. */
export const SHEET_SETTLE_MS = 200;
/** Velocity is measured over this much of the drag's end. */
const VELOCITY_WINDOW_MS = 100;

/** A touch starting on any of these keeps its own meaning: text entry and
 *  every button or link, the header's Cancel among them. */
const EXCLUDED =
  "input, textarea, select, button, a[href], label, [role='button'], " +
  "[contenteditable]:not([contenteditable='false'])";
/** A touch here drags the sheet whatever its scroll. */
const HANDLE = ".q-grab, .q-sheet-head";

/** An upward drag, with resistance: a fifth of the finger's travel at first
 *  and ever stiffer, never more than a fifth of the sheet's height. */
export function sheetBand(dy: number, height: number): number {
  return (dy * 0.2) / (1 + Math.abs(dy) / Math.max(1, height));
}

/** Whether anything from the touch up to the sheet itself is scrolled down. */
function scrolledDown(from: Element, sheet: Element): boolean {
  for (let n: Element | null = from; n; n = n.parentElement) {
    if (n.scrollTop > 0) return true;
    if (n === sheet) return false;
  }
  return false;
}

const now = () => performance.now();

/** A phone's bottom sheet follows a downward drag and is dismissed by it, by
 *  touch only (mouse and pen never start it) and below 700px only, where the
 *  sheet sits at the bottom with its grab handle. A drag starts on the grab
 *  handle or header at any time, or anywhere else in the sheet when nothing
 *  under the finger is scrolled down and the finger moves down first; never
 *  on a control from EXCLUDED. After SHEET_LOCK px a mostly vertical move
 *  locks the drag, which from then on stops the page scrolling; a sideways
 *  one is left alone. The sheet follows the finger through `--sheet-drag-y`
 *  on the layer while `data-sheet-drag` is set, and the scrim fades with
 *  `--sheet-scrim`, so a drag never re-renders; an upward drag rubber-bands.
 *  A release past SHEET_DISMISS of the height, or a downward SHEET_FLICK,
 *  slides the sheet out and then calls onClose; otherwise it springs back.
 *  A second finger or a cancelled touch springs it back too. A touch that
 *  lands while the sheet is still moving (springing back or sliding in)
 *  catches it where it is drawn, read from its computed transform, and the
 *  drag carries on from there with no jump. Passing the dismiss point ticks a
 *  light haptic in the app. Under Reduce Motion the sheet does not move and
 *  a release dismisses or stays at once. */
export function useSheetDrag(
  layerRef: RefObject<HTMLElement | null>,
  sheetRef: RefObject<HTMLElement | null>,
  close: MutableRefObject<() => void>,
): void {
  useEffect(() => {
    const layer = layerRef.current;
    const sheet = sheetRef.current;
    if (!layer || !sheet) return;
    // base: where the sheet was drawn when the touch caught it, nonzero only
    // for a touch that landed while it was still moving
    type Drag = { y: number; x: number; lock: boolean; handle: boolean; dy: number; height: number;
                  base: number; animate: boolean; past: boolean; samples: { y: number; t: number }[] };
    let g: Drag | null = null;
    let timer = 0;
    let leaving = false;
    const show = (offset: number, height: number) => {
      layer.style.setProperty("--sheet-drag-y", `${offset}px`);
      const fade = height > 0 ? Math.max(0, Math.min(1, offset / height)) : 0;
      layer.style.setProperty("--sheet-scrim", String(1 - fade));
    };
    const clear = () => {
      window.clearTimeout(timer);
      delete layer.dataset.sheetDrag;
      layer.style.removeProperty("--sheet-drag-y");
      layer.style.removeProperty("--sheet-scrim");
    };
    const settle = (d: Drag) => {
      if (!d.animate) {
        clear();
        return;
      }
      layer.dataset.sheetDrag = "settle";
      show(0, d.height);
      window.clearTimeout(timer);
      timer = window.setTimeout(clear, SHEET_SETTLE_MS);
    };
    const total = (d: Drag) => d.base + d.dy;
    const offset = (d: Drag) => (total(d) >= 0 ? total(d) : sheetBand(total(d), d.height));
    // a drag that let the sheet go away from rest must put it back
    const moved = (d: Drag) => d.lock || d.base !== 0;
    const cancel = () => {
      const d = g;
      g = null;
      if (d && moved(d)) settle(d);
    };
    const onStart = (e: TouchEvent) => {
      // a second finger, or a new touch, ends any drag still under way
      cancel();
      if (leaving || e.touches.length !== 1) return;
      if (window.matchMedia?.(WIDE)?.matches) return;
      const from = e.target;
      if (!(from instanceof Element) || from.closest(EXCLUDED)) return;
      const handle = !!from.closest(HANDLE);
      if (!handle && scrolledDown(from, sheet)) return;
      const t = e.touches[0];
      const height = sheet.getBoundingClientRect().height || sheet.offsetHeight || window.innerHeight;
      const animate = !prefersReducedMotion();
      const drawn = animate ? currentTranslate(sheet).dy : 0;
      const base = Math.abs(drawn) >= 0.5 ? drawn : 0;
      g = { x: t.clientX, y: t.clientY, lock: false, handle, dy: 0, height, base, animate,
            past: false, samples: [{ y: t.clientY, t: now() }] };
      if (base !== 0) {
        // hold it under the finger from the first touch, before any lock
        window.clearTimeout(timer);
        layer.classList.remove("q-in");
        layer.dataset.sheetDrag = "drag";
        show(offset(g), height);
      }
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
      if (!g.lock) {
        if (Math.abs(dx) < SHEET_LOCK && Math.abs(dy) < SHEET_LOCK) return;
        // sideways is not a drag; upward from the body is the sheet's own
        // scroll, unless the touch caught the sheet away from rest
        if (Math.abs(dy) <= Math.abs(dx) || (!g.handle && dy < 0 && g.base === 0)) {
          cancel();
          return;
        }
        g.lock = true;
        window.clearTimeout(timer);
        layer.classList.remove("q-in");
        if (g.animate) layer.dataset.sheetDrag = "drag";
      }
      if (e.cancelable) e.preventDefault();
      g.dy = dy;
      const at = now();
      g.samples.push({ y: t.clientY, t: at });
      while (g.samples.length > 2 && at - g.samples[0].t > VELOCITY_WINDOW_MS) g.samples.shift();
      const past = total(g) >= SHEET_DISMISS * g.height;
      if (past !== g.past) {
        g.past = past;
        if (past) haptic("sheet");
      }
      if (g.animate) show(offset(g), g.height);
    };
    const onEnd = (e: TouchEvent) => {
      const d = g;
      g = null;
      if (!d) return;
      if (!d.lock) {
        if (moved(d)) settle(d);
        return;
      }
      // velocity runs up to the release itself, so a finger that stopped
      // before lifting has none
      const at = now();
      const endY = e.changedTouches?.[0]?.clientY ?? d.samples[d.samples.length - 1].y;
      const recent = [...d.samples, { y: endY, t: at }].filter((p) => at - p.t <= VELOCITY_WINDOW_MS);
      const first = recent[0];
      const dt = at - first.t;
      const v = dt > 0 ? (endY - first.y) / dt : 0;
      const go = total(d) > 0 && (total(d) >= SHEET_DISMISS * d.height || v >= SHEET_FLICK);
      if (!go) {
        settle(d);
        return;
      }
      leaving = true;
      if (!d.animate) {
        clear();
        close.current();
        return;
      }
      layer.dataset.sheetDrag = "out";
      show(d.height, d.height);
      window.clearTimeout(timer);
      timer = window.setTimeout(() => close.current(), SHEET_SETTLE_MS);
    };
    sheet.addEventListener("touchstart", onStart, { passive: true });
    sheet.addEventListener("touchmove", onMove, { passive: false });
    sheet.addEventListener("touchend", onEnd, { passive: true });
    sheet.addEventListener("touchcancel", cancel, { passive: true });
    return () => {
      sheet.removeEventListener("touchstart", onStart);
      sheet.removeEventListener("touchmove", onMove);
      sheet.removeEventListener("touchend", onEnd);
      sheet.removeEventListener("touchcancel", cancel);
      clear();
    };
  }, [layerRef, sheetRef, close]);
}
