import { RING_SECS } from "../useMoveClock";

/** The last ten seconds of your decision: a closing ring with the seconds
 *  inside. Nothing before that. A shorter window (the declare window) passes
 *  its own `total`, so the ring starts full. */
export function MoveRing({ left, total = RING_SECS }: { left: number | null; total?: number }) {
  if (left === null || left > total) return null;
  const secs = Math.ceil(left);
  const deg = Math.round((left / total) * 360);
  return (
    <span className="move-ring" role="timer" aria-label={`${secs} seconds left`}
          style={{ ["--ring-deg" as string]: `${deg}deg` }}>
      <span className="move-ring-secs">{secs}</span>
    </span>
  );
}
