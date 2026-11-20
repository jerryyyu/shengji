import type { MouseEvent as ReactMouseEvent, TouchEvent as ReactTouchEvent } from "react";

/** How far a finger may move between touchstart and touchend and still be a tap. */
export const TAP_SLOP_PX = 10;

let start: { el: EventTarget; id: number; x: number; y: number } | null = null;

/** Handlers for a control that must answer every tap while the page keeps
 *  changing under it. iOS WebKit drops the click of a tap when content
 *  changes during the tap (its hover heuristic reads the change as a hover
 *  menu opening), and the table changes several times a second while the
 *  cards are dealt, so a click handler alone misses taps there. A tap acts
 *  on touchend and cancels the click, so it acts once and no late click
 *  lands on whatever opened in its place. It is a tap only when one finger
 *  starts on the control, never strays past TAP_SLOP_PX (a drag that comes
 *  back is still a drag) and lifts over the control itself, hit-tested at
 *  the release point because touch events stay aimed at where they began.
 *  Anything else is left to the browser; a mouse, a keyboard or a screen
 *  reader still arrives as the click. */
export function tapHandlers<T extends HTMLElement>(act: (e: ReactMouseEvent<T> | ReactTouchEvent<T>) => void) {
  return {
    onTouchStart: (e: ReactTouchEvent<T>) => {
      const t = e.touches.length === 1 ? e.changedTouches[0] : undefined;
      start = t ? { el: e.currentTarget, id: t.identifier, x: t.clientX, y: t.clientY } : null;
    },
    onTouchMove: (e: ReactTouchEvent<T>) => {
      const s = start;
      if (!s) return;
      if (e.touches.length > 1) { start = null; return; }
      const t = Array.from(e.changedTouches).find((c) => c.identifier === s.id);
      if (t && (Math.abs(t.clientX - s.x) > TAP_SLOP_PX || Math.abs(t.clientY - s.y) > TAP_SLOP_PX)) start = null;
    },
    onTouchEnd: (e: ReactTouchEvent<T>) => {
      const s = start;
      start = null;
      const t = e.changedTouches[0];
      const el = e.currentTarget;
      if (!s || !t || s.el !== el || t.identifier !== s.id || e.touches.length > 0) return;
      if (Math.abs(t.clientX - s.x) > TAP_SLOP_PX || Math.abs(t.clientY - s.y) > TAP_SLOP_PX) return;
      // jsdom has no hit test; a browser always has one
      const hit = typeof document.elementFromPoint === "function" ? document.elementFromPoint(t.clientX, t.clientY) : el;
      if (!hit || !el.contains(hit)) return;
      if (el.getAttribute("aria-disabled") === "true" || (el as HTMLElement & { disabled?: boolean }).disabled) return;
      if (!e.cancelable) return;
      e.preventDefault();
      act(e);
    },
    onTouchCancel: () => { start = null; },
    onClick: (e: ReactMouseEvent<T>) => act(e),
  };
}
