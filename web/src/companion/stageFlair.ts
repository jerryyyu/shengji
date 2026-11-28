// The Collection's stage shows a companion as the table will: it comes in
// its own way as its tile is tapped, a tap on the felt walks it there in
// its own gait, and at rest it takes the table's own moments in turn (a
// stroll, its habit, ready for a turn, a lean to watch, the droop of a big
// trick lost). A store character's material plays with each as at the
// table (its trail on the stroll, its cue at rest, its burst on Big play,
// its accent on its special, one piece falling as it droops, its shower on
// a round won), whole on every device, so the stage shows what the game
// has and what a store character adds with no words. Nothing moves under Reduce Motion, where a
// store character has three still pieces at its feet, or while the stage is
// off screen.
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { MouseEvent, RefObject } from "react";
import { prefersReducedMotion } from "../motion";
import { BIG, DROOPS, GROW, LOOK_BACK_MS, LOOK_MS, LUNGE_BACK, LUNGE_REACH, PERKS, RELAX, lookFrames, lungeFrames, reachOfFrames } from "./beats";
import type { Pose } from "./Companion";
import { DRAWINGS } from "./kinds";
import type { DrawnKind } from "./kinds";
import { ARRIVES, GAITS, LUNGERS, PLAIN_GAIT, QUIRKS, accentPieces, burstPieces, cuePieces, droopPiece, entrancePieces, fitted, gaitFrames, grow, materialOf, restPieces, showerPieces,
  trailPieces, walkAt } from "./flair";
import type { Beat } from "./beats";
import type { Gait, Stance } from "./flair";
import { useCue, useFlairLayer } from "./flairHooks";
import { FullTier } from "./flairLayer";

/** The stage's stroll is the table's: half a second a figure's width, 1.2 s at least for a tap, 3 s at most. */
const STROLL_MS_PER_FIGURE = 500;
const TAP_MS: readonly [number, number] = [1200, 3000];
const TRAIL_STEP_MS = 520;
/** What a figure at rest on the stage does by itself, in turn: the table's own moments, so the stage shows what
 *  the game has. A stroll (its gait, and a store character's trail), its habit, getting ready as a turn
 *  arrives, a lean to watch a card, the droop of a big trick lost, and for a store character a round won (its
 *  special under its shower). */
export const STAGE_MOMENTS = ["stroll", "habit", "ready", "stroll", "watch", "loss", "win"] as const;
/** The least time between two of them, and how soon after it is selected the first comes. */
export const STAGE_MOMENT_MS = 4000;
const FIRST_MOMENT_MS = 2200;
/** How long it stands ready, and leans to watch, before it settles. */
const HELD_MS = 1100;
/** The longest a way in and its entrance run. */
const ENTRANCE_MS = 1400;
/** How long it stands where a tap or a stroll left it before it walks back to the stage's middle. */
export const STAGE_RETURN_MS = 3000;
const OWNER = "stage";
/** The stage paints a store character whole on every device (`FullTier`). */
const WHOLE = new FullTier();
/** The least a piece's flight is on the stage, however close the figure stands to the felt's edge. */
const LEAST_FLY = 20;

export interface StageRefs {
  felt: RefObject<HTMLDivElement | null>; walk: RefObject<HTMLSpanElement | null>; face: RefObject<HTMLSpanElement | null>;
  move: RefObject<HTMLSpanElement | null>; back: RefObject<HTMLCanvasElement | null>; front: RefObject<HTMLCanvasElement | null>;
}

/** The stage's walks and pieces for `kind` drawn `size` px wide, in `pose`
 *  (`poseKey` tells one play of a pose from the next), `paused` while off
 *  screen; `arrives` counts the taps that selected it (0 for the page's
 *  first figure, which is drawn settled): each plays its way in once.
 *  `special` plays the drawing's special (a round won, in the stage's own turn of moments). `onFelt` is the felt's tap; `big()` is Big play's burst;
 *  `material` says whether its two canvases are drawn. */
export function useStageFlair(kind: string, colour: string, size: number, pose: Pose, poseKey: number, paused: boolean, refs: StageRefs, arrives: number,
  special: () => void = () => {}) {
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
  const layer = useFlairLayer(material !== null, refs.back, refs.front, box, false, false, WHOLE);
  // where it stands, in px from the stage's middle, the way it faces, and the walk in flight
  const at = useRef(0);
  const dir = useRef<1 | -1>(1);
  const flight = useRef<{ from: number; to: number; t0: number; ms: number; anims: Animation[]; timers: number[] } | null>(null);
  const dropped = useRef(0);
  // the taps whose way in has been played, and when the last one started
  const entered = useRef(0);
  const enteredAt = useRef(-Infinity);
  const taps = useRef(arrives);
  taps.current = arrives;
  // when it last came to a stand, for its walk back to the middle
  const stood = useRef(0);
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
    // a flight is as long as the felt beside the figure has room for, so no piece leaves the stage: a burst
    // reaches 0.6 of the figure and 1.055 flights from its middle, a shower half the figure and the rest in flights
    const room = f.width / 2 - Math.abs(dx);
    const fly = Math.max(LEAST_FLY, 0.97 * Math.min(size, (room - size * 0.6) / 1.055, (room - size * 0.5) / (0.8 + (24 * grow(size)) / size)));
    return { x: f.width / 2 + dx, y: walk.getBoundingClientRect().bottom - f.top, px: size, dir: dir.current, colour, gold: false, fly };
  };
  const stop = () => {
    const f = flight.current;
    if (!f) return;
    for (const a of f.anims) a.cancel();
    for (const t of f.timers) window.clearTimeout(t);
    flight.current = null;
  };
  /** End a walk in flight where the figure is drawn now, so what follows starts from there, not from the walk's goal. */
  const halt = (): number => {
    const x = Math.round(here() * 10) / 10;
    stop();
    at.current = x;
    stood.current = performance.now();
    if (refs.walk.current) refs.walk.current.style.transform = `translate(${x}px, 0px)`;
    return x;
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
          const n = k === drops || k % 2 ? 3 : 2;
          layer.spawn(OWNER, true, "trail", fitted(trailPieces(material, { ...base, x: base.x + x, dir: d }, { x: d, y: 0 }, n, dropped.current), 0, felt.clientWidth));
          dropped.current += n;
        }, (k * ms) / drops));
      }
    }
    const mine = { from, to: goal, t0: performance.now(), ms, anims, timers };
    flight.current = mine;
    void anims[0].finished.then(() => { if (flight.current === mine) { flight.current = null; stood.current = performance.now(); } }, () => {});
  };
  useEffect(() => stop, []);
  // a stage that leaves view rests at once: the walk ends where it is drawn, the pieces still to drop are
  // forgotten and what is in the air is taken off, so nothing is painted out of sight
  useEffect(() => {
    if (!paused) return;
    halt();
    settle();
    layer?.clear();
    // an entrance cut short as the stage left view (a tile tapped further down the page is out of view before
    // the page says so) is owed again, to be played once the stage is seen
    if (performance.now() - enteredAt.current < ENTRANCE_MS) entered.current = Math.max(0, entered.current - 1);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paused]);

  const emit = (tag: "cue" | "burst" | "entrance" | "shower", make: (s: Stance) => ReturnType<typeof cuePieces>) => {
    const s = stance(here());
    // whatever the flight, no piece's path leaves the felt: the figure may stand by its edge
    if (material && layer && s && !paused) layer.spawn(OWNER, true, tag, fitted(make(s), 0, refs.felt.current?.clientWidth ?? Infinity));
  };
  // its way in as it is selected, and a store character's entrance with it. A tap taken while the stage is out
  // of view (a tile further down the page, before the page scrolls back up) is owed until it is seen, then
  // played once
  useEffect(() => {
    if (arrives <= entered.current || (material && !layer) || paused) return;
    entered.current = arrives;
    enteredAt.current = performance.now();
    const el = refs.move.current;
    if (!el || typeof el.animate !== "function" || still()) return;
    // the fullest way in the stage has room over the figure for, as the table picks one; a chip or a tap on
    // the figure while it plays ends it (`yield`)
    const felt = refs.felt.current;
    const up = felt ? Math.max(0, el.getBoundingClientRect().top - felt.getBoundingClientRect().top) : 0;
    const ways = (ARRIVES as Record<string, readonly Beat[] | undefined>)[kind];
    const beat = ways?.find((b) => reachOfFrames(b.frames, size).up <= up) ?? ways?.[ways.length - 1];
    const a = beat ? el.animate(beat.frames, { duration: beat.ms, easing: beat.easing }) : null;
    if (a) acts.current.anims.push(a);
    if (material) emit("entrance", (s) => entrancePieces(material, s, 8));
    return () => a?.cancel();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layer, arrives, paused]);
  // at rest: its cue on its own clock, and a stroll by itself now and then, so the trail shows
  const calm = useRef(false);
  calm.current = pose === "idle" && !paused && flight.current === null;
  useCue(material !== null, calm, () => { if (material) emit("cue", (s) => cuePieces(material, s)); });
  // at rest it takes the table's moments in turn, each from the table's own beats
  const turn = useRef(0);
  const lastMoment = useRef(0);
  const acts = useRef<{ anims: Animation[]; timers: number[] }>({ anims: [], timers: [] });
  const settle = () => {
    for (const a of acts.current.anims) a.cancel();
    for (const id of acts.current.timers) window.clearTimeout(id);
    acts.current = { anims: [], timers: [] };
  };
  useEffect(() => settle, []);
  const moment = () => {
    const what = STAGE_MOMENTS[turn.current++ % STAGE_MOMENTS.length];
    if (what === "stroll") { walkTo(at.current > 0 ? -size * 1.1 : size * 1.1, false); return; }
    const move = refs.move.current, face = refs.face.current, felt = refs.felt.current;
    if (!move || !face || !felt || typeof move.animate !== "function" || still()) return;
    settle();
    const play = (el: HTMLElement, b: { frames: Keyframe[]; ms: number; easing: string }, hold = false) => {
      const a = el.animate(b.frames, { duration: b.ms, easing: b.easing, ...(hold ? { fill: "forwards" as const } : {}) });
      acts.current.anims.push(a);
      return a;
    };
    const after = (ms: number, fn: () => void) => { acts.current.timers.push(window.setTimeout(fn, ms)); };
    if (what === "habit") {
      const own = (QUIRKS as Record<string, Beat | undefined>)[kind];
      if (own) play(move, own);
    } else if (what === "ready") {
      // the highest jump the stage has room over the figure for; then it stands larger a moment and settles
      const up = Math.max(0, move.getBoundingClientRect().top - felt.getBoundingClientRect().top);
      const perk = PERKS.find((b) => reachOfFrames(b.frames, size).up <= up) ?? GROW;
      const held = play(move, perk, true);
      after(perk.ms + HELD_MS, () => { held.cancel(); play(move, RELAX); });
    } else if (what === "watch") {
      const d = dir.current, straight = { dir: d, lean: 0, up: false }, lean = { dir: d, lean: 8, up: false };
      const held = play(face, { frames: lookFrames(straight, lean, true), ms: LOOK_MS, easing: "ease-out" }, true);
      after(LOOK_MS + HELD_MS, () => { held.cancel(); play(face, { frames: lookFrames(lean, straight, false), ms: LOOK_BACK_MS, easing: "ease-out" }); });
    } else if (what === "loss") {
      play(move, DROOPS[0]);
      if (material) emit("burst", (s) => droopPiece(material, s));
    } else if (material) {
      special();
      emit("shower", (s) => showerPieces(material, s, 6));
    } else moment();
  };
  const next = useRef(moment);
  next.current = moment;
  const back = useRef(walkTo);
  back.current = walkTo;
  useEffect(() => {
    // the first comes soon after it is selected; one due mid-move waits for the figure to be at rest
    lastMoment.current = performance.now() - STAGE_MOMENT_MS + FIRST_MOMENT_MS;
    const timer = window.setInterval(() => {
      const now = performance.now();
      const last = lastMoment.current;
      if (!calm.current) return;
      // off the middle (a tap walked it there, or its own stroll): after a moment it walks back, at the same pace,
      // and its moments go on from there
      if (at.current !== 0 && now - stood.current >= STAGE_RETURN_MS) { lastMoment.current = now; back.current(0, false); return; }
      if (at.current !== 0 || now - last < STAGE_MOMENT_MS) return;
      lastMoment.current = now;
      next.current();
    }, 400);
    return () => window.clearInterval(timer);
  }, [kind, size]);
  // its special: the charge is the stage's as it is the table's, and a store character's accent rides on it
  useEffect(() => {
    if (pose !== "react" || still()) return;
    const felt = refs.felt.current, walk = refs.walk.current;
    const from = halt();
    let lunge: Animation | null = null;
    let reach = 0;
    if (LUNGERS.has(kind) && felt && walk && typeof walk.animate === "function") {
      const room = felt.clientWidth / 2 - size * 0.6 - dir.current * from;
      reach = (LUNGE_REACH.find((r) => r * size <= room) ?? 0) * size;
      if (reach > 0) lunge = walk.animate(lungeFrames({ x: from, y: 0 }, dir.current, { reach, back: LUNGE_BACK * size }), { duration: DRAWINGS[kind as DrawnKind].reactMs });
    }
    // the accent fans ahead of the figure: its flight is the felt left ahead of where it starts
    const ahead = (s: Stance) => {
      const x = s.x + s.dir * ((material!.accent.at[0] - 0.5) * s.px + reach);
      return { ...s, fly: Math.max(LEAST_FLY, Math.min(size, ((s.dir > 0 ? (felt?.clientWidth ?? 0) - x : x) - s.px * 0.12) / 1.05)) };
    };
    if (material) for (const t of material.accent.times) emit("burst", (s) => accentPieces(material, ahead(s), reach, t));
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
    /** A chip or a tap on the figure is the player's: a moment in flight ends at once, so the move the player
     *  asked for starts from the figure at rest, the next moment waits its full time, and a way in still owed
     *  (the stage was out of view) is let go rather than played over what the player asked for. */
    yield: () => { settle(); lastMoment.current = performance.now(); entered.current = Math.max(entered.current, taps.current); },
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
