// The table's big play from `beats.ts` (the two-bounce jump), played once on
// the Collection's stage by its Big play chip, its jump fitted to the stage's
// own height. Under Reduce Motion it holds one still pose for `STILL_BEAT_MS`.
import { BIG, reachOfFrames } from "./beats";
import type { Pose } from "./Companion";
import { prefersReducedMotion } from "../motion";

export type StageBeat = "big";

/** How long a stage beat's still pose stands under Reduce Motion. */
export const STILL_BEAT_MS = 1000;

interface Step { frames: Keyframe[]; ms: number; easing: string; at: number }

/** Each beat's steps (each starting `at` ms in), the figure's own pose while
 *  it plays, and the pose it holds under Reduce Motion. */
export const STAGE_BEATS: Record<StageBeat, { steps: Step[]; pose: Pose; still: string }> = {
  big: { pose: "cheer", still: String(BIG.frames[2].transform), steps: [{ ...BIG, at: 0 }] },
};

/** How long `beat` plays, in ms: its last step's end, or its still pose's time. */
export function stageBeatMs(beat: StageBeat, still = prefersReducedMotion()): number {
  if (still) return STILL_BEAT_MS;
  return Math.max(...STAGE_BEATS[beat].steps.map((s) => s.at + s.ms));
}

/** `frames` with every rise (`translateY`) scaled by `k` and every growth
 *  (`scale` away from 1) by `g`. */
const lowered = (frames: readonly Keyframe[], k: number, g = 1): Keyframe[] => frames.map((f) => ({
  ...f, transform: String(f.transform ?? "")
    .replace(/translateY\((-?[\d.]+)%\)/, (_, y) => `translateY(${Number(y) * k}%)`)
    .replace(/scale\((-?[\d.]+)(?:,\s*(-?[\d.]+))?\)/, (_, x, y) => {
      const at = (v: number) => Math.round((1 + (v - 1) * g) * 1000) / 1000;
      return y === undefined ? `scale(${at(Number(x))})` : `scale(${at(Number(x))}, ${at(Number(y))})`;
    }),
}));
/** The fits tried, largest first, until a beat's apex stays inside the stage:
 *  the rise lowered first, then (a stage too short for even the standing
 *  growth) the growth too. */
const FITS: readonly (readonly [number, number])[] = [
  ...[1, 0.85, 0.7, 0.55, 0.4, 0.25, 0.1, 0].map((k) => [k, 1] as const),
  ...[0.75, 0.5, 0.25, 0].map((g) => [0, g] as const),
];

/** `beat`'s steps for a figure `px` wide with `up` px of stage above it: its
 *  jumps (and, where even that is not enough, its growth) lowered just
 *  enough that no frame reaches past the stage's top. */
export function fittedSteps(beat: StageBeat, px: number, up: number): Step[] {
  const steps = STAGE_BEATS[beat].steps;
  for (const [k, g] of FITS) {
    const tried = steps.map((s) => ({ ...s, frames: lowered(s.frames, k, g) }));
    if (tried.every((s) => reachOfFrames(s.frames, px).up <= up)) return tried;
  }
  return steps.map((s) => ({ ...s, frames: lowered(s.frames, 0, 0) }));
}

/** `beat`'s still pose (Reduce Motion) for the same stage: its rise lowered
 *  just as far as `fittedSteps` would lower its jumps. */
export function fittedStill(beat: StageBeat, px: number, up: number): string {
  const still = [{ transform: STAGE_BEATS[beat].still }];
  for (const [k, g] of FITS) {
    const tried = lowered(still, k, g);
    if (reachOfFrames(tried, px).up <= up) return String(tried[0].transform);
  }
  return String(lowered(still, 0, 0)[0].transform);
}

/** Play `beat` on `el` (the figure's move box, `px` wide, `up` px under the
 *  stage's top) once; `stop` ends it at once. Each step holds its last frame
 *  until the next starts, and the whole beat lets go when its last step ends. */
export function playStageBeat(el: HTMLElement | null, beat: StageBeat, room: { px: number; up: number }): { stop: () => void } {
  if (!el) return { stop: () => {} };
  if (prefersReducedMotion() || typeof el.animate !== "function") {
    // the still pose takes the same stage fit as the moving one
    const still = fittedStill(beat, room.px, room.up);
    const was = el.style.transform;
    el.style.transform = still;
    const t = window.setTimeout(() => { el.style.transform = was; }, STILL_BEAT_MS);
    return { stop: () => { window.clearTimeout(t); el.style.transform = was; } };
  }
  const steps = fittedSteps(beat, room.px, room.up);
  const running: Animation[] = [];
  const start = (s: Step) => { running.push(el.animate(s.frames, { duration: s.ms, easing: s.easing, fill: "forwards" })); };
  const stop = () => { timers.forEach((t) => window.clearTimeout(t)); running.forEach((a) => a.cancel()); running.length = 0; };
  // the first step starts at once; the rest at their times
  steps.filter((s) => s.at === 0).forEach(start);
  const timers = steps.filter((s) => s.at > 0).map((s) => window.setTimeout(() => start(s), s.at));
  timers.push(window.setTimeout(stop, stageBeatMs(beat, false)));
  return { stop };
}
