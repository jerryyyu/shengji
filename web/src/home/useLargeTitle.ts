import { useEffect, useRef, useState } from "react";
import type { RefObject } from "react";

/** An iOS large title over a page's own scroller: `collapsed` turns true
 *  once the large title has scrolled up under the sticky bar, which then
 *  shows the compact title and its hairline. Measured on scroll, at most
 *  once a frame, from the two boxes' bottoms, so it holds whatever the bar's
 *  safe-area inset or the title's text size. Off (never collapsed) when
 *  `enabled` is false. */
export function useLargeTitle(scroller: RefObject<HTMLElement | null>, enabled: boolean) {
  const bar = useRef<HTMLDivElement | null>(null);
  const title = useRef<HTMLHeadingElement | null>(null);
  const [collapsed, setCollapsed] = useState(false);
  useEffect(() => {
    const el = scroller.current;
    if (!enabled || !el) {
      setCollapsed(false);
      return;
    }
    let frame = 0;
    const measure = () => {
      frame = 0;
      const b = bar.current;
      const t = title.current;
      if (!b || !t) return;
      const edge = b.getBoundingClientRect();
      // a bar with no height is not laid out yet (or hidden): nothing to collapse into
      setCollapsed(edge.height > 0 && t.getBoundingClientRect().bottom <= edge.bottom);
    };
    const schedule = () => {
      if (frame === 0) frame = requestAnimationFrame(measure);
    };
    measure();
    el.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule);
    return () => {
      if (frame !== 0) cancelAnimationFrame(frame);
      el.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
    };
  }, [scroller, enabled]);
  return { bar, title, collapsed };
}
