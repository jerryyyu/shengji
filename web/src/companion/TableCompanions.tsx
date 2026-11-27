// The companions on the felt, when Show at the table is on: each person's
// companion stands beside their nameplate (yours over the left end of your
// hand, tagged "You") and now and then walks a few steps within a small zone
// there that keeps clear of the cards played and their labels, the hand,
// the buttons, the HUD and the other companions (`seatZones.ts`). A tap on
// empty felt walks yours to the clear spot nearest the tap; a tap on yours
// plays its special. Your team's round won plays each of its companions'
// special once the round-end sheet has closed, after any level-up. A figure stands on its team's pad in its team's scarf,
// so a team reads by shape as well as colour, and grows with its team's level.
// A level gained shows once the round-end sheet has closed and the table is
// in view: each of the team's companions pops to its new size, cheers, and
// flashes the new level by its head. A team's companions hop when it takes
// a trick, and cheer when the trick is worth 10 points or more; a
// companion sleeps while its person is away. Between moves they stand
// still, each with a short fidget every 6 to 10 s on its own clock (a sway,
// a blink, a small hop, in turn), so a table at rest draws almost no
// frames; a hidden page moves nothing, and Reduce Motion stills everything.
// Every move is a transform of a box round a still drawing, never of the
// drawing's parts. A bot, and a seat its owner left, has none.
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { MouseEvent, RefObject } from "react";
import type { GameState, StatePlayer } from "../protocol";
import { useAuth } from "../auth";
import { prefersReducedMotion } from "../motion";
import { useMediaQuery, TABLET_SCREEN } from "../phoneLayout";
import { Companion } from "./Companion";
import { DRAWINGS } from "./kinds";
import type { Pose } from "./Companion";
import { useCollection } from "./feature";
import { parseLook } from "./look";
import { shownAtTable, useCompanionMode } from "./mode";
import { HAND_LIFT, LIFT, clear, figureBox, nearest, nearestClear, nextSpot, pathClear, TAPPED_HIGH, TAPPED_WIDE, zoneAround, zonesFor } from "./seatZones";
import type { Layout, Rect, SeatPos, Spot, Zone } from "./seatZones";
import { useT } from "../i18n";
import { LEVELS, companionSize } from "./rig";
import "./tableCompanions.css";
import type { Team } from "./rig";

/** A team's level as the index companions grow by (2 is 0, A is 12). */
export const levelIndex = (rank: string | undefined): number => Math.max(0, LEVELS.indexOf((rank ?? "2") as (typeof LEVELS)[number]));

/** A trick worth this many points or more is cheered; a smaller one hopped. */
export const CHEER_POINTS = 10;
/** The fidget's length, and the shortest and longest wait before the next. */
export const FIDGET_MS = 600;
const FIDGET_GAP: readonly [number, number] = [6000, 10000];

/** What each seat's companion does on this frame: its team took a trick
 *  (a hop, a cheer for 10 points or more). A level gained is not here: it
 *  waits for the round-end sheet to close (`useLevelUps`). */
function reactions(state: GameState, prev: GameState | null): Record<number, Pose> {
  const out: Record<number, Pose> = {};
  if (!prev) return out;
  const done = state.last_trick;
  if (done && JSON.stringify(done) !== JSON.stringify(prev.last_trick)) {
    const team = state.players.find((p) => p.seat === done.winner)?.team;
    const pose: Pose = done.points >= CHEER_POINTS ? "cheer" : "hop";
    for (const p of state.players) if (p.team === team && p.connected && !p.away) out[p.seat] = pose;
  }
  return out;
}

/** A hop's peak, as a share of the figure's height: the highest of these
 *  whose rise stays clear where it stands (`hopPeak`). */
export const HOP_PEAKS = [0.28, 0.2, 0.13] as const;
export function hopFrames(peak: number): Keyframe[] {
  return [
    { transform: "translateY(0) scale(1, 1)" }, { transform: "translateY(0) scale(1.03, 0.96)", offset: 0.18 },
    { transform: `translateY(-${Math.round(peak * 100)}%) scale(0.99, 1.02)`, offset: 0.5 },
    { transform: "translateY(0) scale(1.02, 0.98)", offset: 0.82 }, { transform: "translateY(0) scale(1, 1)" }];
}
/** The highest hop a figure `px` wide standing at `s` has room for: its
 *  box raised by the rise past the zone's own headroom (`LIFT`) stays
 *  clear of the table, the nameplates and the felt's top edge. */
export function hopPeak(s: Spot | null, px: number, tag: boolean, layout: Layout): number {
  const low = HOP_PEAKS[HOP_PEAKS.length - 1];
  if (!s) return low;
  return HOP_PEAKS.find((k) => clear({ x: s.x, y: s.y - Math.max(0, Math.ceil((k - LIFT) * px)) }, px, tag, layout)) ?? low;
}

/** The moves at the table, as Web Animations of the box round a still
 *  drawing: no class or style changes as one starts or ends, so the
 *  compositor plays it and nothing is laid out or repainted. */
export const MOVES: Record<"fidget" | "nudge" | "hop" | "cheer", { frames: Keyframe[]; ms: number; easing: string }> = {
  fidget: { ms: FIDGET_MS, easing: "ease-in-out", frames: [
    { transform: "rotate(0)" }, { transform: "rotate(-3deg)", offset: 0.35 }, { transform: "rotate(2deg)", offset: 0.7 }, { transform: "rotate(0)" }] },
  nudge: { ms: 420, easing: "cubic-bezier(0.3, 0.7, 0.3, 1)", frames: [
    { transform: "translateY(0) scale(1, 1)" }, { transform: "translateY(-7%) scale(0.99, 1.02)", offset: 0.45 },
    { transform: "translateY(0) scale(1.02, 0.98)", offset: 0.8 }, { transform: "translateY(0) scale(1, 1)" }] },
  hop: { ms: 500, easing: "cubic-bezier(0.3, 0.7, 0.3, 1)", frames: hopFrames(HOP_PEAKS[HOP_PEAKS.length - 1]) },
  cheer: { ms: 1200, easing: "cubic-bezier(0.3, 0.7, 0.3, 1)", frames: [
    { transform: "translateY(0) scale(1, 1)" }, { transform: "translateY(0) scale(1.09, 0.89)", offset: 0.08 },
    { transform: "translateY(-9%) scale(0.95, 1.05)", offset: 0.26 }, { transform: "translateY(0) scale(1.1, 0.88)", offset: 0.44 },
    { transform: "translateY(-6%) scale(0.97, 1.04)", offset: 0.62 }, { transform: "translateY(0) scale(1.06, 0.93)", offset: 0.8 },
    { transform: "translateY(0) scale(1, 1)" }] },
};

/** A level gained: the figure pops from its old size (`from`, old over new)
 *  past its new one and settles, then cheers; one animation of the box. */
export const POP_MS = 500;
export const LEVEL_UP_MS = POP_MS + MOVES.cheer.ms;
function levelUpFrames(from: number): Keyframe[] {
  const pop = POP_MS / LEVEL_UP_MS;
  const cheer = MOVES.cheer.frames;
  return [
    { transform: `translateY(0) scale(${from.toFixed(3)})`, offset: 0, easing: "cubic-bezier(0.3, 0.7, 0.3, 1)" },
    { transform: "translateY(0) scale(1.22)", offset: pop * 0.5 },
    { transform: "translateY(0) scale(0.95)", offset: pop * 0.78 },
    ...cheer.map((f, i) => ({ ...f, offset: pop + (1 - pop) * (f.offset ?? i / (cheer.length - 1)) })),
  ];
}

/** Play one move on `el`, or a level gained from `from` (old size over new);
 *  resolves when it ends (at once where the element cannot animate, or under
 *  Reduce Motion, after the move's length: a level gained holds its still
 *  badge as long as the move would have taken). */
function play(el: HTMLElement | null, name: keyof typeof MOVES | "levelup", from = 1, frames: Keyframe[] | null = null): { done: Promise<void>; stop: () => void } {
  const m = name === "levelup" ? { frames: levelUpFrames(from), ms: LEVEL_UP_MS, easing: "linear" }
    : frames ? { ...MOVES[name], frames } : MOVES[name];
  if (!el || typeof el.animate !== "function" || prefersReducedMotion()) {
    let timer = 0;
    const done = new Promise<void>((r) => { timer = window.setTimeout(r, name === "levelup" ? m.ms : Math.min(m.ms, FIDGET_MS)); });
    return { done, stop: () => window.clearTimeout(timer) };
  }
  const a = el.animate(m.frames, { duration: m.ms, easing: m.easing });
  return { done: a.finished.then(() => undefined, () => undefined), stop: () => a.cancel() };
}

/** How soon a fidget or walk that fell due mid-move looks again. */
const RETRY_MS = 1000;
/** The fidgets a companion at rest plays in turn. */
const FIDGETS = ["sway", "blink", "nudge"] as const;
/** How long a blink keeps the eyes shut. */
const BLINK_MS = 160;

/** A companion at rest fidgets once every 6 to 10 s, on its own clock, while
 *  the page is shown and motion is allowed: a sway, a blink, a small hop, in
 *  turn. A blink shuts a still drawing's eyes for a moment (`onBlink`). */
function useFidget(el: RefObject<HTMLSpanElement | null>, on: boolean, onBlink: (shut: boolean) => void): void {
  const blink = useRef(onBlink);
  blink.current = onBlink;
  // the clock runs while the figure is drawn; a fidget due mid-move waits
  // for the move to end, so hops for tricks do not keep putting it off
  const onNow = useRef(on);
  onNow.current = on;
  const seenOn = useRef(false);
  if (on) seenOn.current = true;
  const live = seenOn.current;
  useEffect(() => {
    if (!live || prefersReducedMotion()) return;
    let timer = 0;
    let shut = 0;
    let turn = 0;
    let running: { stop: () => void } | null = null;
    const wait = () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(due, FIDGET_GAP[0] + Math.random() * (FIDGET_GAP[1] - FIDGET_GAP[0]));
    };
    const due = () => { if (onNow.current) fire(); else timer = window.setTimeout(due, RETRY_MS); };
    const fire = () => {
      const kind = FIDGETS[turn++ % FIDGETS.length];
      if (kind === "blink") {
        blink.current(true);
        shut = window.setTimeout(() => blink.current(false), BLINK_MS);
      } else {
        running = play(el.current, kind === "sway" ? "fidget" : "nudge");
      }
      wait();
    };
    const seen = () => {
      window.clearTimeout(timer);
      window.clearTimeout(shut);
      blink.current(false);
      running?.stop();
      if (document.visibilityState !== "hidden") wait();
    };
    seen();
    document.addEventListener("visibilitychange", seen);
    return () => {
      window.clearTimeout(timer);
      window.clearTimeout(shut);
      running?.stop();
      document.removeEventListener("visibilitychange", seen);
    };
  }, [el, live]);
}

/** A companion's base size and the most its nameplate's corner allows, by
 *  each player (Individual), in px; it grows from one to the other over the
 *  first levels (`companionSize`). */
export const SEAT_SIZE = { phone: { base: 44, max: 56 }, tablet: { base: 60, max: 76 } } as const;

/** A level its team gained, as one companion shows it: `n` tells one from
 *  the next, `from` is its old size over its new, `glyph` the new level. */
export interface LevelUp { n: number; from: number; glyph: string }
/** The shortest and longest wait before a companion by its player walks again. */
const WALK_GAP: readonly [number, number] = [8000, 15000];
/** A quick hop-walk off cards that landed or a layout that moved, and its step. */
const QUICK_MS: readonly [number, number] = [300, 500];
const QUICK_STEP_MS = 150;
/** Every walk, a tap's or one on its own clock, is the same unhurried
 *  stroll: about half a second a figure's width, one hop of its gait each
 *  520 ms. A tap's walk takes 1.2 s at least; one on its own clock takes
 *  just its distance's time, so the pace never changes. Both take 3 s at most. */
export const TAP_WALK_MS: readonly [number, number] = [1200, 3000];
export const STROLL_MS_PER_FIGURE = 500;
const STROLL_STEP_MS = 520;
/** A stroll's time over `dist` px for a figure `px` wide, before a tap's floor. */
export const strollMs = (dist: number, px: number) => Math.min(TAP_WALK_MS[1], (dist / px) * STROLL_MS_PER_FIGURE);

/** The translation in a computed transform (`matrix(a, b, c, d, x, y)`) or
 *  an inline one (`translate(xpx, ypx)`); null for none. */
export function translateOf(t: string | null | undefined): Spot | null {
  if (!t || t === "none") return null;
  const m = /matrix\(([^)]+)\)/.exec(t);
  if (m) {
    const v = m[1].split(",").map((n) => Number(n.trim()));
    return v.length === 6 && v.every(Number.isFinite) ? { x: v[4], y: v[5] } : null;
  }
  const tr = /translate\(([-\d.]+)px,\s*([-\d.]+)px\)/.exec(t);
  return tr ? { x: Number(tr[1]), y: Number(tr[2]) } : null;
}

/** What the table measures for the walking zones, in px relative to the felt:
 *  every control of your row (the clock's ring, the crown, Declare and its
 *  options, Bury, Play, Clear, the turn pill), the deck and its count, the
 *  hint line, and an open Last trick. */
const OBSTACLES = ".trick-play, .trick-tag, .you-row .btn, .action-bar .btn, .action-bar > *, .you-tagline, .you-tagline > *, "
  + ".timer-ring, .opponent, .last-trick-btn, .last-trick-panel, .deal-deck, .deal-deck-count, .hand-line";
const OVERLAYS = ".hud-group, .hud .chip, .hud button, .hud-menu, .chat-launch, .chat-panel, .chat-bubble, .away-pill";
/** An open panel: while one is up a tap on the felt is not for your companion. */
const PANELS = ".hud-menu, .last-trick-panel, .chat-panel";
/** The room kept from the screen's safe-area edges (a notch, the Dynamic Island), in px. */
const SAFE_MARGIN = 4;

/** A box as the screen has it, in the table's own frame: a portrait phone
 *  draws the table turned a quarter turn clockwise (`.app.rotated`), so a
 *  screen box there is turned back. */
function framed(el: Element, b: { left: number; top: number; width: number; height: number }): Rect {
  if (!el.closest(".app.rotated")) return { x: b.left, y: b.top, w: b.width, h: b.height };
  const W = window.innerWidth;
  return { x: b.top, y: W - (b.left + b.width), w: b.height, h: b.width };
}

/** A tap's point in the table's own frame. */
function framedPoint(el: Element, x: number, y: number): Spot {
  return el.closest(".app.rotated") ? { x: y, y: window.innerWidth - x } : { x, y };
}

function measure(felt: HTMLElement, phone = false, dealing = false): Layout {
  const f = framed(felt, felt.getBoundingClientRect());
  const rel = (e: Element): Rect => {
    const b = framed(e, e.getBoundingClientRect());
    const r = { x: b.x - f.x, y: b.y - f.y, w: b.w, h: b.h };
    // played cards (and their LEAD / WINS label) fly in as a transform of
    // their wrapper: they are measured where they land
    const flying = e.closest(".trick-play");
    return flying ? landed(flying as HTMLElement, e === flying, r, rel0(flying)) : r;
  };
  const rel0 = (e: Element): Rect => { const b = framed(e, e.getBoundingClientRect()); return { x: b.x - f.x, y: b.y - f.y, w: b.w, h: b.h }; };
  const one = (sel: string): Rect | null => { const e = felt.querySelector(sel); if (!e) return null; const r = rel(e); return r.w > 0 && r.h > 0 ? r : null; };
  const screen = felt.closest(".table-screen") ?? felt;
  const obstacles = [...felt.querySelectorAll(OBSTACLES), ...screen.querySelectorAll(OVERLAYS)]
    .filter((e) => !e.closest(".table-companions")).map(rel).filter((r) => r.w > 2 && r.h > 2);
  // the hand from its cards' top, raised by a chosen card's lift
  const hand = one(".hand");
  const first = one(".hand .hand-slot");
  if (hand) {
    const top = Math.min(hand.y, (first?.y ?? hand.y) - HAND_LIFT);
    // while it is dealt the hand is weighed across the felt, where its cards
    // will be, so no figure steps into its row only to be pushed out again
    obstacles.push(dealing ? { x: 0, y: top, w: f.w, h: hand.y + hand.h - top } : { x: hand.x, y: top, w: hand.w, h: hand.y + hand.h - top });
  }
  const plates: Layout["plates"] = {};
  for (const pos of ["left", "top", "right"] as const) {
    const r = one(`.opponent.pos-${pos}`);
    if (r) plates[pos] = r;
  }
  // the side seats' nameplates sit at the screen's safe-area edges, and
  // nothing stands under a notch or the Dynamic Island
  const inset = safeInsets(felt, f);
  const x0 = Math.max(plates.left?.x ?? 0, inset.l);
  const x1 = Math.min(plates.right ? plates.right.x + plates.right.w : f.w, f.w - inset.r);
  const safe = plates.left && plates.right || inset.l > 0 || inset.r > 0 ? { x0, x1 } : undefined;
  if (inset.t > 0) obstacles.push({ x: 0, y: 0, w: f.w, h: inset.t });
  if (inset.b > 0) obstacles.push({ x: 0, y: f.h - inset.b, w: f.w, h: inset.b });
  return { felt: { w: f.w, h: f.h }, plates, tagline: one(".you-tagline"), row: one(".you-row"), hand: first,
           ...(safe ? { safe } : {}), ...(phone ? { phone } : {}), obstacles };
}

/** A rect drawn inside a flying wrapper (`wrap`, itself when `self`),
 *  where it will be once the wrapper's transform is gone: the wrapper's own
 *  box at its laid-out size, and anything inside it carried back with it.
 *  Any affine transform (a move, a scale, a turn) about its transform-origin
 *  is undone; a rect with none, or one that cannot be undone, is as drawn. */
export function landed(wrap: HTMLElement, self: boolean, r: Rect, box: Rect): Rect {
  const cs = getComputedStyle(wrap);
  const m = /^matrix\(([^)]+)\)$/.exec(cs.transform ?? "");
  if (!m) return r;
  const [a, b, c, d, tx, ty] = m[1].split(",").map((n) => Number(n.trim()));
  const det = a * d - b * c;
  if (![a, b, c, d, tx, ty].every(Number.isFinite) || Math.abs(det) < 1e-6) return r;
  if (a === 1 && b === 0 && c === 0 && d === 1 && tx === 0 && ty === 0) return r;
  // laid-out size (no transform), else the drawn box scaled back
  const w = wrap.offsetWidth || box.w / Math.max(1e-6, Math.hypot(a, b));
  const h = wrap.offsetHeight || box.h / Math.max(1e-6, Math.hypot(c, d));
  const [ox, oy] = (cs.transformOrigin || `${w / 2}px ${h / 2}px`).split(" ").map((v) => parseFloat(v));
  const O = { x: Number.isFinite(ox) ? ox : w / 2, y: Number.isFinite(oy) ? oy : h / 2 };
  // the drawn centre is the origin plus the turned and scaled centre, moved
  const C = { x: w / 2 - O.x, y: h / 2 - O.y };
  const cx = box.x + box.w / 2, cy = box.y + box.h / 2;
  const p0 = { x: cx - O.x - (a * C.x + c * C.y) - tx, y: cy - O.y - (b * C.x + d * C.y) - ty };
  if (self) return { x: p0.x, y: p0.y, w, h };
  // a point drawn at q lands at p0 + O + inverse(q - t - p0 - O)
  const back = (qx: number, qy: number) => {
    const vx = qx - tx - p0.x - O.x, vy = qy - ty - p0.y - O.y;
    return { x: p0.x + O.x + (d * vx - c * vy) / det, y: p0.y + O.y + (-b * vx + a * vy) / det };
  };
  const pts = [back(r.x, r.y), back(r.x + r.w, r.y), back(r.x, r.y + r.h), back(r.x + r.w, r.y + r.h)];
  const xs = pts.map((p) => p.x), ys = pts.map((p) => p.y);
  return { x: Math.min(...xs), y: Math.min(...ys), w: Math.max(...xs) - Math.min(...xs), h: Math.max(...ys) - Math.min(...ys) };
}

/** How far the screen's safe-area insets reach into the felt, each with
 *  `SAFE_MARGIN` more, in px (0 where there is none): read off a probe padded
 *  by `env(safe-area-inset-*)`. A rotated table's insets are its frame's, so
 *  it reads none. */
function safeInsets(felt: HTMLElement, f: Rect): { l: number; r: number; t: number; b: number } {
  const none = { l: 0, r: 0, t: 0, b: 0 };
  if (felt.closest(".app.rotated")) return none;
  const probe = document.createElement("div");
  probe.className = "tc-safe-probe";
  probe.style.cssText = "position:fixed;left:0;top:0;width:0;height:0;visibility:hidden;pointer-events:none;"
    + "padding:env(safe-area-inset-top,0px) env(safe-area-inset-right,0px) env(safe-area-inset-bottom,0px) env(safe-area-inset-left,0px)";
  document.body.appendChild(probe);
  const cs = getComputedStyle(probe);
  const px = (v: string) => parseFloat(v) || 0;
  const raw = { l: px(cs.paddingLeft), r: px(cs.paddingRight), t: px(cs.paddingTop), b: px(cs.paddingBottom) };
  probe.remove();
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const reach = (edge: number, into: number) => (edge > 0 ? Math.max(0, edge + SAFE_MARGIN - into) : 0);
  return { l: reach(raw.l, f.x), r: reach(raw.r, vw - (f.x + f.w)), t: reach(raw.t, f.y), b: reach(raw.b, vh - (f.y + f.h)) };
}

/** Where a seat sits from the viewer's chair, as the trick area draws it. */
const SIDES: readonly SeatPos[] = ["bottom", "left", "top", "right"];

const at = (s: Spot) => `translate(${s.x}px, ${s.y}px)`;

/** A corner to walk by from `a` to `b` so neither leg meets anything in
 *  `layout` (the other companions): null where the straight way is clear,
 *  or no corner tried clears both legs. Tried: the two corners of the
 *  rectangle the walk spans, then points either side of its middle, a figure
 *  further out each time; the shortest clear one wins. */
export function around(a: Spot, b: Spot, px: number, tag: boolean, layout: Layout): Spot | null {
  if (pathClear(a, b, px, tag, layout)) return null;
  const mid = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
  const len = Math.hypot(b.x - a.x, b.y - a.y) || 1;
  const n = { x: -(b.y - a.y) / len, y: (b.x - a.x) / len };
  const tries: Spot[] = [{ x: a.x, y: b.y }, { x: b.x, y: a.y }];
  for (let k = 1; k <= 4; k++) for (const side of [1, -1]) tries.push({ x: mid.x + side * k * px * n.x, y: mid.y + side * k * px * n.y });
  let best: Spot | null = null;
  let cost = Infinity;
  for (const raw of tries) {
    const v = { x: Math.round(raw.x), y: Math.round(raw.y) };
    const d = Math.hypot(v.x - a.x, v.y - a.y) + Math.hypot(b.x - v.x, b.y - v.y);
    if (d < cost && pathClear(a, v, px, tag, layout) && pathClear(v, b, px, tag, layout)) { cost = d; best = v; }
  }
  return best;
}

/** How much larger a figure is drawn through its special, the largest that
 *  stays clear where it stands. */
const SPECIAL_SCALES = [1.5, 1.35, 1.2] as const;
/** Where a figure standing at `s` would be drawn `k` times its size: grown
 *  from its feet, so it keeps standing on the same spot. */
const grown = (s: Spot, px: number, k: number): Spot => ({ x: s.x - ((k - 1) * px) / 2, y: s.y - (k - 1) * px });

/** A tap on your own companion plays its special at most this often. */
export const SPECIAL_COOLDOWN_MS = 3000;
/** Taps on the felt that walk your companion are at least this far apart. */
export const TAP_THROTTLE_MS = 500;

/** One companion by its player's nameplate. It stands on its zone's home,
 *  and every 8 to 15 s walks a few hopping steps to another clear spot of
 *  its zone, facing the way it goes; when cards land on it, it walks to the
 *  nearest clear spot. `goal` (yours only) is where a tap on the felt sends
 *  it: it walks there, passing under the cards if they are in the way, and
 *  that spot (`tapped`) is its home from then on, its walks small ones round
 *  it; when cards or a moved layout cover it, it hops to the nearest clear
 *  spot and makes that its home (`onTapped`). A tap on yours plays its special
 *  (at most every 3 s), and `wins` counts your team's rounds won, each
 *  played as a special once any level-up has ended. Every move is a Web
 *  Animation of a transform. Under Reduce Motion it stands on its home;
 *  while the page is hidden it rests. */
function Walker({ player, team, px, pos, zone, layout, roam, pose, up, you, goal, tapped, wins, dealing, onEnd, onUpEnd, onGoal, onTapped, onStray }: {
  player: StatePlayer; team: Team; px: number; pos: SeatPos; dealing: boolean;
  zone: Zone; layout: Layout; roam: Layout; pose: Pose; up: LevelUp | null; you: boolean; goal: { spot: Spot; n: number } | null;
  tapped: Spot | null; wins: number; onEnd: () => void; onUpEnd: () => void; onGoal?: (n: number) => void;
  onTapped?: (s: Spot | null) => void; onStray?: (s: Spot | null) => void;
}) {
  const t = useT();
  const { kind, colour } = parseLook(player.look);
  const away = !player.connected || player.away === true;
  const move: Pose = away ? "sleep" : pose;
  const walk = useRef<HTMLSpanElement | null>(null);
  const face = useRef<HTMLSpanElement | null>(null);
  const box = useRef<HTMLSpanElement | null>(null);
  const cur = useRef<Spot | null>(null);
  const walking = useRef<Animation[]>([]);
  // the walk in flight, from where to where; null at rest
  const path = useRef<{ from: Spot; to: Spot } | null>(null);
  // where it stands and wanders: round the spot a tap chose (clear of the
  // other companions' zones as well as the table), else its own zone
  const here = useMemo(() => (tapped ? zoneAround(tapped, px, roam, you) : zone),
  // eslint-disable-next-line react-hooks/exhaustive-deps
  [tapped?.x, tapped?.y, zone, roam, px, you]);
  const room = tapped ? roam : layout;
  const tappedDone = useRef(onTapped);
  tappedDone.current = onTapped;
  const ended = useRef(onEnd);
  ended.current = onEnd;
  const upEnded = useRef(onUpEnd);
  upEnded.current = onUpEnd;
  const layoutNow = useRef(layout);
  layoutNow.current = layout;
  const [blink, setBlink] = useState(false);
  // the special in play, counted so each one plays once
  const [special, setSpecial] = useState(0);
  const [playing, setPlaying] = useState(false);
  const lastSpecial = useRef(-Infinity);
  // a figure with nowhere clear to stand is not drawn, and keeps no clock
  // where a figure whose whole zone is covered stepped out to, until its
  // zone has room again: it is never taken off the table while drawn
  const [stray, setStray] = useState<Spot | null>(null);
  // the table keeps the others clear of where it stepped out to
  const strayDone = useRef(onStray);
  strayDone.current = onStray;
  useEffect(() => { strayDone.current?.(stray); }, [stray]);
  useEffect(() => () => strayDone.current?.(null), []);
  // a figure taken off the table is drawn again only with a spot to stand on
  const [, redraw] = useState(0);
  // a tapped home stands on its own: the zone only matters without one; a
  // drawn figure stays drawn until it has been moved or taken off
  const placed = (tapped ?? zone.home ?? stray ?? cur.current) !== null;
  useFidget(box, placed && move === "idle" && !up && !playing, setBlink);

  const stop = () => { for (const a of walking.current) a.cancel(); walking.current = []; path.current = null; };
  const place = (s: Spot) => { cur.current = s; if (walk.current) walk.current.style.transform = at(s); };
  /** Where the figure is drawn now: mid-walk, where the walk has it (its
   *  rendered transform), else the spot it stands on. */
  const shown = (): Spot | null => {
    const el = walk.current;
    if (!el || walking.current.length === 0) return cur.current;
    return translateOf(getComputedStyle(el).transform) ?? cur.current;
  };
  /** Walk to `to`, from wherever the figure is drawn now. A walk that would
   *  cross cards goes there at once, unless `under` lets it pass beneath them
   *  (the table's layer is under the cards); `quick` is a short hop-walk for
   *  stepping off cards or a moved layout. Only a figure with nowhere drawn
   *  yet, a hidden page or Reduce Motion goes there at once. */
  const goTo = (to: Spot, { under = false, quick = false, slow = false, via = null }:
    { under?: boolean; quick?: boolean; slow?: boolean; via?: Spot | null } = {}) => {
    const from = shown();
    const el = walk.current;
    if (!from || !el || typeof el.animate !== "function" || prefersReducedMotion() || document.visibilityState === "hidden"
        || (!under && !pathClear(from, to, px, you, layoutNow.current))) {
      // a walk still in flight would end over the new spot: it stops first
      stop();
      place(to);
      return;
    }
    stop();
    if (Math.hypot(to.x - from.x, to.y - from.y) < 1 && !via) { place(to); return; }
    const leg = via ? Math.hypot(via.x - from.x, via.y - from.y) : 0;
    const dist = via ? leg + Math.hypot(to.x - via.x, to.y - via.y) : Math.hypot(to.x - from.x, to.y - from.y);
    const ms = quick ? Math.min(QUICK_MS[1], Math.max(QUICK_MS[0], QUICK_MS[0] + (dist / px) * 80))
      : slow ? Math.max(TAP_WALK_MS[0], strollMs(dist, px))
      : strollMs(dist, px);
    const dir = to.x < from.x ? -1 : 1;
    if (face.current) face.current.style.transform = `scaleX(${dir})`;
    const a = el.animate(via && dist > 0 ? [{ transform: at(from) }, { transform: at(via), offset: leg / dist }, { transform: at(to) }]
      : [{ transform: at(from) }, { transform: at(to) }], { duration: ms, easing: "ease-in-out" });
    const step = quick ? QUICK_STEP_MS : STROLL_STEP_MS;
    const gait = face.current?.animate([
      { transform: `scaleX(${dir}) translateY(0)` }, { transform: `scaleX(${dir}) translateY(-12%)`, offset: 0.45 },
      { transform: `scaleX(${dir}) translateY(0)` }], { duration: step, iterations: Math.max(1, Math.round(ms / step)) });
    walking.current = gait ? [a, gait] : [a];
    path.current = under ? null : { from, to };
    place(to);
    void a.finished.then(() => {
      walking.current = walking.current.filter((x) => x !== a && x !== gait);
      if (path.current?.to === to) path.current = null;
    }, () => {});
  };

  // stand on the home, or step off a spot cards have landed on. A figure with
  // no clear spot is not drawn and forgets where it stood, so the next one
  // drawn is placed afresh; a figure that must move (cards landing on it, a
  // walk whose way they now block, a moved layout) hops there quickly from
  // where it is drawn, passing under the cards, never jumping. A tapped home
  // cards now cover gives way to the nearest clear spot, which becomes the
  // home; with none clear it goes back to its zone.
  useLayoutEffect(() => {
    const now = cur.current;
    const drawn = now !== null && !!walk.current?.style.transform;
    // while the hand is dealt the cards keep arriving and flying over the
    // felt: a drawn figure holds still under them, and steps aside, if it
    // must, once the deal is done
    if (dealing && drawn) return;
    const quick = { under: true, quick: true };
    if (tapped && !clear(tapped, px, you, roam)) {
      // with no clear spot near it the tapped home is dropped: yours goes back
      // to its zone, at the zone's own spot and size
      const near = nearestClear({ x: tapped.x + px / 2, y: tapped.y + px }, px, you, roam);
      tappedDone.current?.(near);
      const to = near ?? zone.home;
      if (!to) { stop(); cur.current = null; redraw((n) => n + 1); }
      else if (drawn) goTo(to, quick);
      else place(to);
      return;
    }
    if (!tapped && !zone.home) {
      // its whole zone covered: a drawn figure walks out to the nearest
      // clear spot and waits there; one not drawn yet stays off
      if (stray && now && clear(now, px, you, roam)) return;
      const out = drawn ? nearestClear({ x: now.x + px / 2, y: now.y + px }, px, you, roam) : null;
      if (out) { setStray(out); goTo(out, quick); return; }
      stop();
      if (cur.current) { cur.current = null; redraw((n) => n + 1); }
      if (stray) setStray(null);
      return;
    }
    if (stray) setStray(null);
    const home = (tapped ?? zone.home)!;
    if (!now || !drawn) {
      place(now && clear(now, px, you, room) ? now : home);
      if (face.current && !now) face.current.style.transform = `scaleX(${pos === "right" ? -1 : 1})`;
      return;
    }
    const flight = path.current;
    if (flight && !pathClear(flight.from, flight.to, px, you, room)) {
      goTo(clear(now, px, you, room) ? now : nearest(here, now) ?? home, quick);
      return;
    }
    const near = nearest(here, now);
    const off = !near || Math.hypot(near.x - now.x, near.y - now.y) > px / 2;
    // covered (a control or a bubble appeared over it): out by the nearest
    // way, upward before downward
    if (off || !clear(now, px, you, room)) goTo(off ? home : nearest(here, now, true) ?? home, quick);
  }, [zone, here, layout, roam, px, you, dealing]);

  // a tap on the felt sends yours there, once, and makes it the home: each
  // tap is taken (or dropped) the first time it is seen, and one whose spot
  // is no longer clear of the table and the other companions is dropped
  const goalN = goal?.n;
  const tookGoal = useRef(0);
  const goalDone = useRef(onGoal);
  goalDone.current = onGoal;
  useEffect(() => {
    if (!goal || goal.n <= tookGoal.current) return;
    tookGoal.current = goal.n;
    goalDone.current?.(goal.n);
    if (!placed || !clear(goal.spot, px, you, roam)) return;
    // round the other companions, in two legs, where the straight way meets one
    const from = shown();
    const others: Layout = { ...layout, obstacles: roam.obstacles.slice(layout.obstacles.length) };
    goTo(goal.spot, { under: true, slow: true, via: from ? around(from, goal.spot, px, you, others) : null });
    tappedDone.current?.(goal.spot);
  }, [goalN]);

  // a walk now and then, on its own clock, while the page is shown, within
  // where it stands (round a tapped home, or its zone)
  const zoneNow = useRef(here);
  zoneNow.current = here;
  const roomNow = useRef(room);
  roomNow.current = room;
  const roamNow = useRef(roam);
  roamNow.current = roam;
  // the clock runs while the figure is drawn: a walk due mid-move (a hop for
  // a trick, a special) or while the hand is dealt waits for it to end, so
  // the moves do not keep putting it off
  const idle = placed && move === "idle" && !up && !playing && !dealing;
  const idleNow = useRef(idle);
  idleNow.current = idle;
  useEffect(() => {
    if (!placed || prefersReducedMotion()) return;
    let timer = 0;
    const due = () => {
      if (!idleNow.current || walking.current.length > 0) { timer = window.setTimeout(due, RETRY_MS); return; }
      const from = cur.current;
      // a spot it can reach without crossing anything; it stays put when none is
      for (let i = 0; from && i < 6; i++) {
        const to = nextSpot(zoneNow.current, from, px, Math.random());
        if (to && pathClear(from, to, px, you, roomNow.current)) { goTo(to); break; }
      }
      wait();
    };
    const wait = () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(due, WALK_GAP[0] + Math.random() * (WALK_GAP[1] - WALK_GAP[0]));
    };
    const seen = () => { window.clearTimeout(timer); if (document.visibilityState !== "hidden") wait(); };
    seen();
    document.addEventListener("visibilitychange", seen);
    return () => { window.clearTimeout(timer); document.removeEventListener("visibilitychange", seen); };
  }, [placed, px]);
  useEffect(() => stop, []);

  useEffect(() => {
    if (move !== "hop" && move !== "cheer") return;
    // a hop as high as stays clear where it stands
    const run = move === "hop" ? play(box.current, "hop", 1, hopFrames(hopPeak(cur.current, px, you, roamNow.current))) : play(box.current, move);
    let live = true;
    void run.done.then(() => { if (live) ended.current(); });
    return () => { live = false; run.stop(); };
  // a hop's height is read where it stands as it starts
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [move]);

  // a level gained: once per level, when the table is in view
  const upN = up?.n;
  useEffect(() => {
    if (!up || !placed) return;
    const run = play(box.current, "levelup", up.from);
    let live = true;
    void run.done.then(() => { if (live) upEnded.current(); });
    return () => { live = false; run.stop(); };
  }, [upN, placed]);

  // a round won: its special, once any level-up has ended
  const played = useRef(0);
  useEffect(() => {
    if (wins <= played.current || up || !placed || away) return;
    played.current = wins;
    setSpecial((n) => n + 1);
  }, [wins, up, placed, away]);
  // the special: the drawing plays its signature for that move's length
  // (the one time a figure's parts move at the table), then stands still
  // again; under Reduce Motion it shows the signature's peak for a moment
  useEffect(() => {
    if (special === 0) return;
    lastSpecial.current = Date.now();
    setPlaying(true);
    const still = prefersReducedMotion();
    const ms = still ? 1000 : DRAWINGS[kind].reactMs;
    const timer = window.setTimeout(() => setPlaying(false), ms);
    // drawn larger for its length, as large as stays clear where it stands
    const s = cur.current;
    const k = still || !s ? 1 : SPECIAL_SCALES.find((f) => clear(grown(s, px, f), px * f, you, roamNow.current)) ?? 1;
    const el = box.current;
    const a = k > 1 && el && typeof el.animate === "function"
      ? el.animate([{ transform: "scale(1)" }, { transform: `scale(${k})`, offset: 0.15 }, { transform: `scale(${k})`, offset: 0.85 },
                    { transform: "scale(1)" }], { duration: ms, easing: "ease-in-out" })
      : null;
    return () => { window.clearTimeout(timer); a?.cancel(); setPlaying(false); };
  }, [special, kind]);
  const nudging = useRef<{ stop: () => void } | null>(null);
  useEffect(() => () => nudging.current?.stop(), []);
  const poked = (e: MouseEvent) => {
    e.stopPropagation();
    if (!you || away || playing || up) return;
    // a tap while the special cools down still answers, with a small hop
    if (Date.now() - lastSpecial.current < SPECIAL_COOLDOWN_MS) {
      if (!prefersReducedMotion()) { nudging.current?.stop(); nudging.current = play(box.current, "nudge"); }
      return;
    }
    setSpecial((n) => n + 1);
  };

  const drawn: Pose = away ? "sleep" : up ? "cheer" : playing ? "react" : move;

  if (!placed) return null;
  return (
    <span className="tc-seat" data-seat={player.seat} data-pos={pos}>
      <span className={`tc-walk${you ? " tc-mine" : ""}`} ref={walk} onClick={you ? poked : undefined}>
        {you ? <span className="tc-you">{t("table.companionYou")}</span> : null}
        {up && !away ? <span className="tc-level" key={up.n}>{up.glyph}</span> : null}
        <span className="tc-face" ref={face}>
          <span className="tc-move" ref={box} data-move={up && !away ? "levelup" : playing && !away ? "react" : move}>
            <Companion kind={kind} colour={colour} size={px} team={team} grow={false}
                       blink={blink && drawn === "idle"} still={drawn === "react" && playing ? undefined : true} idle="rest"
                       state={drawn === "cheer" ? "cheer" : drawn === "sleep" ? "sleep" : drawn === "react" ? "react" : "idle"} />
          </span>
        </span>
      </span>
    </span>
  );
}

/** The walking zones, measured from the felt and measured again whenever
 *  the cards, the phase or the layout change (and twice more as cards
 *  finish flying in). */
function useLayout(root: RefObject<HTMLDivElement | null>, on: boolean, key: string, phone = false, dealing = false): Layout | null {
  const [layout, setLayout] = useState<Layout | null>(null);
  useLayoutEffect(() => {
    if (!on) return;
    const felt = root.current?.parentElement;
    if (!felt) return;
    // a measure that finds nothing moved keeps the layout as it was
    let last = "";
    const read = () => {
      const next = measure(felt, phone, dealing);
      const seen = JSON.stringify(next);
      if (seen === last) return;
      last = seen;
      setLayout(next);
    };
    read();
    // once more as the cards finish flying in, and again after a slow flight
    const later = window.setTimeout(read, 450);
    const slow = window.setTimeout(read, 1200);
    window.addEventListener("resize", read);
    let ro: ResizeObserver | null = null;
    if (typeof ResizeObserver === "function") {
      ro = new ResizeObserver(read);
      ro.observe(felt);
    }
    // a line, a control, a chat bubble or a panel that comes and goes (not
    // with the game): measured again on the next frame, never for the
    // companions' own changes
    let frame = 0;
    let mo: MutationObserver | null = null;
    if (typeof MutationObserver === "function") {
      mo = new MutationObserver((list) => {
        if (frame || list.every((m) => (m.target as Element).closest?.(".table-companions"))) return;
        frame = window.requestAnimationFrame(() => { frame = 0; read(); });
      });
      mo.observe(felt.closest(".table-screen") ?? felt, { childList: true, subtree: true });
    }
    return () => {
      window.clearTimeout(later); window.clearTimeout(slow); window.cancelAnimationFrame(frame);
      window.removeEventListener("resize", read); ro?.disconnect(); mo?.disconnect();
    };
  }, [root, on, key, phone, dealing]);
  return on ? layout : null;
}

/** Whether the page is shown, re-read as it is hidden and shown again. */
function usePageShown(): boolean {
  const [shown, setShown] = useState(() => document.visibilityState !== "hidden");
  useEffect(() => {
    const seen = () => setShown(document.visibilityState !== "hidden");
    document.addEventListener("visibilitychange", seen);
    return () => document.removeEventListener("visibilitychange", seen);
  }, []);
  return shown;
}

/** The levels the companions stand at, and each seat's level gained still
 *  to show. A level changes behind the round-end sheet, so the figures keep
 *  the old one while it is open (and while the page is hidden); once the
 *  table is in view a team that climbed shows it, once per companion. A
 *  level lost (a new game) or one the table opened onto changes the size
 *  with no move. */
export function useLevelUps(state: GameState, size: { base: number; max: number }) {
  const [levels, setLevels] = useState<readonly string[]>(state.levels);
  const [ups, setUps] = useState<Record<number, LevelUp>>({});
  const count = useRef(0);
  const pageShown = usePageShown();
  const covered = state.phase === "round_end" || !pageShown;
  useEffect(() => {
    if (covered || (state.levels[0] === levels[0] && state.levels[1] === levels[1])) return;
    const add: Record<number, LevelUp> = {};
    for (const team of [0, 1] as const) {
      const was = levelIndex(levels[team]);
      const is = levelIndex(state.levels[team]);
      if (is <= was) continue;
      const from = companionSize(size.base, was, size.max) / companionSize(size.base, is, size.max);
      for (const p of state.players) {
        if (p.team !== team || p.is_bot || p.left || !p.connected || p.away) continue;
        add[p.seat] = { n: ++count.current, from, glyph: state.levels[team] };
      }
    }
    setLevels(state.levels);
    if (Object.keys(add).length) setUps((u) => ({ ...u, ...add }));
  }, [covered, state.levels, state.players, levels, size.base, size.max]);
  const done = (seat: number) => () => setUps((u) => {
    const rest = { ...u };
    delete rest[seat];
    return rest;
  });
  return { levels, ups, done };
}

/** Your team's rounds won, counted once each round-end sheet has closed
 *  and the table is in view (as a level gained is shown). */
function useRoundWins(state: GameState, ours: 0 | 1): number {
  const [wins, setWins] = useState(0);
  const pending = useRef(false);
  const pageShown = usePageShown();
  const covered = state.phase === "round_end" || !pageShown;
  if (state.phase === "round_end" && state.round_result && state.round_result.winner_team === ours) pending.current = true;
  useEffect(() => {
    if (covered || !pending.current) return;
    pending.current = false;
    setWins((n) => n + 1);
  }, [covered]);
  return wins;
}

/** What a tap on the felt is not: a card, a played trick, a seat, a
 *  control, a panel, or a companion. */
const NOT_FELT = "button, a, input, textarea, select, label, [role='button'], [role='switch'], .card, .hand, .hand-line, "
  + ".trick-play, .opponent, .hud, .you-row, .action-bar, .deal-deck, .chat-panel, .modal, .panel, .last-trick-panel, .tc-walk";

export default function TableCompanions({ state }: { state: GameState }) {
  const shown = useCollection();
  const account = useAuth();
  const mode = useCompanionMode(account.status === "in" ? account.user : null);
  const tablet = useMediaQuery(TABLET_SCREEN);
  const [poses, setPoses] = useState<Record<number, Pose>>({});
  const [goal, setGoal] = useState<{ spot: Spot; n: number } | null>(null);
  // the spot your last tap chose: yours stays round it for the rest of this table
  const [tapped, setTapped] = useState<{ room: string; spot: Spot } | null>(null);
  // where a figure whose whole zone is covered stepped out to, by seat
  const [strays, setStrays] = useState<Partial<Record<SeatPos, { spot: Spot; px: number }>>>({});
  const prev = useRef<GameState | null>(null);
  const root = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const moves = reactions(state, prev.current);
    prev.current = state;
    if (Object.keys(moves).length) setPoses((p) => ({ ...p, ...moves }));
  }, [state]);
  // a table you only watch (an open table's newcomer until the next trick)
  // draws none, as the watch feed and a replay draw none
  const on = shown && shownAtTable(mode) && state.joining_you !== true;
  const size = tablet ? SEAT_SIZE.tablet : SEAT_SIZE.phone;
  const { levels, ups, done } = useLevelUps(state, size);
  const me = state.players.find((p) => p.seat === state.you);
  const ours = me?.team ?? 0;
  const wins = useRoundWins(state, ours);
  const key = JSON.stringify([state.phase, state.trick, state.last_trick?.winner, state.players.map((p) => [p.seat, p.is_bot, p.left]), tablet, levels]);
  const layout = useLayout(root, on, key, !tablet, state.phase === "deal");
  const people = state.players.filter((p) => !p.is_bot && !p.left);
  // the spot your last tap chose, at this table; yours stands round it, at
  // its full size, whatever room its zone by your hand has
  const home = tapped && tapped.room === state.room ? tapped.spot : null;
  const myPx = companionSize(size.base, levelIndex(levels[ours]), size.max);
  // what yours takes round a tapped home, as far as it wanders there: no
  // other seat's zone or step-out comes into it
  const homeKey = home ? `${home.x},${home.y},${myPx}` : "";
  const taken = useMemo(() => {
    if (!home) return null;
    const b = figureBox(home, myPx, true);
    const dx = Math.ceil(TAPPED_WIDE * myPx);
    const dy = Math.ceil(TAPPED_HIGH * myPx);
    return { x: b.x - dx, y: b.y - dy, w: b.w + 2 * dx, h: b.h + 2 * dy };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [homeKey]);
  // the zones, worked out again only when the layout, the people, their sizes or a tapped home change
  const seatsKey = JSON.stringify(people.map((p) => [p.seat, p.team]));
  const zones = useMemo(() => (layout ? zonesFor(people.map((p) => ({
    pos: SIDES[(p.seat - state.you + 4) % 4], size: companionSize(size.base, levelIndex(levels[p.team]), size.max),
    tag: p.seat === state.you })), taken ? { ...layout, obstacles: [...layout.obstacles, taken] } : layout) : null),
  // eslint-disable-next-line react-hooks/exhaustive-deps
  [layout, seatsKey, state.you, size.base, size.max, levels[0], levels[1], taken]);
  const mine = me && !me.is_bot && !me.left ? zones?.bottom ?? null : null;
  // where yours may go off its zone (a tap, or stepping off cards there):
  // clear of the other companions' zones as well as the table
  // and for each seat, the table with every other seat's zone in it: where a
  // special drawn larger must stay clear
  // (with where each stands: a tapped home, a step out of a covered zone)
  const rooms = useMemo(() => {
    if (!layout || !zones) return null;
    const boxes = (pos: SeatPos) => {
      const own = zones[pos].spots.map((s) => figureBox(s, zones[pos].size ?? size.base, pos === "bottom"));
      const out = strays[pos];
      if (out) own.push(figureBox(out.spot, out.px, pos === "bottom"));
      if (pos === "bottom" && taken) own.push(taken);
      return own;
    };
    const out = {} as Record<SeatPos, Layout>;
    for (const pos of SIDES) out[pos] = { ...layout, obstacles: [...layout.obstacles, ...SIDES.filter((q) => q !== pos).flatMap(boxes)] };
    return out;
  }, [layout, zones, size.base, strays, taken]);
  const roam = rooms?.bottom ?? null;

  // a tap on empty felt walks yours to the clear spot nearest the tap: yours
  // drawn anywhere (by your hand, on a tapped home, stepped out) takes it
  const out = strays.bottom?.spot ?? null;
  const tapState = useRef({ layout: roam, mine, home, out, px: myPx, last: -Infinity, n: 0 });
  tapState.current.out = out;
  tapState.current.layout = roam;
  tapState.current.mine = mine;
  tapState.current.home = home;
  tapState.current.px = myPx;
  useEffect(() => {
    const felt = root.current?.parentElement;
    if (!on || !felt) return;
    const tap = (e: Event) => {
      const at = tapState.current;
      const target = e.target as Element | null;
      // under Reduce Motion nothing walks: yours stays at home
      if (!at.layout || !at.mine || !(at.home ?? at.mine.home ?? at.out) || !target || target.closest(NOT_FELT) || prefersReducedMotion()) return;
      // a tap while a menu or panel is open closes it, or is for it: yours stays
      if (panelAtDown || document.querySelector(PANELS)) return;
      const now = Date.now();
      if (now - at.last < TAP_THROTTLE_MS) return;
      const f = framed(felt, felt.getBoundingClientRect());
      const { clientX, clientY } = e as globalThis.MouseEvent;
      const p = framedPoint(felt, clientX, clientY);
      const px = at.px;
      const spot = nearestClear({ x: p.x - f.x, y: p.y - f.y }, px, true, at.layout);
      if (!spot) return;
      at.last = now;
      setGoal({ spot, n: ++at.n });
    };
    // whether a panel was open as the tap began, before the tap closes it
    let panelAtDown = false;
    const down = () => { panelAtDown = document.querySelector(PANELS) !== null; };
    document.addEventListener("pointerdown", down, true);
    felt.addEventListener("click", tap);
    return () => { document.removeEventListener("pointerdown", down, true); felt.removeEventListener("click", tap); };
  }, [on, size.base]);

  if (!on) return null;
  const end = (seat: number) => () => setPoses((p) => ({ ...p, [seat]: "idle" }));
  // a tap's goal is cleared once yours has taken it, so no later render replays it
  const takeGoal = (n: number) => setGoal((g) => (g && g.n === n ? null : g));
  const takeHome = (s: Spot | null) => setTapped(s ? { room: state.room, spot: s } : null);
  const stepped = (pos: SeatPos, px: number) => (s: Spot | null) => setStrays((m) => {
    const was = m[pos];
    if (s ? was && was.spot.x === s.x && was.spot.y === s.y && was.px === px : !was) return m;
    const next = { ...m };
    if (s) next[pos] = { spot: s, px }; else delete next[pos];
    return next;
  });
  return (
    <div className="table-companions" ref={root} aria-hidden="true">
      {layout && zones ? people.map((p) => {
        const pos = SIDES[(p.seat - state.you + 4) % 4];
        const zone = zones[pos];
        const you = p.seat === state.you;
        return (
          <Walker key={p.seat} player={p} team={p.team === ours ? "us" : "them"}
                  px={you && home ? myPx : zone.size ?? companionSize(size.base, levelIndex(levels[p.team]), size.max)}
                  pos={pos} zone={zone} layout={layout} roam={rooms ? rooms[pos] : layout} pose={poses[p.seat] ?? "idle"}
                  up={ups[p.seat] ?? null} you={you} goal={you ? goal : null} tapped={you ? home : null}
                  wins={p.team === ours ? wins : 0} dealing={state.phase === "deal"} onEnd={end(p.seat)} onUpEnd={done(p.seat)}
                  onGoal={you ? takeGoal : undefined} onTapped={you ? takeHome : undefined}
                  onStray={stepped(pos, you && home ? myPx : zone.size ?? companionSize(size.base, levelIndex(levels[p.team]), size.max))} />
        );
      }) : null}
    </div>
  );
}
