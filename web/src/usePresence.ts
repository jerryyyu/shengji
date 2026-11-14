import { useEffect, useState } from "react";
import { prefersReducedMotion } from "./motion";

/** How long a popover takes to scale and fade in or out; `.pop-in` and
 *  `.pop-out` in index.css use the same number. */
export const POP_MS = 200;

/** Whether a close can play its fade: not under Reduce Motion, and only
 *  where the page can animate at all (jsdom cannot, so tests see the
 *  element go at once, as they did before). */
function canPop(): boolean {
  return !prefersReducedMotion()
    && typeof document !== "undefined" && typeof document.body?.animate === "function";
}

/** Keeps a popover mounted through its closing fade. `mounted` says whether
 *  to render it, `className` is its `pop-in` or `pop-out` class, empty under
 *  Reduce Motion, where it appears and goes at once. Opening again mid-fade
 *  cancels the close. */
export function usePresence(open: boolean): { mounted: boolean; className: string } {
  const [mounted, setMounted] = useState(open);
  const [leaving, setLeaving] = useState(false);
  // derived during render, so the frame that opens the popover already draws it
  if (open && !mounted) setMounted(true);
  if (open && leaving) setLeaving(false);
  if (!open && mounted && !leaving) {
    if (canPop()) setLeaving(true);
    else setMounted(false);
  }
  useEffect(() => {
    if (!leaving) return;
    const timer = window.setTimeout(() => { setLeaving(false); setMounted(false); }, POP_MS);
    return () => window.clearTimeout(timer);
  }, [leaving]);
  const animate = !prefersReducedMotion();
  return { mounted, className: !animate ? "" : leaving ? "pop-out" : "pop-in" };
}
