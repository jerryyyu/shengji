import { useRef } from "react";
import type { ReactNode, TouchEvent } from "react";

/** A touch must start this close to the left edge to be a back swipe. */
export const EDGE_PX = 24;
/** How far right it must travel to go back; a shorter drag springs back. */
export const BACK_PX = 60;
/** More vertical drift than this, or more vertical than horizontal travel,
 *  is a scroll, never a back swipe. */
export const DRIFT_PX = 40;

/** A sub-page that a swipe from its left edge takes back, as the iOS edge
 *  swipe does: the page follows the finger while it drags, `onBack` runs on
 *  a drag past `BACK_PX`, and anything shorter, more vertical, or started
 *  away from the edge leaves the page as it was. Only touches that start in
 *  the edge strip are followed, so a tap or a scroll anywhere else on the
 *  page (its swatches, its stage) is untouched. The listeners never call
 *  preventDefault. */
export default function EdgeSwipeBack({ onBack, children, className = "" }: {
  onBack: () => void; children: ReactNode; className?: string;
}) {
  const el = useRef<HTMLDivElement>(null);
  const start = useRef<{ x: number; y: number } | null>(null);
  const dx = useRef(0);

  const follow = (x: number) => {
    const node = el.current;
    if (!node) return;
    node.style.transition = x === 0 ? "transform var(--dur-fast, 0.18s) ease-out" : "none";
    node.style.transform = x === 0 ? "" : `translateX(${x}px)`;
  };
  const reset = () => {
    start.current = null;
    dx.current = 0;
    follow(0);
  };

  const onTouchStart = (e: TouchEvent) => {
    const t = e.touches[0];
    start.current = e.touches.length === 1 && t.clientX <= EDGE_PX ? { x: t.clientX, y: t.clientY } : null;
    dx.current = 0;
  };
  const onTouchMove = (e: TouchEvent) => {
    const s = start.current;
    if (!s) return;
    const t = e.touches[0];
    const x = t.clientX - s.x;
    const y = Math.abs(t.clientY - s.y);
    if (y > DRIFT_PX || (y > 12 && y > Math.abs(x))) {
      reset();
      return;
    }
    dx.current = Math.max(0, x);
    follow(dx.current);
  };
  const onTouchEnd = () => {
    const went = start.current !== null && dx.current > BACK_PX;
    reset();
    if (went) onBack();
  };

  return (
    <div ref={el} className={`edge-swipe ${className}`} onTouchStart={onTouchStart} onTouchMove={onTouchMove}
         onTouchEnd={onTouchEnd} onTouchCancel={reset}>
      {children}
    </div>
  );
}
