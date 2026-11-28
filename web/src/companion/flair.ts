// A companion's character and, for a store character, its material.
// Character is every companion's: its own gait at the one walking pace, a
// habit at rest and a way in. Each is a transform of a box the figure
// already has, in the beats' grammar, so the table fits it to the room.
// Material is a store character's only: pieces of its own (petals, bamboo
// leaves), one mark and one cue, painted on the table's two canvases
// (`flairLayer.ts`). Here are the tables and the pure builders that turn a
// moment into pieces; nothing here touches the page.
import type { Beat } from "./beats";
import type { CompanionKind } from "./look";
import type { Spot } from "./seatZones";

const f = (y: number, r: number, sx: number, sy: number, offset?: number, opacity?: number): Keyframe =>
  ({ transform: `translateY(${y}%) rotate(${r}deg) scale(${sx}, ${sy})`, ...(offset === undefined ? {} : { offset }), ...(opacity === undefined ? {} : { opacity }) });
const SPRING = "cubic-bezier(0.3, 0.7, 0.3, 1)";

/** One step of a gait on the face box: rise (% of the figure), turn (deg),
 *  squash, and where in the step it falls. */
type Step = readonly [y: number, r: number, sx: number, sy: number, offset?: number];
export interface Gait { step: number; steps: readonly Step[] }
/** The gait every figure had, and a quick step aside still has. */
export const PLAIN_GAIT: Gait = { step: 520, steps: [[0, 0, 1, 1], [-12, 0, 1, 1, 0.45], [0, 0, 1, 1]] };
/** Each companion's own gait. The pace is the walk's, never the gait's: a
 *  whole number of steps is fitted to the walk's time. No step rises past
 *  the headroom a standing figure keeps (`LIFT`). */
export const GAITS: Record<CompanionKind, Gait> = {
  tractor: { step: 520, steps: [[0, 0, 1, 1], [-2, -3, 1, 1, 0.5], [0, 0, 1, 1]] },
  bun: { step: 520, steps: [[0, 0, 1.08, 0.9], [-10, 0, 0.95, 1.07, 0.45], [0, 0, 1.08, 0.9]] },
  chick: { step: 260, steps: [[0, 0, 1, 1], [-8, 3, 1, 1, 0.45], [0, 0, 1, 1]] },
  sparrow: { step: 520, steps: [[0, 0, 1, 1], [-15, -5, 0.97, 1.04, 0.45], [0, 0, 1.03, 0.96, 0.9], [0, 0, 1, 1]] },
  lamb: { step: 520, steps: [[0, 0, 1, 1], [-14, 4, 0.98, 1.03, 0.45], [0, 0, 1.03, 0.97, 0.9], [0, 0, 1, 1]] },
  panda: { step: 1040, steps: [[0, 0, 1, 1], [-4, -5, 1, 1, 0.25], [0, 0, 1, 1, 0.5], [-4, 5, 1, 1, 0.75], [0, 0, 1, 1]] },
};
/** A gait's keyframes for the face box, facing `dir`. */
export const gaitFrames = (gait: Gait, dir: 1 | -1): Keyframe[] => gait.steps.map(([y, r, sx, sy, offset]) =>
  ({ transform: `scaleX(${dir}) translateY(${y}%) rotate(${r}deg) scale(${sx}, ${sy})`, ...(offset === undefined ? {} : { offset }) }));

/** Each companion's habit at rest, one of its fidgets: an engine rumble, a
 *  deep breath, a peck, a head tilt, a wool shake, a slow rock. */
export const QUIRKS: Record<CompanionKind, Beat> = {
  tractor: { name: "rumble", ms: 700, easing: "linear", frames: [f(0, 0, 1, 1), f(-1.5, -1.5, 1.01, 0.99, 0.15), f(0, 1.5, 1, 1, 0.3), f(-1.5, -1, 1.01, 0.99, 0.45), f(0, 1, 1, 1, 0.6), f(-1, 0, 1, 1, 0.8), f(0, 0, 1, 1)] },
  bun: { name: "breath", ms: 1100, easing: "ease-in-out", frames: [f(0, 0, 1, 1), f(0, 0, 1.1, 0.88, 0.3), f(0, 0, 0.96, 1.06, 0.6), f(0, 0, 1.03, 0.98, 0.8), f(0, 0, 1, 1)] },
  chick: { name: "peck", ms: 900, easing: "ease-in-out", frames: [f(0, 0, 1, 1), f(0, 9, 1, 1, 0.2), f(0, 2, 1, 1, 0.4), f(0, 9, 1, 1, 0.6), f(0, 0, 1, 1)] },
  sparrow: { name: "tilt", ms: 1300, easing: "ease-in-out", frames: [f(0, 0, 1, 1), f(0, -7, 1, 1, 0.2), f(0, -7, 1, 1, 0.45), f(0, 6, 1, 1, 0.65), f(0, 6, 1, 1, 0.85), f(0, 0, 1, 1)] },
  lamb: { name: "shake", ms: 620, easing: "linear", frames: [f(0, 0, 1, 1), f(0, -5, 1.03, 1.02, 0.15), f(0, 5, 1.03, 1.02, 0.35), f(0, -4, 1.02, 1.01, 0.55), f(0, 3, 1.01, 1, 0.75), f(0, 0, 1, 1)] },
  panda: { name: "rock", ms: 1600, easing: "ease-in-out", frames: [f(0, 0, 1, 1), f(0, -6, 1, 1, 0.25), f(0, 6, 1, 1, 0.6), f(0, -3, 1, 1, 0.85), f(0, 0, 1, 1)] },
};

/** Each companion's way in, the fullest first: the table plays the first
 *  that stays clear where the figure stands. Each fades up as it comes. */
export const ARRIVES: Record<CompanionKind, readonly Beat[]> = {
  tractor: [{ name: "rev", ms: 700, easing: "ease-out", frames: [f(0, 0, 0.6, 0.6, 0, 0), f(0, -4, 1.06, 0.95, 0.5, 1), f(0, 3, 0.98, 1.02, 0.75), f(0, 0, 1, 1)] }],
  bun: [-60, -30, 0].map((y): Beat => ({ name: `plop${-y}`, ms: 620, easing: "ease-in", frames: [f(y, 0, 0.95, 1.05, 0, 0), f(0, 0, 1.16, 0.8, 0.6, 1), f(y / 10, 0, 0.97, 1.05, 0.8), f(0, 0, 1, 1)] })),
  chick: [-12, 0].map((y): Beat => ({ name: `hatch${-y}`, ms: 520, easing: SPRING, frames: [f(0, 0, 1, 0.1, 0, 0), f(y, 0, 0.95, 1.1, 0.6, 1), f(0, 0, 1, 1)] })),
  sparrow: [[-70, -14], [-35, -8], [0, 0]].map(([y, r]): Beat => ({ name: `swoop${-y}`, ms: 700, easing: "ease-out", frames: [f(y, r, 0.9, 0.9, 0, 0), f(0, -r / 3, 1, 1, 0.75, 1), f(0, 0, 1, 1)] })),
  lamb: [[-26, -13], [-14, -7], [0, 0]].map(([a, b]): Beat => ({ name: `prance${-a}`, ms: 800, easing: "linear", frames: [f(0, 0, 0.8, 0.8, 0, 0), f(a, 0, 1, 1, 0.3, 1), f(0, 0, 1.04, 0.96, 0.55), f(b, 0, 1, 1, 0.78), f(0, 0, 1, 1)] })),
  panda: [{ name: "waddle", ms: 900, easing: "ease-out", frames: [f(0, -5, 0.9, 0.9, 0, 0), f(0, 5, 1, 1, 0.3, 1), f(0, -4, 1, 1, 0.62), f(0, 0, 1, 1)] }],
};

// ---- material: a store character's own ----

/** What a piece is drawn as. */
export type Shape = "petal" | "leaf" | "spark" | "blossom" | "ripple" | "ink";
/** Which canvas a piece is painted on: `back` under the figures, `front` over them. */
export type Depth = "back" | "front";
/** One state of a piece: where its middle is, its turn, its size and how solid it is, at `t` of its life (0 to 1). */
export interface Key { t: number; x: number; y: number; r: number; sx: number; sy: number; o: number }
/** A piece: a shape in two tints, its life and the delay before it, and its keys in order. */
export interface Piece { shape: Shape; depth: Depth; w: number; h: number; c1: string; c2: string; ms: number; delay: number; keys: readonly Key[] }

export interface Material {
  shape: "petal" | "leaf";
  /** A piece's size at a phone's table figure, in px. */
  size: readonly [number, number];
  /** Each colourway's two tints; the first is drawn for a colour not listed. */
  tints: Record<string, readonly [string, string]>;
  mark: "blossom" | "ripple";
  markInk: string;
  /** The idle cue: a glint at a point of the figure (shares of its box), or its mark under its feet. */
  cue: { type: "spark"; at: readonly [number, number]; ink: string } | { type: "mark" };
  /** The special's accent: where it starts (shares of the figure's box), the way it opens (deg, 0 the way it faces), its spread, and when (ms). */
  accent: { at: readonly [number, number]; deg: number; spread: number; n: number; times: readonly number[] };
}
/** The store characters' materials. A free companion has none. */
export const MATERIALS: Partial<Record<CompanionKind, Material>> = {
  lamb: { shape: "petal", size: [11, 8], mark: "blossom", markInk: "#f2c14e", cue: { type: "spark", at: [0.83, 0.13], ink: "#fff3c0" },
    tints: { newyear: ["#ffb7c5", "#ff8fa8"], jade: ["#f1fbf3", "#bfe3cf"], ink: ["#f6f4ee", "#c9ccd1"], lacquer: ["#ffa093", "#e4504a"] },
    accent: { at: [0.97, 0.5], deg: -25, spread: 80, n: 3, times: [690] } },
  panda: { shape: "leaf", size: [15, 6], mark: "ripple", markInk: "#0c1712", cue: { type: "mark" },
    tints: { classic: ["#a3e38f", "#4fa862"], russet: ["#a3e38f", "#4fa862"], ink: ["#b9c4b8", "#6f8273"], gilded: ["#bfeed9", "#4fae93"] },
    accent: { at: [1, 0.58], deg: 20, spread: 0, n: 1, times: [780, 1200] } },
};
export const materialOf = (kind: string): Material | null => (MATERIALS as Record<string, Material | undefined>)[kind] ?? null;
/** The store characters whose special charges: the table lunges the figure (`lungeFor`). */
export const LUNGERS: ReadonlySet<string> = new Set(["lamb"]);
/** The trail's gold pieces, from the level at which a team's figures stop growing. */
export const GOLD: readonly [string, string] = ["#fff3c0", "#f2c14e"];
/** The team level index (2 is 0) from which every third piece is gold: level 6. */
export const GOLD_LEVEL = 4;

/** A figure as a moment sees it: where its feet's middle is, its width, the
 *  way it faces, its colourway, and whether its pieces turn gold. */
export interface Stance { x: number; y: number; px: number; dir: 1 | -1; colour: string; gold: boolean }

const rnd = (a: number, b: number, rand: () => number) => a + rand() * (b - a);
const key = (t: number, x: number, y: number, r: number, s: number, o: number, sy = s): Key => ({ t, x, y, r, sx: s, sy, o });
/** How much larger pieces are drawn round a larger figure (the Collection's stage). */
const grow = (px: number) => Math.min(2.4, Math.max(1, px / 52));
const tintOf = (m: Material, s: Stance, i: number): readonly [string, string] =>
  (s.gold && i % 3 === 2 ? GOLD : m.tints[s.colour] ?? Object.values(m.tints)[0]);

/** The trail's pieces as one hop lands, walking along `u` (a unit vector):
 *  `n` of them, each starting and landing behind the figure's middle along
 *  the way it walks, a little to either side of its path, leaving one at a
 *  time. They are painted under the figures. */
export function trailPieces(m: Material, s: Stance, u: Spot, n: number, serial: number, rand: () => number = Math.random): Piece[] {
  const k = grow(s.px), nx = -u.y, ny = u.x;
  return Array.from({ length: n }, (_, i) => {
    const back = rnd(0.6, 1.05, rand) * s.px, side = (i % 2 ? rnd(0.04, 0.2, rand) : rnd(-0.2, -0.04, rand)) * s.px;
    const x0 = s.x - u.x * back + nx * side, y0 = s.y - u.y * back + ny * side;
    const far = rnd(6, 26, rand) * k, x1 = x0 - u.x * far, y1 = y0 - u.y * far, lift = s.px * rnd(0.2, 0.55, rand);
    const sc = rnd(0.9, 1.5, rand), o = rnd(0.75, 0.95, rand), r0 = rnd(0, 360, rand), r1 = r0 + rnd(140, 360, rand) * (rand() < 0.5 ? -1 : 1);
    const [c1, c2] = tintOf(m, s, serial * 3 + i);
    return { shape: m.shape, depth: "back", w: m.size[0] * k, h: m.size[1] * k, c1, c2, ms: rnd(1900, 2400, rand), delay: i * 90, keys: [
      key(0, x0, y0 - lift, r0, 0.4 * sc, 0), key(0.12, x0 + (x1 - x0) * 0.35, y0 - lift * 0.6, r0 + (r1 - r0) * 0.4, sc, o),
      key(0.5, x1, y1, r1, sc, o * 0.9), key(1, x1, y1, r1 + 15, sc * 0.95, 0)] };
  });
}

/** The character's mark, in its own motion, round the figure: the Lamb's
 *  blossom ring opens and turns behind it; the Panda's ink ripple spreads
 *  flat under its feet, twice. */
export function markPieces(m: Material, s: Stance, delay: number, scale = 1, twice = true): Piece[] {
  const w = s.px * 1.2 * scale;
  if (m.mark === "blossom") {
    const y = s.y - s.px * 0.45;
    return [{ shape: "blossom", depth: "back", w, h: w, c1: m.markInk, c2: m.markInk, ms: 750, delay, keys: [key(0, s.x, y, 0, 0.6, 0.85), key(1, s.x, y, 70, 1.5, 0)] }];
  }
  const ring = (d: number): Piece => ({ shape: "ripple", depth: "back", w, h: w, c1: m.markInk, c2: m.markInk, ms: 900, delay: d,
    keys: [key(0, s.x, s.y - 2, 0, 0.3, 0.6, 0.11), key(1, s.x, s.y - 2, 0, 1.7, 0, 0.62)] });
  return twice ? [ring(delay), ring(delay + 220)] : [ring(delay)];
}

/** The idle cue: the Lamb's gold glint on its horn; the Panda's ink ripple under its feet. */
export function cuePieces(m: Material, s: Stance): Piece[] {
  if (m.cue.type === "mark") return markPieces(m, s, 0, 0.75, true);
  const { at, ink } = m.cue;
  const x = s.x + s.dir * (at[0] - 0.5) * s.px, y = s.y - (1 - at[1]) * s.px;
  const spark = (sx: number, sy: number, w: number, delay: number): Piece => ({ shape: "spark", depth: "front", w, h: w, c1: ink, c2: ink, ms: 750, delay,
    keys: [key(0, sx, sy, 0, 0, 0), key(0.4, sx, sy, 45, 1, 0.95), key(1, sx, sy, 90, 0, 0)] });
  return [spark(x, y, s.px * 0.3, 0), spark(x + s.dir * s.px * 0.16, y - s.px * 0.12, s.px * 0.16, 180)];
}

/** A burst: its mark, and `n` pieces that start on a ring outside the
 *  figure and fly out in two lobes, up left and up right, clear of the path
 *  of its jump, one at a time. */
export function burstPieces(m: Material, s: Stance, n: number, delay: number, rand: () => number = Math.random): Piece[] {
  const k = grow(s.px), ox = s.x, oy = s.y - s.px * 0.5, half = Math.max(1, Math.ceil(n / 2));
  const out: Piece[] = markPieces(m, s, delay, 1, n > 3);
  for (let i = 0; i < n; i++) {
    const right = i % 2 === 0, share = (Math.floor(i / 2) + 0.5) / half;
    const a = ((right ? -62 + 50 * share : -118 - 50 * share) + rnd(-5, 5, rand)) * Math.PI / 180;
    const r0 = s.px * 0.6, r1 = s.px * (0.6 + 0.7 * rnd(0.8, 1.15, rand));
    const ax = ox + Math.cos(a) * r1, ay = oy + Math.sin(a) * r1, ex = ax + Math.cos(a) * s.px * 0.25, ey = s.y - rnd(0, 6, rand), r = rnd(0, 360, rand);
    const [c1, c2] = tintOf(m, s, i);
    out.push({ shape: m.shape, depth: "front", w: m.size[0] * 1.5 * k, h: m.size[1] * 1.5 * k, c1, c2, ms: rnd(1150, 1450, rand), delay: delay + i * 35, keys: [
      key(0, ox + Math.cos(a) * r0, oy + Math.sin(a) * r0, r, 0.3, 0), key(0.34, ax, ay, r + 140, 1, 1), key(0.86, ex, ey, r + 330, 0.9, 0.85), key(1, ex, ey, r + 330, 0.9, 0)] });
  }
  return out;
}

/** A round won: its mark, and `n` pieces falling in two columns either side of the figure, one at a time. */
export function showerPieces(m: Material, s: Stance, n: number, rand: () => number = Math.random): Piece[] {
  const k = grow(s.px), out: Piece[] = markPieces(m, s, 300, 1, false);
  for (let i = 0; i < n; i++) {
    const side = i % 2 ? -1 : 1, x0 = s.x + side * rnd(0.7, 1.3, rand) * s.px, y0 = s.y - s.px * rnd(1.7, 2.1, rand);
    const sway = side * rnd(4, 16, rand) * k, y1 = s.y - rnd(0, 8, rand), r = rnd(0, 360, rand);
    const [c1, c2] = tintOf(m, s, i);
    out.push({ shape: m.shape, depth: "front", w: m.size[0] * 1.5 * k, h: m.size[1] * 1.5 * k, c1, c2, ms: 1350, delay: 150 + i * 110, keys: [
      key(0, x0, y0, r, 0.8, 0), key(0.2, x0 + sway, y0 + (y1 - y0) * 0.3, r + 120, 1, 1), key(0.85, x0 + sway * 1.5, y1, r + 400, 1, 0.9), key(1, x0 + sway * 1.5, y1, r + 400, 1, 0)] });
  }
  return out;
}

/** The themed entrance: `n` pieces spiral in to a ring outside the figure
 *  and fade there as it comes in, then its mark. The Panda's comes up
 *  through ink: blots open where it will stand, before it shows. */
export function entrancePieces(m: Material, s: Stance, n: number, rand: () => number = Math.random): Piece[] {
  const k = grow(s.px), cx = s.x, cy = s.y - s.px * 0.5, out: Piece[] = [];
  if (m.mark === "ripple") {
    const blots: readonly (readonly [number, number, number])[] = [[0, 0, 0], [-0.3, 0.12, 110], [0.28, -0.1, 200]];
    for (const [dx, dy, delay] of blots.slice(0, Math.min(3, Math.max(1, Math.round(n / 3))))) {
      out.push({ shape: "ink", depth: "back", w: s.px * 1.2, h: s.px * 1.2, c1: m.markInk, c2: m.markInk, ms: 760, delay,
        keys: [key(0, cx + dx * s.px, cy + dy * s.px, 0, 0.15, 0.55), key(1, cx + dx * s.px, cy + dy * s.px, 0, 1.25, 0)] });
    }
    return [...out, ...burstPieces(m, s, Math.max(0, n - out.length - 2), 420, rand).filter((p) => p.shape !== "ripple")];
  }
  for (let i = 0; i < n - 1; i++) {
    const a0 = (i * 2 * Math.PI) / Math.max(1, n - 1);
    const at = (turn: number, r: number): [number, number] => [cx + Math.cos(a0 + turn) * r * s.px, cy + Math.sin(a0 + turn) * r * s.px * 0.8];
    const [c1, c2] = tintOf(m, s, i);
    const p = [at(0, 1.3), at(1.2, 1.05), at(2.6, 0.78), at(3.4, 0.68)];
    out.push({ shape: m.shape, depth: "front", w: m.size[0] * 1.25 * k, h: m.size[1] * 1.25 * k, c1, c2, ms: 900, delay: i * 40, keys: [
      key(0, p[0][0], p[0][1], 0, 0.6, 0), key(0.3, p[1][0], p[1][1], 120, 1, 1), key(0.7, p[2][0], p[2][1], 260, 1, 1), key(1, p[3][0], p[3][1], 340, 0.8, 0)] });
  }
  return [...out, ...markPieces(m, s, 760, 1, false)];
}

/** The special's accent: a fan from the point of contact, away from the
 *  body (`reach` px further on where the table lunged the figure), each
 *  piece falling to the ground ahead of it. `at` is one of the accent's times. */
export function accentPieces(m: Material, s: Stance, reach: number, at: number, own = true, rand: () => number = Math.random): Piece[] {
  const k = grow(s.px), c = { ...m.accent, n: own ? m.accent.n : Math.ceil(m.accent.n / 2) };
  const x = s.x + s.dir * ((c.at[0] - 0.5) * s.px + reach), y = s.y - (1 - c.at[1]) * s.px;
  return Array.from({ length: c.n }, (_, i) => {
    const a = (c.deg + (c.n > 1 ? (i / (c.n - 1) - 0.5) * c.spread : 0)) * Math.PI / 180, ux = Math.cos(a) * s.dir, uy = Math.sin(a);
    const r0 = s.px * 0.12, r1 = s.px * rnd(0.5, 0.8, rand), r = rnd(0, 360, rand), ey = s.y - rnd(0, 5, rand);
    const [c1, c2] = tintOf(m, s, i);
    return { shape: m.shape, depth: "front", w: m.size[0] * 1.5 * k, h: m.size[1] * 1.5 * k, c1, c2, ms: 950, delay: at + i * 60, keys: [
      key(0, x + ux * r0, y + uy * r0, r, 0.4, 0), key(0.35, x + ux * r1, y + uy * r1, r + 120, 1, 1),
      key(0.85, x + ux * r1 * 1.25, ey, r + 260, 0.9, 0.85), key(1, x + ux * r1 * 1.25, ey, r + 260, 0.9, 0)] };
  });
}

/** A big trick lost: one piece falls beside the drooping figure. */
export function droopPiece(m: Material, s: Stance): Piece[] {
  const k = grow(s.px), x = s.x + s.dir * s.px * 0.7, y0 = s.y - s.px * 0.9;
  const [c1, c2] = tintOf(m, s, 0);
  return [{ shape: m.shape, depth: "front", w: m.size[0] * k, h: m.size[1] * k, c1, c2, ms: 1600, delay: 250, keys: [
    key(0, x, y0, 0, 1, 0), key(0.25, x + 10 * k, y0 + s.px * 0.3, 70, 1, 0.8), key(0.8, x - 6 * k, s.y - 3, 190, 1, 0.7), key(1, x - 6 * k, s.y - 3, 190, 1, 0)] }];
}

/** Under Reduce Motion: three pieces lying still at its feet, and nothing else. */
export function restPieces(m: Material, s: Stance): Piece[] {
  const k = grow(s.px), [c1, c2] = tintOf(m, s, 0);
  return ([[-0.38, -18], [-0.06, 24], [0.3, -8]] as const).map(([dx, r]) =>
    ({ shape: m.shape, depth: "back" as const, w: m.size[0] * k, h: m.size[1] * k, c1, c2, ms: 0, delay: 0, keys: [key(0, s.x + dx * s.px, s.y + 2, r, 1, 0.85)] }));
}

/** Where a walk from `from` to `to` (by `via`, `leg` of its way along)
 *  has the figure at `share` of its time, on the walk's own ease-in-out, so
 *  the trail asks the page for nothing. */
export function walkAt(from: Spot, to: Spot, share: number, via: Spot | null = null, leg = 0): Spot {
  // cubic-bezier(0.42, 0, 0.58, 1), solved for its time
  let lo = 0, hi = 1, s = share;
  for (let i = 0; i < 18; i++) { s = (lo + hi) / 2; if (((0.52 * s - 0.78) * s + 1.26) * s < share) lo = s; else hi = s; }
  const e = (-2 * s + 3) * s * s;
  if (!via || leg <= 0 || leg >= 1) return { x: from.x + (to.x - from.x) * e, y: from.y + (to.y - from.y) * e };
  return e < leg ? { x: from.x + (via.x - from.x) * (e / leg), y: from.y + (via.y - from.y) * (e / leg) }
    : { x: via.x + (to.x - via.x) * ((e - leg) / (1 - leg)), y: via.y + (to.y - via.y) * ((e - leg) / (1 - leg)) };
}
