// A companion as a figure, and as the round portrait that stands for a
// person wherever a name is shown. The figure's poses are CSS animations of
// transform and opacity only (companion.css); under Reduce Motion each pose
// is a still.
import { useEffect, useId, useMemo } from "react";
import { prefersReducedMotion } from "../motion";
import { parseArt, renderArt, tractorMarkup, tractorPortraitUrl } from "./Tractor";
import { parseLook } from "./look";
import type { Colour, CompanionKind } from "./look";
import "./companion.css";

export type Pose = "idle" | "hop" | "cheer" | "sleep";

/** The whole companion in a `size`-pixel square. `hop` and `cheer` play once
 *  and then call `onPoseEnd`, so the owner returns it to `idle`. */
export function Companion({ kind = "tractor", colour, size, state = "idle", onPoseEnd }: {
  kind?: CompanionKind; colour: Colour; size: number; state?: Pose; onPoseEnd?: () => void;
}) {
  void kind;
  const id = useId().replace(/[^a-zA-Z0-9]/g, "");
  const sleeping = state === "sleep";
  const art = useMemo(() => renderArt(parseArt(tractorMarkup(colour, id, { eyes: sleeping ? "sleep" : "open", detail: size >= 64 }))),
    [colour, id, sleeping, size]);
  // a still pose plays no animation, so it ends at once
  useEffect(() => {
    if ((state === "hop" || state === "cheer") && prefersReducedMotion()) onPoseEnd?.();
  }, [state, onPoseEnd]);
  return (
    <svg className={`cmp cmp-${state}`} width={size} height={size} viewBox="0 0 400 400"
         aria-hidden="true" focusable="false"
         onAnimationEnd={(e) => {
           if ((state === "hop" || state === "cheer") && (e.target as Element).classList.contains("cmp-body")) onPoseEnd?.();
         }}>
      {art}
      {sleeping ? <text className="cmp-z" x="300" y="80" fontSize="54" fontWeight="700" fill="#e8ede8">z</text> : null}
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
  const { colour } = parseLook(look);
  return <img className="portrait" data-look={`tractor/${colour}`} src={tractorPortraitUrl(colour, size < 40)} width={size} height={size}
              alt="" aria-hidden="true" draggable={false} />;
}
