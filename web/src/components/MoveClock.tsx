import { LOW_SECS } from "../useMoveClock";

/** The one timer: a ring that drains from full over the whole window, with
 *  the seconds left in its centre. It turns red for the last LOW_SECS.
 *  `thin` is the quieter ring on someone else's seat pill. A left above
 *  `total` (a window the server extended) draws a full ring. */
export function TimerRing({ left, total, thin = false }: { left: number | null; total: number; thin?: boolean }) {
  if (left === null) return null;
  const secs = Math.ceil(left);
  const frac = total > 0 ? Math.min(1, Math.max(0, left / total)) : 0;
  const low = left <= LOW_SECS;
  return (
    <span className={`timer-ring${thin ? " thin" : ""}${low ? " low" : ""}`} role="timer"
          aria-label={`${secs} seconds left`}
          style={{ ["--ring-deg" as string]: `${Math.round(frac * 360)}deg` }}>
      <span className="timer-ring-secs">{secs}</span>
    </span>
  );
}
