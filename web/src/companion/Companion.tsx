// A companion as a figure, and as the round portrait that stands for a
// person wherever a name is shown. The figure's poses are CSS animations of
// transform and opacity only (companion.css, and companion.store.css for the
// drawn characters and the Tractor's rider); under Reduce Motion each pose
// is drawn still, at its peak.
import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { prefersReducedMotion } from "../motion";
import { parseArt, renderArt } from "./Tractor";
import { DRAWINGS } from "./kinds";
import type { DrawnColour, DrawnKind } from "./kinds";
import { companionSize } from "./rig";
import type { CharPose, Team } from "./rig";
import { lookId, parseLook } from "./look";
import "./companion.css";
import "./companion.store.css";

export type Pose = CharPose;

/** The poses that play once and end. */
const ONCE: ReadonlySet<Pose> = new Set(["hop", "cheer", "react"]);
/** How long a still pose stands before it ends, under Reduce Motion. */
const STILL_MS = 1000;

/** The suit the Lucky Cat's card turns up on one play: a joker about one
 *  play in twelve, else one of the four suits. */
export const pickSuit = (r: number): string => (r < 1 / 12 ? "j" : "shcd"[Math.min(3, Math.floor(((r - 1 / 12) / (11 / 12)) * 4))]);

/** The whole companion in a `size`-pixel square. `hop`, `cheer` and `react`
 *  play once and then call `onPoseEnd`, so the owner returns it to `idle`.
 *  At the table, `team` stands it on its team's pad in its team's scarf, and
 *  `level` (the team's level index, 2 is 0) grows it from `size` toward
 *  `max`; a level gained pops it from its old size, unless `grow` is false
 *  (the table plays its own level-up move). `still` draws the pose at
 *  its peak with nothing moving; it is on by itself under Reduce Motion.
 *  `idle` says how idle and sleep move: `loop` (their own endless loops) or
 *  `rest` (still, so a page at rest draws no frames). */
export function Companion({ kind = "tractor", colour, size, state = "idle", team, level, max, still, idle = "loop", grow = true, onPoseEnd }: {
  kind?: DrawnKind; colour: DrawnColour; size: number; state?: Pose; team?: Team; level?: number; max?: number;
  still?: boolean; idle?: "loop" | "rest"; grow?: boolean; onPoseEnd?: () => void;
}) {
  const id = useId().replace(/[^a-zA-Z0-9]/g, "");
  const drawing = DRAWINGS[kind];
  const px = level === undefined ? size : companionSize(size, level, max ?? Number.POSITIVE_INFINITY);
  const calm = still ?? prefersReducedMotion();
  const detail = px >= 64;
  const art = useMemo(() => renderArt(parseArt(drawing.markup(colour, id, { pose: state, detail, still: calm, team }))),
    [drawing, colour, id, state, detail, calm, team]);

  // each play of the Lucky Cat's reaction turns up a card of its own
  const suit = useMemo(() => (kind === "cat" && state === "react" ? pickSuit(Math.random()) : undefined), [kind, state]);

  // a level gained grows the figure from the size it stood at
  const was = useRef(px);
  const [from, setFrom] = useState<number | null>(null);
  useLayoutEffect(() => {
    if (grow && px > was.current && !prefersReducedMotion()) setFrom(was.current / px);
    was.current = px;
  }, [px, grow]);

  // a still pose plays no animation, so it ends on a timer
  useEffect(() => {
    if (!ONCE.has(state) || !calm) return;
    const timer = window.setTimeout(() => onPoseEnd?.(), STILL_MS);
    return () => window.clearTimeout(timer);
  }, [state, calm, onPoseEnd]);

  const resting = !ONCE.has(state);
  const poseCls = calm && ONCE.has(state) ? "" : resting && idle === "rest" ? `cmp-${state} cmp-rest` : `cmp-${state}`;
  const cls = ["cmp", drawing.char ? "cmp-char" : "", `cmp-${kind}`, poseCls, calm ? "cmp-still" : "",
    team ? `cmp-${team}` : "", from !== null ? "cmp-grow" : ""].filter(Boolean).join(" ");
  const [zx, zy] = drawing.z;
  return (
    <svg className={cls} data-pose={state} width={px} height={px} viewBox="0 0 400 400" aria-hidden="true" focusable="false" data-suit={suit}
         style={from !== null ? { "--cmp-from": from.toFixed(3) } as CSSProperties : undefined}
         onAnimationEnd={(e) => {
           if (e.target === e.currentTarget && e.animationName === "cmp-grow") setFrom(null);
           else if (ONCE.has(state) && (e.target as Element).classList.contains("cmp-body")) onPoseEnd?.();
         }}>
      {art}
      {state === "sleep" ? <text className="cmp-z" x={zx} y={zy} fontSize="54" fontWeight="700" fill="#e8ede8">z</text> : null}
    </svg>
  );
}

/** A person's portrait: their look's companion on its ground, in a disc of
 *  `size` pixels. A bot has none; it keeps its initial (`initial`). */
export function Portrait({ look, size, bot = false, initial = "" }: {
  look: string | null | undefined; size: number; bot?: boolean; initial?: string;
}) {
  if (bot) {
    return (
      <span className="avatar portrait-bot" aria-hidden="true"
            style={{ width: size, height: size, fontSize: Math.round(size * 0.46) }}>
        {initial.slice(0, 1).toUpperCase() || "·"}
      </span>
    );
  }
  const shown = parseLook(look);
  return <img className="portrait" data-look={lookId(shown)} src={DRAWINGS[shown.kind].portraitUrl(shown.colour, size < 40)}
              width={size} height={size} alt="" aria-hidden="true" draggable={false} />;
}
