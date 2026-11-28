// The Collection's stage shows a companion as the table will: it comes in
// its own way as it is selected, a tap on the felt walks it there in its
// own gait, and a store character's material plays live (its trail on a
// stroll it takes by itself every few seconds, its cue at rest, its burst
// on Big play, its accent on its special), so the stage shows what a store
// character adds with no words. Nothing moves under Reduce Motion, where a
// store character has three still pieces at its feet, or while the stage is
// off screen.
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { MouseEvent, RefObject } from "react";
import { prefersReducedMotion } from "../motion";
import { BIG, lungeFrames, LUNGE_BACK, LUNGE_REACH } from "./beats";
import type { Pose } from "./Companion";
import { DRAWINGS } from "./kinds";
import type { DrawnKind } from "./kinds";
import { ARRIVES, GAITS, LUNGERS, PLAIN_GAIT, accentPieces, burstPieces, cuePieces, entrancePieces, gaitFrames, materialOf, restPieces, trailPieces, walkAt } from "./flair";
import type { Beat } from "./beats";
import type { Gait, Stance } from "./flair";
import { useCue, useFlairLayer } from "./flairHooks";

/** The stage's stroll is the table's: half a second a figure's width, 1.2 s at least for a tap, 3 s at most. */
const STROLL_MS_PER_FIGURE = 500;
const TAP_MS: readonly [number, number] = [1200, 3000];
const TRAIL_STEP_MS = 520;
/** How often a store character strolls across the stage by itself. */
export const STAGE_STROLL_MS = 6500;
/** How soon after it is selected the first stroll comes. */
const FIRST_STROLL_MS = 2200;
const OWNER = "stage";

export interface StageRefs {
  felt: RefObject<HTMLDivElement | null>; walk: RefObject<HTMLSpanElement | null>; face: RefObject<HTMLSpanElement | null>;
  move: RefObject<HTMLSpanElement | null>; back: RefObject<HTMLCanvasElement | null>; front: RefObject<HTMLCanvasElement | null>;
}

/** The stage's walks and pieces for `kind` drawn `size` px wide, in `pose`
 *  (`poseKey` tells one play of a pose from the next), `paused` while off
 *  screen. `onFelt` is the felt's tap; `big()` is Big play's burst;
 *  `material` says whether its two canvases are drawn. */
export function useStageFlair(kind: string, colour: string, size: number, pose: Pose, poseKey: number, paused: boolean, refs: StageRefs) {
  const material = materialOf(kind);
  const [box, setBox] = useState<{ w: number; h: number } | undefined>(undefined);
  useLayoutEffect(() => {
    const el = refs.felt.current;
    if (!el || !material) return;
    const read = () => setBox({ w: el.clientWidth, h: el.clientHeight });
    read();
    window.addEventListener("resize", read);
    return () => window.removeEventListener("resize", read);
  }, [material, refs.felt, size]);
  const layer = useFlairLayer(material !== null, refs.back, refs.front, box, false, false);
  // where it stands, in px from the stage's middle, the way it faces, and the walk in flight
  const at = useRef(0);
  const dir = useRef<1 | -1>(1);
  const flight = useRef<{ from: number; to: number; t0: number; ms: number; anims: Animation[]; timers: number[] } | null>(null);
  const still = () => prefersReducedMotion() || document.visibilityState === "hidden";
  const here = (): number => {
    const f = flight.current;
    return f ? walkAt({ x: f.from, y: 0 }, { x: f.to, y: 0 }, Math.min(1, (performance.now() - f.t0) / f.ms)).x : at.current;
  };
  /** The figure as a moment sees it, standing `dx` from the stage's middle. */
  const stance = (dx: number): Stance | null => {
    const felt = refs.felt.current, walk = refs.walk.current;
    if (!felt || !walk) return null;
    const f = felt.getBoundingClientRect();
    return { x: f.width / 2 + dx, y: walk.getBoundingClientRect().bottom - f.top, px: size, dir: dir.current, colour, gold: false };
  };
  const stop = () => {
    const f = flight.current;
    if (!f) return;
    for (const a of f.anims) a.cancel();
    for (const t of f.timers) window.clearTimeout(t);
    flight.current = null;
  };
  const walkTo = (to: number, tap: boolean) => {
    const walk = refs.walk.current, face = refs.face.current, felt = refs.felt.current;
    if (!walk || !face || !felt || typeof walk.animate !== "function" || still()) return;
    const from = here();
    stop();
    const half = Math.max(0, felt.clientWidth / 2 - size * 0.6);
    const goal = Math.round(Math.max(-half, Math.min(half, to)));
    const dist = Math.abs(goal - from);
    at.current = goal;
    walk.style.transform = `translate(${goal}px, 0px)`;
    if (dist < 1) return;
    const ms = Math.max(tap ? TAP_MS[0] : 0, Math.min(TAP_MS[1], (dist / size) * STROLL_MS_PER_FIGURE));
    const d = goal < from ? -1 : 1;
    dir.current = d;
    face.style.transform = `scaleX(${d})`;
    const gait = (GAITS as Record<string, Gait | undefined>)[kind] ?? PLAIN_GAIT;
    const hops = Math.max(1, Math.round(ms / gait.step));
    const anims = [walk.animate([{ transform: `translate(${from}px, 0px)` }, { transform: `translate(${goal}px, 0px)` }], { duration: ms, easing: "ease-in-out" }),
      face.animate(gaitFrames(gait, d), { duration: ms / hops, iterations: hops })];
    const timers: number[] = [];
    const base = stance(0);
    if (material && layer && base) {
      const drops = Math.max(1, Math.round(ms / TRAIL_STEP_MS));
      for (let k = 1; k <= drops; k++) {
        timers.push(window.setTimeout(() => {
          const x = walkAt({ x: from, y: 0 }, { x: goal, y: 0 }, k / drops).x;
          layer.spawn(OWNER, true, "trail", trailPieces(material, { ...base, x: base.x + x, dir: d }, { x: d, y: 0 }, k === drops || k % 2 ? 3 : 2, k));
        }, (k * ms) / drops));
      }
    }
    const mine = { from, to: goal, t0: performance.now(), ms, anims, timers };
    flight.current = mine;
    void anims[0].finished.then(() => { if (flight.current === mine) flight.current = null; }, () => {});
  };
  useEffect(() => stop, []);

  const emit = (tag: "cue" | "burst" | "entrance", make: (s: Stance) => ReturnType<typeof cuePieces>) => {
    const s = stance(here());
    if (material && layer && s && !paused) layer.spawn(OWNER, true, tag, make(s));
  };
  // its way in as it is selected, and a store character's entrance with it
  const entered = useRef(false);
  useEffect(() => {
    if (entered.current || (material && !layer)) return;
    entered.current = true;
    const el = refs.move.current;
    if (!el || typeof el.animate !== "function" || still()) return;
    const beat: Beat | undefined = (ARRIVES as Record<string, readonly Beat[] | undefined>)[kind]?.[0];
    const a = beat ? el.animate(beat.frames, { duration: beat.ms, easing: beat.easing }) : null;
    if (material) emit("entrance", (s) => entrancePieces(material, s, 8));
    return () => a?.cancel();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layer]);
  // at rest: its cue on its own clock, and a stroll by itself now and then, so the trail shows
  const calm = useRef(false);
  calm.current = pose === "idle" && !paused && flight.current === null;
  useCue(material !== null, calm, () => { if (material) emit("cue", (s) => cuePieces(material, s)); });
  const stroll = useRef(walkTo);
  stroll.current = walkTo;
  useEffect(() => {
    if (!material) return;
    // the first comes soon after it is selected; a stroll due mid-move waits for the figure to be at rest
    let last = performance.now() - STAGE_STROLL_MS + FIRST_STROLL_MS;
    const timer = window.setInterval(() => {
      if (!calm.current || performance.now() - last < STAGE_STROLL_MS) return;
      last = performance.now();
      stroll.current(at.current > 0 ? -size * 1.1 : size * 1.1, false);
    }, 400);
    return () => window.clearInterval(timer);
  }, [material, size]);
  // its special: the charge is the stage's as it is the table's, and a store character's accent rides on it
  useEffect(() => {
    if (pose !== "react" || still()) return;
    const felt = refs.felt.current, walk = refs.walk.current;
    const from = here();
    stop();
    let lunge: Animation | null = null;
    let reach = 0;
    if (LUNGERS.has(kind) && felt && walk && typeof walk.animate === "function") {
      const room = felt.clientWidth / 2 - size * 0.6 - dir.current * from;
      reach = (LUNGE_REACH.find((r) => r * size <= room) ?? 0) * size;
      if (reach > 0) lunge = walk.animate(lungeFrames({ x: from, y: 0 }, dir.current, { reach, back: LUNGE_BACK * size }), { duration: DRAWINGS[kind as DrawnKind].reactMs });
    }
    if (material) for (const t of material.accent.times) emit("burst", (s) => accentPieces(material, s, reach, t));
    return () => lunge?.cancel();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pose, poseKey]);
  // under Reduce Motion a store character's material is three still pieces at its feet
  useEffect(() => {
    const s = stance(at.current);
    if (!material || !layer || !s || !prefersReducedMotion()) return;
    layer.rest(OWNER, restPieces(material, s));
    return () => layer.rest(OWNER, null);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [material, layer, box, colour, size]);

  return {
    material: material !== null,
    /** A tap on the felt (not on the figure, whose tap is its special) walks it there. */
    onFelt: (e: MouseEvent<HTMLDivElement>) => {
      const felt = refs.felt.current;
      if (!felt || (e.target as Element).closest(".coll-figure")) return;
      const f = felt.getBoundingClientRect();
      walkTo(e.clientX - f.left - f.width / 2, true);
    },
    /** Big play: a store character's burst as the jump leaves the ground. */
    big: () => { if (material && !still()) emit("burst", (s) => burstPieces(material, s, 7, BIG.ms * 0.2)); },
  };
}
