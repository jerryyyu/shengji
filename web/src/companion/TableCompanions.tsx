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
// a trick, and cheer when the trick is worth 10 points or more. They answer
// the game (`beats.ts`): yours gets ready as your turn arrives (a jump, then
// held a little larger with a few small bobs until you play); each turns or
// leans to watch a card played; a trick of 20 points or more is a two-bounce
// jump for its winners and a droop for the others, a tractor led is its
// team's two quick hops, and a kitty taken on the last trick is the takers'
// special once the sheet has closed. A
// companion sleeps while its person is away. Between moves they stand
// still, each with a short fidget every 6 to 10 s on its own clock (a sway,
// a blink, a small hop, in turn), so a table at rest draws almost no
// frames; a hidden page moves nothing, and Reduce Motion stills everything.
// Every move is a transform of a box round a still drawing, never of the
// drawing's parts. A bot, and a seat its owner left, has none.
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { MouseEvent, RefObject } from "react";
import type { CompanionShare, GameState, StatePlayer } from "../protocol";
import { useAuth } from "../auth";
import { prefersReducedMotion } from "../motion";
import { useMediaQuery, TABLET_SCREEN } from "../phoneLayout";
import { Companion } from "./Companion";
import { DRAWINGS } from "./kinds";
import type { Pose } from "./Companion";
import { useCollection } from "./feature";
import { parseLook } from "./look";
import { shownAtTable, useCompanionMode } from "./mode";
import { countPoke, countWalk } from "./usage";
import { BEAT_MAX, BIG, BeatLog, CHUGS, DROOPS, GROW, LOOK_BACK_MS, LOOK_MS, PERKS, READY_BOB, READY_BOBS, READY_BOB_GAP_MS, READY_HELD, READY_JUMP_GAP_MS, READY_SCALE, RELAX,
  aim, canWatch, facingCss, fits, kittyCapture, lastPlay, lookFrames, lungeFor, lungeFrames, pickBeat, reactions, sameFacing, underBudget, yourTurn } from "./beats";
import { ARRIVES, GAITS, GOLD_LEVEL, LUNGERS, PLAIN_GAIT, QUIRKS, accentPieces, burstPieces, cuePieces, droopPiece, entrancePieces, gaitFrames, materialOf, restPieces,
  showerPieces, trailPieces, walkAt } from "./flair";
import type { Material, Piece, Stance } from "./flair";
import { useCue, useFlairLayer } from "./flairHooks";
import type { FlairLayer, Tag } from "./flairLayer";
import type { Beat, Facing, TableMove } from "./beats";
import { HAND_LIFT, LIFT, clear, figureBox, nearest, nearestClear, nextSpot, pathClear, TAPPED_HIGH, TAPPED_WIDE, zoneAround, zonesFor } from "./seatZones";
import type { Layout, Rect, SeatPos, Spot, Zone } from "./seatZones";
import { useT } from "../i18n";
import { LEVELS, companionSize } from "./rig";
import "./tableCompanions.css";
import type { Team } from "./rig";

/** A team's level as the index companions grow by (2 is 0, A is 12). */
export const levelIndex = (rank: string | undefined): number => Math.max(0, LEVELS.indexOf((rank ?? "2") as (typeof LEVELS)[number]));

export { CHEER_POINTS } from "./beats";
/** The fidget's length, and the shortest and longest wait before the next. */
export const FIDGET_MS = 600;
const FIDGET_GAP: readonly [number, number] = [6000, 10000];

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
function play(el: HTMLElement | null, name: keyof typeof MOVES | "levelup" | Beat, from = 1, frames: Keyframe[] | null = null): { done: Promise<void>; stop: () => void } {
  const m = typeof name !== "string" ? name
    : name === "levelup" ? { frames: levelUpFrames(from), ms: LEVEL_UP_MS, easing: "linear" }
    : frames ? { ...MOVES[name], frames } : MOVES[name];
  if (!el || typeof el.animate !== "function" || prefersReducedMotion()) {
    let timer = 0;
    // a move with a held pose (the droop) stands in it for its still length
    const held = typeof name !== "string" && el ? name.still : undefined;
    const was = el?.style.transform ?? "";
    if (held && el) el.style.transform = held;
    const done = new Promise<void>((r) => { timer = window.setTimeout(r, name === "levelup" ? m.ms : held ? STILL_BEAT_MS : Math.min(m.ms, FIDGET_MS)); })
      .then(() => { if (held && el) el.style.transform = was; });
    return { done, stop: () => { window.clearTimeout(timer); if (held && el) el.style.transform = was; } };
  }
  const a = el.animate(m.frames, { duration: m.ms, easing: m.easing });
  return { done: a.finished.then(() => undefined, () => undefined), stop: () => a.cancel() };
}

/** How long a move's held pose stands under Reduce Motion. */
export const STILL_BEAT_MS = 1000;
/** How soon a fidget or walk that fell due mid-move looks again. */
const RETRY_MS = 1000;
/** The fidgets a companion at rest plays in turn. */
const FIDGETS = ["sway", "blink", "nudge", "habit"] as const;
/** How long a blink keeps the eyes shut. */
const BLINK_MS = 160;

/** A companion at rest fidgets once every 6 to 10 s, on its own clock, while
 *  the page is shown and motion is allowed: a sway, a blink, a small hop and
 *  its own habit (`habit`: its beat where it fits, else the sway), in
 *  turn. A blink shuts a still drawing's eyes for a moment (`onBlink`). */
function useFidget(el: RefObject<HTMLSpanElement | null>, on: boolean, onBlink: (shut: boolean) => void, habit: () => Beat | null): void {
  const blink = useRef(onBlink);
  blink.current = onBlink;
  const own = useRef(habit);
  own.current = habit;
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
        running = play(el.current, kind === "sway" ? "fidget" : kind === "nudge" ? "nudge" : own.current() ?? "fidget");
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
/** How long the spot a figure stepped out from must stay clear before it
 *  walks back: an obstacle that comes and goes does not walk it out and back. */
export const RETURN_MS = 1000;
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
  + ".timer-ring, .opponent, .last-trick-btn, .last-trick-panel, .deal-deck, .deal-deck-count, .hand-line, "
  + ".watch-controls, .watch-tabs, .watch-kitty, .watch-own";
/** Of those, what stays put while a hand is dealt: your name pill and your row's controls (Declare and its options among them). */
const FIXED = ".you-tagline, .you-row .btn, .action-bar .btn, .action-bar > *, .timer-ring";
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

/** Where each side seat's played cards and their label have landed at this
 *  felt size, kept as one box per seat: no figure stands there, so the left
 *  and right seats' companions are not chased off by every card their
 *  person plays. Only a trick's plays (`[data-play]`) are kept; a
 *  declaration shown for a moment stays an obstacle only while it is up.
 *  A new felt size forgets them. */
interface Slots { size: string; seen: Partial<Record<"left" | "right", Rect>> }
const union = (a: Rect, b: Rect): Rect => {
  const x = Math.min(a.x, b.x), y = Math.min(a.y, b.y);
  return { x, y, w: Math.max(a.x + a.w, b.x + b.w) - x, h: Math.max(a.y + a.h, b.y + b.h) - y };
};
/** Whether a played card's wrapper is still flying in (it carries a transform until it lands). */
const inFlight = (e: Element): boolean => {
  const t = getComputedStyle(e).transform;
  return !!t && t !== "none" && t !== "matrix(1, 0, 0, 1, 0, 0)";
};

function measure(felt: HTMLElement, phone = false, dealing = false, insets: SafeEdges | null = null,
  seen: ((e: Element, b: DOMRect) => void) | null = null, slots: Slots | null = null): Layout {
  const fb = felt.getBoundingClientRect();
  seen?.(felt, fb);
  const f = framed(felt, fb);
  const rel = (e: Element): Rect => {
    const raw = e.getBoundingClientRect();
    seen?.(e, raw);
    const b = framed(e, raw);
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
  const fixed = [...felt.querySelectorAll(FIXED)].map(rel).filter((r) => r.w > 2 && r.h > 2);
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
  const inset = safeReach(insets ?? safeEdges(felt), f);
  const x0 = Math.max(plates.left?.x ?? 0, inset.l);
  const x1 = Math.min(plates.right ? plates.right.x + plates.right.w : f.w, f.w - inset.r);
  const safe = plates.left && plates.right || inset.l > 0 || inset.r > 0 ? { x0, x1 } : undefined;
  if (slots) {
    const size = `${Math.round(f.w)}x${Math.round(f.h)}`;
    if (slots.size !== size) { slots.size = size; slots.seen = {}; }
    for (const pos of ["left", "right"] as const) {
      const play = felt.querySelector(`.trick-play[data-play].pos-${pos}`);
      if (play && !inFlight(play)) {
        const boxes = [play, ...play.querySelectorAll(".trick-tag")].map(rel).filter((r) => r.w > 2 && r.h > 2);
        for (const r of boxes) slots.seen[pos] = slots.seen[pos] ? union(slots.seen[pos], r) : r;
      }
      const kept = slots.seen[pos];
      if (kept) obstacles.push(kept);
    }
  }
  if (inset.t > 0) obstacles.push({ x: 0, y: 0, w: f.w, h: inset.t });
  if (inset.b > 0) obstacles.push({ x: 0, y: f.h - inset.b, w: f.w, h: inset.b });
  return { felt: { w: f.w, h: f.h }, plates, tagline: one(".you-tagline"), row: one(".you-row"), hand: first,
           ...(safe ? { safe } : {}), ...(phone ? { phone } : {}), obstacles, fixed };
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

/** The screen's safe-area insets (a notch, the Dynamic Island), in px:
 *  read off a probe padded by `env(safe-area-inset-*)`. A rotated table's
 *  insets are its frame's, so it reads none. They change only with the
 *  window's size or turn, so the table reads them once for each. */
interface SafeEdges { l: number; r: number; t: number; b: number }
function safeEdges(felt: HTMLElement): SafeEdges {
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
  return raw;
}

/** How far the safe-area insets reach into the felt `f`, each with
 *  `SAFE_MARGIN` more, in px (0 where there is none). */
function safeReach(raw: SafeEdges, f: Rect): SafeEdges {
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
function Walker({ player, team, px, pos, zone, layout, roam, pose, up, you, goal, tapped, wins, poke = 0, dealing, ready, watch, flair = null, gold = false, arrives = false, onEnd, onUpEnd, onGoal, onTapped, onStray, onSpecial }: {
  /** The felt's layer of pieces, for a store character's material; null where none is painted. */
  flair?: FlairLayer | null;
  /** Its team stands at the level from which a trail's pieces turn part gold. */
  gold?: boolean;
  /** It is drawn onto a table already shown (its person sat down), so it comes in its own way; a table opened or reconnected into draws everyone settled. */
  arrives?: boolean;
  player: StatePlayer; team: Team; px: number; pos: SeatPos; dealing: boolean;
  ready: boolean; watch: { pos: SeatPos; key: string } | null;
  zone: Zone; layout: Layout; roam: Layout; pose: TableMove; up: LevelUp | null; you: boolean; goal: { spot: Spot; n: number } | null;
  tapped: Spot | null; wins: number; onEnd: () => void; onUpEnd: () => void; onGoal?: (n: number) => void;
  onTapped?: (s: Spot | null) => void; onStray?: (s: Spot | null) => void;
  /** Another seat's person played its special for the table: each new value plays it here. */
  poke?: number;
  /** Yours played its special on a tap, for the table to see. */
  onSpecial?: () => void;
}) {
  const t = useT();
  const { kind, colour } = parseLook(player.look);
  const away = !player.connected || player.away === true;
  const move: TableMove = away ? "sleep" : pose;
  const walk = useRef<HTMLSpanElement | null>(null);
  // how it faces and leans now, the turn in flight, and when its moves started
  const facing = useRef<Facing>({ dir: pos === "right" ? -1 : 1, lean: 0, up: false });
  const looking = useRef<Animation | null>(null);
  const beats = useRef<BeatLog | null>(null);
  beats.current ??= new BeatLog();
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
  // a walk back to its zone waits RETURN_MS: `waiting` is the wait (its
  // timer, 0 while the way home is blocked), the home it is for and whether
  // the way there was open as it began, `settled`
  // counts each wait that ran out, and `back` is set as one does, so the
  // next look at the zone walks back
  const [settled, setSettled] = useState(0);
  const back = useRef(false);
  const waiting = useRef<{ timer: number; to: Spot; open: boolean } | null>(null);
  const unwait = () => { if (waiting.current) window.clearTimeout(waiting.current.timer); waiting.current = null; };
  useEffect(() => unwait, []);
  // a tapped home stands on its own: the zone only matters without one; a
  // drawn figure stays drawn until it has been moved or taken off
  const placed = (tapped ?? zone.home ?? stray ?? cur.current) !== null;
  // ready while the table waits on its person, between the other moves
  const readyOn = ready && placed && !away && move === "idle" && !up && !playing && !dealing;
  useFidget(box, placed && move === "idle" && !up && !playing && !readyOn, setBlink, () => {
    const s = cur.current;
    return s && fits(QUIRKS[kind].frames, s, px, you, roamNow.current) ? QUIRKS[kind] : null;
  });
  // a store character's material: its pieces start from where it stands
  const material: Material | null = flair ? materialOf(kind) : null;
  const owner = String(player.seat);
  // the walk in flight as the walk itself has it, so a moment mid-walk starts from where the figure is drawn
  const flying = useRef<{ from: Spot; to: Spot; via: Spot | null; share: number; t0: number; ms: number } | null>(null);
  const drawnAt = (): Spot | null => {
    const f = flying.current;
    return f ? walkAt(f.from, f.to, Math.min(1, (performance.now() - f.t0) / f.ms), f.via, f.share) : cur.current;
  };
  const emit = (tag: Tag, make: (m: Material, s: Stance) => Piece[], k = 1) => {
    const s = drawnAt();
    if (!flair || !material || !s || away) return;
    flair.spawn(owner, you, tag, make(material, { x: s.x + px / 2, y: s.y + px, px: px * k, dir: facing.current.dir, colour, gold }));
  };
  // the trail's pieces still to come from the walk in flight, how many hops have dropped some, and how many pieces
  const trailing = useRef<number[]>([]);
  const hopped = useRef(0);
  const dropped = useRef(0);

  const stop = () => {
    for (const a of walking.current) a.cancel();
    walking.current = [];
    path.current = null;
    flying.current = null;
    for (const id of trailing.current) window.clearTimeout(id);
    trailing.current = [];
  };
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
    looking.current?.cancel();
    facing.current = { dir, lean: 0, up: false };
    if (face.current) face.current.style.transform = `scaleX(${dir})`;
    const a = el.animate(via && dist > 0 ? [{ transform: at(from) }, { transform: at(via), offset: leg / dist }, { transform: at(to) }]
      : [{ transform: at(from) }, { transform: at(to) }], { duration: ms, easing: "ease-in-out" });
    // a whole number of hops, at least one, fitted to the walk's time, so
    // the feet are on the ground as it arrives and no hop runs on after it
    // the gait is the companion's own; a quick step aside keeps the plain hop
    const own = quick ? PLAIN_GAIT : GAITS[kind];
    const step = quick ? QUICK_STEP_MS : own.step;
    const hops = Math.max(1, Math.round(ms / step));
    const gait = face.current?.animate(gaitFrames(own, dir), { duration: ms / hops, iterations: hops });
    walking.current = gait ? [a, gait] : [a];
    const flight = { from, to, via, share: via && dist > 0 ? leg / dist : 0, t0: performance.now(), ms };
    flying.current = flight;
    if (material && flair) {
      // the trail: pieces behind it as each hop lands (one for a step aside),
      // from where the walk has it then, worked out from the walk itself
      const drops = quick ? 1 : Math.max(1, Math.round(ms / STROLL_STEP_MS));
      const share = via && dist > 0 ? leg / dist : 0;
      const long = { x: (to.x - from.x) / (dist || 1), y: (to.y - from.y) / (dist || 1) };
      for (let k = 1; k <= drops; k++) {
        trailing.current.push(window.setTimeout(() => {
          const p = walkAt(from, to, k / drops, via, share);
          const was = walkAt(from, to, Math.max(0, k / drops - 0.06), via, share);
          const gone = Math.hypot(p.x - was.x, p.y - was.y);
          const u = gone > 0.5 ? { x: (p.x - was.x) / gone, y: (p.y - was.y) / gone } : long;
          const n = quick || !you ? 1 : k === drops ? 3 : ++hopped.current % 2 ? 3 : 2;
          flair.spawn(owner, you, "trail", trailPieces(material, { x: p.x + px / 2, y: p.y + px, px, dir, colour, gold }, u, n, dropped.current));
          dropped.current += n;
        }, (k * ms) / drops));
      }
    }
    path.current = under ? null : { from, to };
    place(to);
    void a.finished.then(() => {
      if (flying.current === flight) flying.current = null;
      walking.current = walking.current.filter((x) => x !== a);
      if (path.current?.to === to) path.current = null;
    }, () => {});
    if (gait) void gait.finished.then(() => { walking.current = walking.current.filter((x) => x !== gait); }, () => {});
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
    // must, once the deal is done. What does not fly (your name pill, the
    // declare options the deal brings up) it steps off at once
    if (dealing && drawn && clear(now, px, you, { ...room, obstacles: room.fixed ?? [] })) return;
    const quick = { under: true, quick: true };
    const due = back.current;
    back.current = false;
    // the wait for a walk back runs on only while the figure still waits for it
    let kept = false;
    step();
    if (!kept) unwait();
    function step() {
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
      const home = (tapped ?? zone.home)!;
      // clear where it stands but off its zone (it stepped out and the way
      // back opened): it walks back once RETURN_MS has passed with the same
      // home. Something appearing elsewhere does not start the wait again; a
      // way home that was open and is then blocked pauses it, and it starts
      // again once the way clears. A way blocked from the start (a nameplate
      // between) does not hold it: it walks back under, as any step does
      if (!tapped && drawn && !due && !path.current) {
        const near = nearest(here, now, false);
        const off = !near || Math.hypot(near.x - now.x, near.y - now.y) > px / 2;
        if (off && clear(now, px, you, room)) {
          kept = true;
          const open = pathClear(now, home, px, you, room);
          const w = waiting.current;
          const same = !!w && w.to.x === home.x && w.to.y === home.y;
          if (same && w.timer && (open || !w.open)) return;
          if (same && w.timer && !open) { window.clearTimeout(w.timer); w.timer = 0; return; }
          if (same && !w.timer && !open) return;
          unwait();
          const timer = window.setTimeout(() => { waiting.current = null; back.current = true; setSettled((n) => n + 1); }, RETURN_MS);
          waiting.current = { timer, to: home, open };
          return;
        }
      }
      if (stray) setStray(null);
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
    }
  }, [zone, here, layout, roam, px, you, dealing, settled]);

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
    beats.current!.note(Date.now());
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
  const idle = placed && move === "idle" && !up && !playing && !dealing && !readyOn;
  const idleNow = useRef(idle);
  idleNow.current = idle;
  // the clock outlives the render it was set in: it walks with the walk as it is now (the layer of pieces may have come since)
  const walkNow = useRef(goTo);
  walkNow.current = goTo;
  useEffect(() => {
    if (!placed || prefersReducedMotion()) return;
    let timer = 0;
    const due = () => {
      if (!idleNow.current || walking.current.length > 0) { timer = window.setTimeout(due, RETRY_MS); return; }
      // a figure that has done its share this minute stands until the next look
      if (!underBudget(beats.current!, Date.now(), you)) { wait(); return; }
      const from = cur.current;
      // a spot it can reach without crossing anything; it stays put when none is
      for (let i = 0; from && i < 6; i++) {
        const to = nextSpot(zoneNow.current, from, px, Math.random());
        if (to && pathClear(from, to, px, you, roomNow.current)) { beats.current!.note(Date.now()); walkNow.current(to); break; }
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
  // a store character's idle cue, on its own clock, while it stands at rest
  const restful = useRef(false);
  restful.current = idle && walking.current.length === 0 && !away;
  useCue(placed && !!material, restful, () => emit("cue", cuePieces));
  // its way in, once, as it is drawn onto a table already shown: never as
  // the table itself is first drawn, while the hand is dealt, on a hidden
  // page or under Reduce Motion
  const entered = useRef(false);
  const owed = useRef(false);
  const comes = useRef(arrives);
  useEffect(() => {
    if (!placed || entered.current) return;
    entered.current = true;
    if (!comes.current || dealing || away || prefersReducedMotion() || document.visibilityState === "hidden") return;
    const beat = pickBeat(ARRIVES[kind], cur.current, px, you, roamNow.current);
    const run = beat ? play(box.current, beat) : null;
    // a store character's entrance comes with it, once the felt's layer of pieces is there to paint it
    owed.current = materialOf(kind) !== null;
    return () => run?.stop();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [placed]);
  // the first store character at a table brings the layer with it, so its entrance waits a render for it
  useEffect(() => {
    if (!owed.current || !flair) return;
    owed.current = false;
    emit("entrance", (m, s) => entrancePieces(m, s, you ? 8 : 4));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [flair, placed]);
  // under Reduce Motion its material is three pieces lying still at its feet
  useEffect(() => {
    const s = cur.current;
    if (!flair || !material || !placed || !s || away || !prefersReducedMotion()) return;
    flair.rest(owner, restPieces(material, { x: s.x + px / 2, y: s.y + px, px, dir: facing.current.dir, colour, gold }));
    return () => flair.rest(owner, null);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [flair, material, placed, away, zone, here, layout, roam, px, colour, gold]);
  // a walk in flight as the deal starts goes on to where it was going at a
  // stroll, from where it is drawn: no quick hop runs on into the deal, and
  // nothing snaps
  useEffect(() => {
    if (!dealing || walking.current.length === 0 || !cur.current) return;
    goTo(cur.current, { under: true });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dealing]);

  /** Turn the face box to `to`: at once under Reduce Motion (the held pose)
   *  or while hidden, else over `ms`, with a turn's small rise (`hop`). */
  const faceTo = (to: Facing, ms: number, hop: boolean) => {
    const el = face.current;
    const from = facing.current;
    if (!el || sameFacing(from, to)) return;
    facing.current = to;
    looking.current?.cancel();
    looking.current = null;
    el.style.transform = facingCss(to);
    if (typeof el.animate !== "function" || prefersReducedMotion() || document.visibilityState === "hidden") return;
    looking.current = el.animate(lookFrames(from, to, hop), { duration: ms, easing: "ease-out" });
  };
  /** Stand straight again, facing the same way: a lean is held only between the other moves. */
  const straighten = () => faceTo({ dir: facing.current.dir, lean: 0, up: false }, LOOK_BACK_MS, false);
  useEffect(() => () => looking.current?.cancel(), []);

  // a card played: it turns or leans to watch the seat that played it, and
  // stands straight again as the trick is collected. Not for its own
  // person's card, mid-move or mid-walk, more often than `WATCH_GAP_MS`, or
  // past its share of moves this minute
  const watchKey = watch?.key ?? "";
  const busy = !placed || away || !!up || playing || dealing || readyOn || move !== "idle";
  const busyNow = useRef(busy);
  busyNow.current = busy;
  useEffect(() => {
    if (!watch) { straighten(); return; }
    const s = cur.current;
    if (watch.pos === pos || busyNow.current || !s || walking.current.length > 0) return;
    const now = Date.now();
    if (!canWatch(beats.current!, now, you)) return;
    const to = aim(s, px, you, facing.current, watch.pos, team === "us", roamNow.current);
    if (sameFacing(to, facing.current)) return;
    beats.current!.note(now);
    faceTo(to, LOOK_MS, true);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [watchKey]);

  // ready: as the turn arrives it jumps (as high as stays clear) and lands a
  // little larger, bobs a few times, and holds that size until the turn
  // passes; a turn back within 8 s only grows, with no jump or bob; under
  // Reduce Motion only the held size. The size is the box's
  // own style, so nothing runs while it is held
  const calm = useRef({ up: !!up, playing });
  calm.current = { up: !!up, playing };
  const held = useRef(false);
  const jumped = useRef(-Infinity);
  useEffect(() => {
    const el = box.current;
    if (!readyOn || !el) return;
    straighten();
    held.current = true;
    el.style.transform = READY_HELD;
    // a turn that comes round again within `READY_JUMP_GAP_MS`, or to a figure that has done its most this minute, only grows
    const now = Date.now();
    const jump = now - jumped.current >= READY_JUMP_GAP_MS && beats.current!.count(now) < BEAT_MAX;
    if (jump) { jumped.current = now; beats.current!.note(now); }
    const moving = typeof el.animate === "function" && !prefersReducedMotion();
    const runs: Animation[] = [];
    const timers: number[] = [];
    if (moving && document.visibilityState !== "hidden") {
      const perk = (jump ? pickBeat(PERKS, cur.current, px, you, roamNow.current) : null) ?? GROW;
      runs.push(el.animate(perk.frames, { duration: perk.ms, easing: perk.easing }));
      for (let i = 1; jump && i <= READY_BOBS; i++) {
        timers.push(window.setTimeout(() => {
          const s = cur.current;
          if (document.visibilityState === "hidden" || !s || !fits(READY_BOB.frames, s, px, you, roamNow.current)) return;
          runs.push(el.animate(READY_BOB.frames, { duration: READY_BOB.ms, easing: READY_BOB.easing }));
        }, perk.ms + i * READY_BOB_GAP_MS - READY_BOB.ms));
      }
    }
    return () => {
      for (const t of timers) window.clearTimeout(t);
      for (const a of runs) a.cancel();
      held.current = false;
      el.style.transform = "";
      // a level-up or a special that takes over starts from the held size itself
      if (moving && el.isConnected && document.visibilityState !== "hidden" && !calm.current.up && !calm.current.playing) {
        el.animate(RELAX.frames, { duration: RELAX.ms, easing: RELAX.easing });
      }
    };
  // the jump's height is read where it stands as the turn arrives
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [readyOn]);

  useEffect(() => {
    if (move === "idle" || move === "sleep" || move === "react") return;
    straighten();
    beats.current!.note(Date.now());
    const s = cur.current;
    // a hop as high as stays clear where it stands; a big jump only where it
    // has the room, else the cheer; the droop and the tractor's hops at the
    // largest that stays clear
    const run = move === "hop" ? play(box.current, "hop", 1, hopFrames(hopPeak(s, px, you, roamNow.current)))
      : move === "cheer" ? play(box.current, "cheer")
      : move === "big" ? play(box.current, pickBeat([BIG], s, px, you, roamNow.current) ?? "cheer")
      : play(box.current, pickBeat(move === "droop" ? DROOPS : CHUGS, s, px, you, roamNow.current) ?? (move === "droop" ? DROOPS[DROOPS.length - 1] : CHUGS[CHUGS.length - 1]));
    // a store character marks a big play with a burst of its own, and a big trick lost with one falling piece
    if (move === "big" && !prefersReducedMotion()) emit("burst", (m, st) => burstPieces(m, st, you ? 7 : 3, BIG.ms * 0.2));
    if (move === "droop" && !prefersReducedMotion()) emit("burst", droopPiece);
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
    emit("shower", (m, st) => showerPieces(m, st, you ? 6 : 3));
  }, [wins, up, placed, away]);
  // another seat's special, shared by its person: played as theirs plays it
  const poked2 = useRef(poke);
  useEffect(() => {
    if (poke <= poked2.current) return;
    poked2.current = poke;
    if (up || !placed || away || playing) return;
    setSpecial((n) => n + 1);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [poke]);
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
    beats.current!.note(Date.now());
    const a = k > 1 && el && typeof el.animate === "function"
      ? el.animate([{ transform: held.current ? READY_HELD : "scale(1)" }, { transform: `scale(${k})`, offset: 0.15 }, { transform: `scale(${k})`, offset: 0.85 },
                    { transform: "scale(1)" }], { duration: ms, easing: "ease-in-out" })
      : null;
    // a special that charges moves the figure itself, as far as stays clear;
    // a store character's accent rides on the special's own beats
    const charge = !still && LUNGERS.has(kind) && walking.current.length === 0 && typeof walk.current?.animate === "function"
      ? lungeFor(s, px, you, facing.current.dir, roamNow.current, k) : { reach: 0, back: 0 };
    const lunge = s && charge.reach > 0 ? walk.current!.animate(lungeFrames(s, facing.current.dir, charge), { duration: ms }) : null;
    if (!still) for (const at of material?.accent.times ?? []) emit("burst", (m, st) => accentPieces(m, st, charge.reach, at, you), k);
    return () => { window.clearTimeout(timer); a?.cancel(); lunge?.cancel(); setPlaying(false); };
  }, [special, kind]);
  const nudging = useRef<{ stop: () => void } | null>(null);
  useEffect(() => () => nudging.current?.stop(), []);
  const poked = (e: MouseEvent) => {
    e.stopPropagation();
    if (!you || away || playing || up) return;
    // a tap while the special cools down still answers, with a small hop
    if (Date.now() - lastSpecial.current < SPECIAL_COOLDOWN_MS) {
      countPoke(false);
      if (!prefersReducedMotion()) { nudging.current?.stop(); nudging.current = play(box.current, held.current ? READY_BOB : "nudge"); }
      return;
    }
    countPoke(true);
    setSpecial((n) => n + 1);
    onSpecial?.();
  };

  const drawn: Pose = away ? "sleep" : up ? "cheer" : playing ? "react" : move === "big" ? "cheer" : move === "droop" || move === "chug" ? "idle" : move;
  // the tag rides up with a figure standing larger
  const lift = readyOn ? { transform: `translate(-50%, -${Math.ceil(px * (READY_SCALE - 1))}px)` } : undefined;

  if (!placed) return null;
  return (
    <span className="tc-seat" data-seat={player.seat} data-pos={pos}>
      <span className={`tc-walk${you ? " tc-mine" : ""}`} ref={walk} onClick={you ? poked : undefined} data-ready={readyOn ? "" : undefined}>
        {you ? <span className="tc-you" style={lift}>{t("table.companionYou")}</span> : null}
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

/** What the walking zones are measured round: every obstacle and overlay,
 *  and the hand. */
const MEASURED = `${OBSTACLES}, ${OVERLAYS}, .hand`;
/** Whether a node added to or taken off the table is, or holds, something
 *  the zones are measured round. */
const measured = (n: Node): boolean => n instanceof Element && !n.closest(".table-companions")
  && (n.matches(MEASURED) || n.querySelector(MEASURED) !== null);

/** The walking zones, measured from the felt as the table first shows
 *  them and as the cards, the phase or the layout change (and twice more
 *  as cards finish flying in), and on the next frame whenever something
 *  they are measured round appears, goes or changes size, or the window
 *  changes size or turns. A measure asked for while one is already due
 *  this frame is the same one; a commit that touches none of them
 *  measures nothing. */
function useLayout(root: RefObject<HTMLDivElement | null>, on: boolean, key: string, phone = false, dealing = false): Layout | null {
  const [layout, setLayout] = useState<Layout | null>(null);
  // what a measure reads as it runs, so a change of them only asks for one
  const opts = useRef({ phone, dealing });
  opts.current = { phone, dealing };
  // measures now, or on the next frame; null while the table is not watched
  const ask = useRef<{ now: () => void; soon: () => void; flying: () => boolean } | null>(null);
  useLayoutEffect(() => {
    if (!on) return;
    const felt = root.current?.parentElement;
    if (!felt) return;
    const screen = felt.closest(".table-screen") ?? felt;
    // the safe-area insets, read once for each window size and turn
    let insets: SafeEdges | null = null;
    // the side seats' landed cards, kept for this felt size
    const slots: Slots = { size: "", seen: {} };
    // a measure that finds nothing moved keeps the layout as it was
    let last = "";
    let ro: ResizeObserver | null = null;
    // each watched box's size as the last measure (or the observer) saw it:
    // a box the observer reports at that size asks for no measure
    const sizes = new WeakMap<Element, string>();
    const size = (w: number, h: number) => `${Math.round(w)}x${Math.round(h)}`;
    const note = (e: Element, b: DOMRect) => { sizes.set(e, size(b.width, b.height)); };
    const watched = new WeakSet<Element>();
    const watch = () => {
      if (!ro) return;
      for (const e of [felt, ...felt.querySelectorAll(MEASURED), ...screen.querySelectorAll(OVERLAYS)]) {
        if (!e.closest(".table-companions") && !watched.has(e)) { watched.add(e); ro.observe(e); }
      }
    };
    let frame = 0;
    // the changes queued before a measure are in it: it takes them, so
    // they ask for no other; ones queued after it still do
    let mo: MutationObserver | null = null;
    const read = () => {
      window.cancelAnimationFrame(frame);
      frame = 0;
      mo?.takeRecords();
      insets ??= safeEdges(felt);
      const next = measure(felt, opts.current.phone, opts.current.dealing, insets, ro ? note : null, slots);
      watch();
      const seen = JSON.stringify(next);
      if (seen === last) return;
      last = seen;
      setLayout(next);
    };
    const soon = () => { if (!frame) frame = window.requestAnimationFrame(read); };
    // whether cards are still flying in: their wrappers carry a transform until they land
    const flying = () => [...felt.querySelectorAll(".trick-play")].some(inFlight);
    ask.current = { now: read, soon, flying };
    const resized = () => { insets = null; soon(); };
    if (typeof ResizeObserver === "function") {
      ro = new ResizeObserver((list) => {
        let changed = false;
        for (const e of list) {
          const box = e.borderBoxSize?.[0];
          const now = box ? size(box.inlineSize, box.blockSize) : size(e.contentRect.width, e.contentRect.height);
          if (sizes.get(e.target) !== now) changed = true;
          sizes.set(e.target, now);
        }
        if (changed) soon();
      });
    }
    read();
    window.addEventListener("resize", resized);
    window.addEventListener("orientationchange", resized);
    // a line, a control, a chat bubble or a panel that comes or goes:
    // never for the companions' own changes or for nodes that are none of those
    if (typeof MutationObserver === "function") {
      mo = new MutationObserver((list) => {
        if (!frame && list.some((m) => [...m.addedNodes, ...m.removedNodes].some(measured))) soon();
      });
      mo.observe(screen, { childList: true, subtree: true });
    }
    return () => {
      ask.current = null;
      window.cancelAnimationFrame(frame);
      window.removeEventListener("resize", resized); window.removeEventListener("orientationchange", resized);
      ro?.disconnect(); mo?.disconnect();
    };
  }, [root, on]);
  // the cards, the phase or the layout changed: measured before the frame
  // is drawn (a figure the cards will land on steps aside as they set off),
  // and while cards are flying in, once more as they land and again after
  // a slow flight
  const first = useRef(true);
  useLayoutEffect(() => {
    if (first.current) { first.current = false; return; }
    ask.current?.now();
    const again = () => { if (ask.current?.flying()) ask.current.soon(); };
    const later = window.setTimeout(again, 450);
    const slow = window.setTimeout(again, 1200);
    return () => { window.clearTimeout(later); window.clearTimeout(slow); };
  }, [key, phone, dealing]);
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

/** What each team's companions owe a round's end, counted once its sheet
 *  has closed and the table is in view (as a level gained is shown): a
 *  special for your team's round won and for the team that took the kitty
 *  on the last trick, and a droop (`onDroop`) for the team it was taken
 *  from when that team lost the round with it. */
function useRoundEnds(state: GameState, ours: 0 | 1, onDroop: (team: 0 | 1) => void): readonly [number, number] {
  const [specials, setSpecials] = useState<readonly [number, number]>([0, 0]);
  const pending = useRef<{ special: [boolean, boolean]; droop: 0 | 1 | null }>({ special: [false, false], droop: null });
  const droop = useRef(onDroop);
  droop.current = onDroop;
  const pageShown = usePageShown();
  const covered = state.phase === "round_end" || !pageShown;
  if (state.phase === "round_end" && state.round_result) {
    if (state.round_result.winner_team === ours) pending.current.special[ours] = true;
    const took = kittyCapture(state);
    if (took !== null) {
      pending.current.special[took] = true;
      pending.current.droop = state.round_result.winner_team === took ? ((1 - took) as 0 | 1) : null;
    }
  }
  useEffect(() => {
    if (covered) return;
    const { special, droop: lost } = pending.current;
    pending.current = { special: [false, false], droop: null };
    if (special[0] || special[1]) setSpecials((n) => [n[0] + (special[0] ? 1 : 0), n[1] + (special[1] ? 1 : 0)]);
    if (lost !== null) droop.current(lost);
  }, [covered]);
  return specials;
}

/** What a tap on the felt is not: a card, a played trick, a seat, a
 *  control, a panel, or a companion. */
const NOT_FELT = "button, a, input, textarea, select, label, [role='button'], [role='switch'], .card, .hand, .hand-line, "
  + ".trick-play, .opponent, .hud, .you-row, .action-bar, .deal-deck, .chat-panel, .modal, .panel, .last-trick-panel, .tc-walk";

/** `watch`: the watch screen's table, where the bottom seat is the player
 *  whose tab is selected, not you: nobody is tagged "You", a tap walks
 *  nobody, a seat whose look the feed left out draws none, and `quiet`
 *  (fast play, a step back, a turn to another seat) skips the hops. */
/** The companion moves the other seats' people shared (`companion`), the
 *  latest of each seat, with a count that tells one from the next. */
export type SharedMoves = Partial<Record<number, { act: "special" } & { n: number } | { act: "home"; x: number; y: number; n: number }>>;

/** A shared spot: a point of the felt's safe area from 0 to 1, so it lands
 *  on every screen in the same place of the table. */
function toShared(l: Layout, p: Spot): { x: number; y: number } {
  const x0 = l.safe?.x0 ?? 0, x1 = l.safe?.x1 ?? l.felt.w;
  const r = (v: number) => Math.round(Math.min(1, Math.max(0, v)) * 10000) / 10000;
  return { x: r((p.x - x0) / Math.max(1, x1 - x0)), y: r(p.y / Math.max(1, l.felt.h)) };
}
function fromShared(l: Layout, x: number, y: number): Spot {
  const x0 = l.safe?.x0 ?? 0, x1 = l.safe?.x1 ?? l.felt.w;
  return { x: x0 + x * (x1 - x0), y: y * l.felt.h };
}
/** The least time between two parked spots sent, a little over the
 *  server's one second, so none is dropped; a tap sooner waits and only the
 *  latest is sent once the time is up. */
export const HOME_SHARE_GAP_MS = 1100;

export default function TableCompanions({ state, watch = null, shared, onShare }: {
  state: GameState; watch?: { quiet: boolean } | null;
  /** The other seats' shared moves (`Table.tsx` reads them off the socket). */
  shared?: SharedMoves;
  /** Send one of yours to the table: its special on a tap, the spot a tap parked it. */
  onShare?: (m: CompanionShare) => void;
}) {
  const shown = useCollection();
  const account = useAuth();
  const mode = useCompanionMode(account.status === "in" ? account.user : null);
  const tablet = useMediaQuery(TABLET_SCREEN);
  const [poses, setPoses] = useState<Record<number, TableMove>>({});
  const bigAt = useRef({ big: -Infinity });
  // whether the table waits on you and the card it watches, as of the frame
  // whose reactions are in `poses`: getting ready and watching wait for it,
  // so a trick taken is hopped before either. A frame that changes neither
  // (every card of the deal) renders nothing more
  const [live, setLive] = useState<{ ready: boolean; play: { seat: number; key: string } | null }>({ ready: false, play: null });
  const [goal, setGoal] = useState<{ spot: Spot; n: number } | null>(null);
  // the spot your last tap chose: yours stays round it for the rest of this table
  const [tapped, setTapped] = useState<{ room: string; spot: Spot } | null>(null);
  // the other seats' shared moves as each figure takes them: a walk to the
  // spot its person parked it (then its home), and a count of its specials
  const [remoteGoals, setRemoteGoals] = useState<Record<number, { spot: Spot; n: number }>>({});
  const [remoteHomes, setRemoteHomes] = useState<{ room: string; at: Record<number, Spot> }>({ room: state.room, at: {} });
  const [pokes, setPokes] = useState<Record<number, number>>({});
  // where a figure whose whole zone is covered stepped out to, by seat
  const [strays, setStrays] = useState<Partial<Record<SeatPos, { spot: Spot; px: number }>>>({});
  const prev = useRef<GameState | null>(null);
  const root = useRef<HTMLDivElement | null>(null);
  // whether the table's figures have been drawn once: one drawn after that comes in its own way
  const drawn = useRef(false);
  const flairBack = useRef<HTMLCanvasElement | null>(null);
  const flairFront = useRef<HTMLCanvasElement | null>(null);
  const quiet = watch?.quiet ?? false;
  const watching = watch !== null;
  useEffect(() => {
    const moves = reactions(state, prev.current, Date.now(), bigAt.current);
    prev.current = state;
    if (!quiet && Object.keys(moves).length) setPoses((p) => ({ ...p, ...moves }));
    const ready = yourTurn(state);
    const play = lastPlay(state);
    setLive((was) => (was.ready === ready && was.play?.key === play?.key ? was : { ready, play }));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state]);
  // an open table's newcomer until the next trick draws none, as a replay draws none
  const on = shown && shownAtTable(mode) && state.joining_you !== true;
  const size = tablet ? SEAT_SIZE.tablet : SEAT_SIZE.phone;
  const { levels, ups, done } = useLevelUps(state, size);
  const seated = state.players.find((p) => p.seat === state.you);
  const me = watch ? undefined : seated;
  const ours = seated?.team ?? 0;
  const players = useRef(state.players);
  players.current = state.players;
  const specials = useRoundEnds(state, ours, (team) => setPoses((p) => {
    const next = { ...p };
    for (const q of players.current) if (q.team === team && q.connected && !q.away) next[q.seat] = "droop";
    return next;
  }));
  // the card the table watches, and whether it waits on you
  const played = on ? live.play : null;
  const ready = on && live.ready;
  const key = JSON.stringify([state.phase, state.trick, state.last_trick?.winner, state.players.map((p) => [p.seat, p.is_bot, p.left]), tablet, levels]);
  const layout = useLayout(root, on, key, !tablet, state.phase === "deal");
  const people = state.players.filter((p) => !p.is_bot && !p.left && (!watch || !!p.look));
  // a store character at the table brings its pieces: one layer for the
  // felt, none on the watch screen (its figures keep their gait and habit)
  const material = on && !watching && people.some((p) => materialOf(parseLook(p.look).kind) !== null);
  const flair = useFlairLayer(material, flairBack, flairFront, layout?.felt, state.phase === "deal", state.phase === "play");
  // the spot your last tap chose, at this table; yours stands round it, at
  // its full size, whatever room its zone by your hand has
  const myPx = companionSize(size.base, levelIndex(levels[ours]), size.max);
  // after a reload the spot comes from the seat's own frame (its shared home)
  const ownShared = !watch && me && !me.is_bot ? me.home : undefined;
  const ownKey = ownShared && layout ? `${ownShared[0]},${ownShared[1]},${layout.felt.w},${layout.felt.h},${myPx}` : "";
  const fromFrame = useMemo(() => (ownShared && layout ? nearestClear(fromShared(layout, ownShared[0], ownShared[1]), myPx, true, layout) : null),
  // eslint-disable-next-line react-hooks/exhaustive-deps
  [ownKey]);
  const home = tapped && tapped.room === state.room ? tapped.spot : fromFrame;
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
    tag: !watch && p.seat === state.you })), taken ? { ...layout, obstacles: [...layout.obstacles, taken] } : layout) : null),
  // eslint-disable-next-line react-hooks/exhaustive-deps
  [layout, seatsKey, state.you, size.base, size.max, levels[0], levels[1], taken, watching]);
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

  const seatPx = (p: StatePlayer) => zones?.[SIDES[(p.seat - state.you + 4) % 4]].size ?? companionSize(size.base, levelIndex(levels[p.team]), size.max);
  // where another seat's person parked its companion, on this screen: the
  // clear spot nearest their point, round the other companions
  const parkAt = (p: StatePlayer, x: number, y: number): Spot | null => {
    const room = rooms?.[SIDES[(p.seat - state.you + 4) % 4]];
    return room ? nearestClear(fromShared(room, x, y), seatPx(p), false, room) : null;
  };
  const parkNow = useRef(parkAt);
  parkNow.current = parkAt;
  // each seat's shared moves as they arrive; a viewer not shown the
  // companions (or a watcher) takes none
  const seenShared = useRef<Record<number, number>>({});
  useEffect(() => {
    if (!shared) return;
    for (const [k, m] of Object.entries(shared)) {
      const seat = Number(k);
      if (!m || m.n <= (seenShared.current[seat] ?? 0)) continue;
      seenShared.current[seat] = m.n;
      const p = state.players.find((q) => q.seat === seat);
      if (!on || watching || seat === state.you || !p || p.is_bot || p.left) continue;
      if (m.act === "special") setPokes((c) => ({ ...c, [seat]: (c[seat] ?? 0) + 1 }));
      else {
        const spot = parkNow.current(p, m.x, m.y);
        if (spot) setRemoteGoals((g) => ({ ...g, [seat]: { spot, n: m.n } }));
      }
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shared]);
  const share = useRef(onShare);
  share.current = onShare;
  // your parked spot, sent at most every HOME_SHARE_GAP_MS: a tap sooner
  // waits, and the latest one goes when the time is up, so the spot yours
  // ends at is the one the table and a rejoin are told
  const homeOut = useRef<{ last: number; timer: number | null; latest: { x: number; y: number } | null }>({ last: -Infinity, timer: null, latest: null });
  const sendHome = (pt: { x: number; y: number }) => {
    const h = homeOut.current;
    h.latest = pt;
    if (h.timer !== null) return;
    const wait = h.last + HOME_SHARE_GAP_MS - Date.now();
    const go = () => {
      h.timer = null;
      h.last = Date.now();
      if (h.latest) share.current?.({ type: "companion", act: "home", ...h.latest });
      h.latest = null;
    };
    if (wait <= 0) go();
    else h.timer = window.setTimeout(go, wait);
  };
  const sendHomeNow = useRef(sendHome);
  sendHomeNow.current = sendHome;
  useEffect(() => () => { if (homeOut.current.timer !== null) window.clearTimeout(homeOut.current.timer); }, []);
  // a seat that changed hands (its frame's home gone, its name changed, a
  // bot's now) forgets the parked spot and the walk its last holder shared
  const holders = useRef<Record<number, { name: string; home: boolean; bot: boolean }>>({});
  useEffect(() => {
    const gone: number[] = [];
    for (const p of state.players) {
      const was = holders.current[p.seat];
      const now = { name: p.name, home: !!p.home, bot: p.is_bot || !!p.left };
      if (was && ((was.home && !now.home) || was.name !== now.name || (!was.bot && now.bot))) gone.push(p.seat);
      holders.current[p.seat] = now;
    }
    if (!gone.length) return;
    setRemoteHomes((h) => {
      const at = { ...h.at };
      for (const seat of gone) delete at[seat];
      return { ...h, at };
    });
    setRemoteGoals((g) => {
      const next = { ...g };
      for (const seat of gone) delete next[seat];
      return next;
    });
  }, [state.players]);

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
    if (!on || !felt || watch) return;
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
      countWalk();
      setGoal({ spot, n: ++at.n });
      sendHomeNow.current(toShared(at.layout, { x: p.x - f.x, y: p.y - f.y }));
    };
    // whether a panel was open as the tap began, before the tap closes it
    let panelAtDown = false;
    const down = () => { panelAtDown = document.querySelector(PANELS) !== null; };
    document.addEventListener("pointerdown", down, true);
    felt.addEventListener("click", tap);
    return () => { document.removeEventListener("pointerdown", down, true); felt.removeEventListener("click", tap); };
  }, [on, size.base, watching]);

  const figures = on && !!layout && !!zones;
  useEffect(() => { drawn.current = figures; }, [figures]);
  if (!on) return null;
  const end = (seat: number) => () => setPoses((p) => ({ ...p, [seat]: "idle" }));
  // a tap's goal is cleared once yours has taken it, so no later render replays it
  const takeGoal = (n: number) => setGoal((g) => (g && g.n === n ? null : g));
  const takeHome = (s: Spot | null) => setTapped(s ? { room: state.room, spot: s } : null);
  // another seat's: its walk taken, the spot is its home for this table
  const takeRemoteGoal = (seat: number) => (n: number) => setRemoteGoals((g) => {
    if (g[seat]?.n !== n) return g;
    const next = { ...g };
    delete next[seat];
    return next;
  });
  const takeRemoteHome = (seat: number) => (s: Spot | null) => setRemoteHomes((h) => {
    const at = h.room === state.room ? { ...h.at } : {};
    if (s) at[seat] = s; else delete at[seat];
    return { room: state.room, at };
  });
  // a parked spot the frame carries (a rejoin, a late arrival) until one is shared here
  const remoteHome = (p: StatePlayer): Spot | null => {
    const kept = remoteHomes.room === state.room ? remoteHomes.at[p.seat] : undefined;
    if (kept) return kept;
    return p.home ? parkAt(p, p.home[0], p.home[1]) : null;
  };
  const stepped = (pos: SeatPos, px: number) => (s: Spot | null) => setStrays((m) => {
    const was = m[pos];
    if (s ? was && was.spot.x === s.x && was.spot.y === s.y && was.px === px : !was) return m;
    const next = { ...m };
    if (s) next[pos] = { spot: s, px }; else delete next[pos];
    return next;
  });
  return (
    <div className="table-companions" ref={root} aria-hidden="true">
      {material ? <canvas className="tc-flair" data-depth="back" ref={flairBack} /> : null}
      {layout && zones ? people.map((p) => {
        const pos = SIDES[(p.seat - state.you + 4) % 4];
        const zone = zones[pos];
        const you = !watch && p.seat === state.you;
        return (
          <Walker key={p.seat} player={p} team={p.team === ours ? "us" : "them"}
                  px={you && home ? myPx : zone.size ?? companionSize(size.base, levelIndex(levels[p.team]), size.max)}
                  pos={pos} zone={zone} layout={layout} roam={rooms ? rooms[pos] : layout} pose={poses[p.seat] ?? "idle"}
                  up={ups[p.seat] ?? null} you={you} goal={you ? goal : watching ? null : remoteGoals[p.seat] ?? null}
                  tapped={you ? home : watching ? null : remoteHome(p)} poke={pokes[p.seat] ?? 0}
                  onSpecial={you ? () => share.current?.({ type: "companion", act: "special" }) : undefined}
                  wins={watching ? 0 : specials[p.team]} dealing={state.phase === "deal"} ready={you && ready}
                  flair={flair} gold={levelIndex(levels[p.team]) >= GOLD_LEVEL} arrives={drawn.current}
                  watch={played ? { pos: SIDES[(played.seat - state.you + 4) % 4], key: played.key } : null} onEnd={end(p.seat)} onUpEnd={done(p.seat)}
                  onGoal={you ? takeGoal : takeRemoteGoal(p.seat)} onTapped={you ? takeHome : takeRemoteHome(p.seat)}
                  onStray={stepped(pos, you && home ? myPx : zone.size ?? companionSize(size.base, levelIndex(levels[p.team]), size.max))} />
        );
      }) : null}
      {material ? <canvas className="tc-flair" data-depth="front" ref={flairFront} /> : null}
    </div>
  );
}
