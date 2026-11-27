// The table's moves from `beats.ts`, played once on the Collection's stage
// by its move chips: Ready (the jump as your turn arrives, its bobs, back to
// size), Watch (the lean toward a card played, held, then straight again) and
// Big play (the two-bounce jump). The stage has the room the table checks
// for, so each plays its largest form. Under Reduce Motion each holds one
// still pose for `STILL_BEAT_MS`.
import { BIG, LOOK_BACK_MS, LOOK_MS, LEANS, PERKS, READY_BOB, READY_BOBS, READY_BOB_GAP_MS, READY_HELD, RELAX,
  facingCss, lookFrames } from "./beats";
import type { Facing } from "./beats";
import type { Pose } from "./Companion";
import { prefersReducedMotion } from "../motion";

export type StageBeat = "ready" | "watch" | "big";

/** How long a stage beat's still pose stands under Reduce Motion. */
export const STILL_BEAT_MS = 1000;
/** How long Watch holds its lean before it straightens. */
export const WATCH_HOLD_MS = 900;

interface Step { frames: Keyframe[]; ms: number; easing: string; at: number }

const STRAIGHT: Facing = { dir: 1, lean: 0, up: false };
const LEANING: Facing = { dir: 1, lean: LEANS[0], up: false };

/** Each beat's steps (each starting `at` ms in), the figure's own pose while
 *  it plays, and the pose it holds under Reduce Motion. */
export const STAGE_BEATS: Record<StageBeat, { steps: Step[]; pose: Pose; still: string }> = {
  ready: {
    pose: "idle", still: READY_HELD,
    steps: [
      { ...PERKS[0], at: 0 },
      ...Array.from({ length: READY_BOBS }, (_, i) => ({ ...READY_BOB, at: PERKS[0].ms + i * READY_BOB_GAP_MS })),
      { ...RELAX, at: PERKS[0].ms + READY_BOBS * READY_BOB_GAP_MS },
    ],
  },
  watch: {
    pose: "idle", still: facingCss(LEANING),
    steps: [
      { frames: lookFrames(STRAIGHT, LEANING, true), ms: LOOK_MS, easing: "ease-out", at: 0 },
      { frames: [{ transform: facingCss(LEANING) }, { transform: facingCss(LEANING) }], ms: WATCH_HOLD_MS, easing: "linear", at: LOOK_MS },
      { frames: lookFrames(LEANING, STRAIGHT, false), ms: LOOK_BACK_MS, easing: "ease-in", at: LOOK_MS + WATCH_HOLD_MS },
    ],
  },
  big: { pose: "cheer", still: String(BIG.frames[2].transform), steps: [{ ...BIG, at: 0 }] },
};

/** How long `beat` plays, in ms: its last step's end, or its still pose's time. */
export function stageBeatMs(beat: StageBeat, still = prefersReducedMotion()): number {
  if (still) return STILL_BEAT_MS;
  return Math.max(...STAGE_BEATS[beat].steps.map((s) => s.at + s.ms));
}

/** Play `beat` on `el` (the figure's move box) once; `stop` ends it at once. */
export function playStageBeat(el: HTMLElement | null, beat: StageBeat): { stop: () => void } {
  if (!el) return { stop: () => {} };
  const { steps, still } = STAGE_BEATS[beat];
  if (prefersReducedMotion() || typeof el.animate !== "function") {
    const was = el.style.transform;
    el.style.transform = still;
    const t = window.setTimeout(() => { el.style.transform = was; }, STILL_BEAT_MS);
    return { stop: () => { window.clearTimeout(t); el.style.transform = was; } };
  }
  const running: Animation[] = [];
  const start = (s: Step) => { running.push(el.animate(s.frames, { duration: s.ms, easing: s.easing })); };
  // the first step starts at once; the rest at their times
  steps.filter((s) => s.at === 0).forEach(start);
  const timers = steps.filter((s) => s.at > 0).map((s) => window.setTimeout(() => start(s), s.at));
  return { stop: () => { timers.forEach((t) => window.clearTimeout(t)); running.forEach((a) => a.cancel()); } };
}
