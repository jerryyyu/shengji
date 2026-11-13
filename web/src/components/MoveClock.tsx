import { RING_SECS } from "../useMoveClock";

/** The last ten seconds of your decision: a closing ring with the seconds
 *  inside. Nothing before that. */
export function MoveRing({ left }: { left: number | null }) {
  if (left === null || left > RING_SECS) return null;
  const secs = Math.ceil(left);
  const deg = Math.round((left / RING_SECS) * 360);
  return (
    <span className="move-ring" role="timer" aria-label={`${secs} seconds left`}
          style={{ ["--ring-deg" as string]: `${deg}deg` }}>
      <span className="move-ring-secs">{secs}</span>
    </span>
  );
}
