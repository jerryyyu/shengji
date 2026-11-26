import { useRef } from "react";
import type { CSSProperties } from "react";
import { LOW_SECS } from "../useMoveClock";
import { useT } from "../i18n";

/** A new figure from the server that moves the deadline by more than this
 *  restarts the drain from it; smaller differences are network jitter. */
export const RING_RESYNC_MS = 500;

/** Where the drain starts: the deadline it runs to, and the seconds already
 *  gone from the window when it starts (negative while a window the server
 *  extended is still above `total`). `key` changes on every restart; `left`
 *  is the last sample read against the deadline, and `seen` the last `end`
 *  the caller gave with it. */
interface Anchor { end: number; total: number; gone: number; key: number; left: number; seen: number | null }

/** The one timer: a ring that drains from full over the whole window, with
 *  the seconds left in its centre. It turns red for the last LOW_SECS.
 *  `thin` is the quieter ring on someone else's seat pill. A left above
 *  `total` (a window the server extended) draws a full ring until the
 *  window starts.
 *
 *  The drain is one CSS animation over the whole window, two half rings
 *  turned by `transform`, so it runs on the compositor and is continuous;
 *  React redraws only the seconds. Each `left` is checked against the
 *  running drain's deadline, and a deadline that has moved (the server
 *  restarted or extended the window) starts the drain again from it.
 *
 *  `end` is the deadline the sample counts to (useMoveClockSample), when the
 *  caller has it: it is compared as given, so a fresh server figure that
 *  repeats the seconds still restarts the drain if its deadline moved. */
export function TimerRing({ left, total, end = null, thin = false }: {
  left: number | null; total: number; end?: number | null; thin?: boolean;
}) {
  const t = useT();
  const anchor = useRef<Anchor | null>(null);
  if (left === null) {
    anchor.current = null;
    return null;
  }
  // Without `end`, a new sample of `left` is drawn as it is taken, so the
  // deadline it implies is read then. A redraw that brings the same sample
  // (a card chosen between ticks) reads nothing: the sample has aged since,
  // and would look like a moved deadline.
  let a = anchor.current;
  if (!a || a.total !== total || a.left !== left || (end !== null && end !== a.seen)) {
    const at = end ?? Date.now() + left * 1000;
    if (!a || a.total !== total || Math.abs(at - a.end) > RING_RESYNC_MS) {
      a = { end: at, total, gone: total - left, key: (a?.key ?? 0) + 1, left, seen: end };
    } else {
      a = { ...a, left, seen: end };
    }
    anchor.current = a;
  }
  const secs = Math.ceil(left);
  const low = left <= LOW_SECS;
  // each half of the drain is half the window: under Reduce Motion it steps once a second
  const drain = { "--ring-total": `${total}s`, "--ring-at": `${round3(-a.gone)}s`,
    "--ring-steps": Math.max(1, Math.round(total / 2)) } as CSSProperties;
  return (
    <span className={`timer-ring${thin ? " thin" : ""}${low ? " low" : ""}`} role="timer"
          aria-label={t("table.secondsLeft", { seconds: secs })}>
      <span key={a.key} className="timer-ring-band" style={drain} aria-hidden="true">
        <span className="timer-ring-half l"><span /></span>
        <span className="timer-ring-half r"><span /></span>
      </span>
      <span className="timer-ring-secs">{secs}</span>
    </span>
  );
}

const round3 = (v: number) => Math.round(v * 1000) / 1000 + 0;
