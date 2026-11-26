// The companions on the felt, when Show at the table is on: each person's
// companion stands beside their nameplate (yours above your hand, tagged
// "You") and now and then walks a few steps within a small zone there that
// keeps clear of the cards played, the hand, the buttons and the HUD
// (`seatZones.ts`). A figure stands on its team's pad in its team's scarf,
// so a team reads by shape as well as colour, and grows with its team's level,
// only at round end. A team's companions hop when it takes a trick, and
// cheer when the trick is worth 10 points or more or the team climbs; a
// companion sleeps while its person is away. Between moves they stand
// still, each with a short fidget every 6 to 10 s on its own clock, so a
// table at rest draws almost no frames; a hidden page moves nothing, and
// Reduce Motion stills everything. Every move is a transform of a box
// round a still drawing, never of the drawing's parts. A bot, and a seat
// its owner left, has none. Nothing here takes a tap.
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { RefObject } from "react";
import type { GameState, StatePlayer } from "../protocol";
import { useAuth } from "../auth";
import { prefersReducedMotion } from "../motion";
import { useMediaQuery, TABLET_SCREEN } from "../phoneLayout";
import { Companion } from "./Companion";
import type { Pose } from "./Companion";
import { useCollection } from "./feature";
import { parseLook } from "./look";
import { shownAtTable, useCompanionMode } from "./mode";
import { clear, nearest, nextSpot, pathClear, zoneFor } from "./seatZones";
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
 *  (a hop, a cheer for 10 points or more), or at round end climbed (a cheer). */
function reactions(state: GameState, prev: GameState | null): Record<number, Pose> {
  const out: Record<number, Pose> = {};
  if (!prev) return out;
  const done = state.last_trick;
  if (done && JSON.stringify(done) !== JSON.stringify(prev.last_trick)) {
    const team = state.players.find((p) => p.seat === done.winner)?.team;
    const pose: Pose = done.points >= CHEER_POINTS ? "cheer" : "hop";
    for (const p of state.players) if (p.team === team && p.connected && !p.away) out[p.seat] = pose;
  }
  if (state.phase === "round_end" && prev.phase !== "round_end" && state.round_result && state.round_result.level_change > 0) {
    for (const p of state.players) if (p.team === state.round_result.winner_team && p.connected && !p.away) out[p.seat] = "cheer";
  }
  return out;
}

/** The moves at the table, as Web Animations of the box round a still
 *  drawing: no class or style changes as one starts or ends, so the
 *  compositor plays it and nothing is laid out or repainted. */
const MOVES: Record<"fidget" | "hop" | "cheer", { frames: Keyframe[]; ms: number; easing: string }> = {
  fidget: { ms: FIDGET_MS, easing: "ease-in-out", frames: [
    { transform: "rotate(0)" }, { transform: "rotate(-3deg)", offset: 0.35 }, { transform: "rotate(2deg)", offset: 0.7 }, { transform: "rotate(0)" }] },
  hop: { ms: 500, easing: "cubic-bezier(0.3, 0.7, 0.3, 1)", frames: [
    { transform: "translateY(0) scale(1, 1)" }, { transform: "translateY(0) scale(1.03, 0.96)", offset: 0.18 },
    { transform: "translateY(-14%) scale(0.99, 1.02)", offset: 0.5 }, { transform: "translateY(0) scale(1.02, 0.98)", offset: 0.82 },
    { transform: "translateY(0) scale(1, 1)" }] },
  cheer: { ms: 1200, easing: "cubic-bezier(0.3, 0.7, 0.3, 1)", frames: [
    { transform: "translateY(0) scale(1, 1)" }, { transform: "translateY(0) scale(1.09, 0.89)", offset: 0.08 },
    { transform: "translateY(-26%) scale(0.94, 1.08)", offset: 0.26 }, { transform: "translateY(0) scale(1.1, 0.88)", offset: 0.44 },
    { transform: "translateY(-18%) scale(0.96, 1.06)", offset: 0.62 }, { transform: "translateY(0) scale(1.06, 0.93)", offset: 0.8 },
    { transform: "translateY(0) scale(1, 1)" }] },
};

/** Play one move on `el`; resolves when it ends (at once where the element
 *  cannot animate, or under Reduce Motion, after the move's length). */
function play(el: HTMLElement | null, name: keyof typeof MOVES): { done: Promise<void>; stop: () => void } {
  const m = MOVES[name];
  if (!el || typeof el.animate !== "function" || prefersReducedMotion()) {
    let timer = 0;
    const done = new Promise<void>((r) => { timer = window.setTimeout(r, Math.min(m.ms, FIDGET_MS)); });
    return { done, stop: () => window.clearTimeout(timer) };
  }
  const a = el.animate(m.frames, { duration: m.ms, easing: m.easing });
  return { done: a.finished.then(() => undefined, () => undefined), stop: () => a.cancel() };
}

/** A companion at rest fidgets once every 6 to 10 s, on its own clock, while
 *  the page is shown and motion is allowed. */
function useFidget(el: RefObject<HTMLSpanElement | null>, on: boolean): void {
  useEffect(() => {
    if (!on || prefersReducedMotion()) return;
    let timer = 0;
    let running: { stop: () => void } | null = null;
    const wait = () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        running = play(el.current, "fidget");
        wait();
      }, FIDGET_GAP[0] + Math.random() * (FIDGET_GAP[1] - FIDGET_GAP[0]));
    };
    const seen = () => {
      window.clearTimeout(timer);
      running?.stop();
      if (document.visibilityState !== "hidden") wait();
    };
    seen();
    document.addEventListener("visibilitychange", seen);
    return () => {
      window.clearTimeout(timer);
      running?.stop();
      document.removeEventListener("visibilitychange", seen);
    };
  }, [el, on]);
}

/** A companion's base size and the most its nameplate's corner allows, by
 *  each player (Individual), in px. */
export const SEAT_SIZE = { phone: { base: 32, max: 40 }, tablet: { base: 44, max: 56 } } as const;
/** The shortest and longest wait before a companion by its player walks again. */
const WALK_GAP: readonly [number, number] = [8000, 15000];
/** A walk's shortest and longest time; one hop of its gait. */
const WALK_MS: readonly [number, number] = [800, 1500];
const STEP_MS = 260;

/** What the table measures for the walking zones, in px relative to the felt. */
const OBSTACLES = ".trick-play, .hand, .you-row .btn, .action-bar .btn, .you-tagline, .opponent, .last-trick-btn, .deal-deck, .hand-line";
const OVERLAYS = ".hud-group, .hud .chip, .hud button, .chat-launch, .away-pill";

function measure(felt: HTMLElement): Layout {
  const f = felt.getBoundingClientRect();
  const rel = (e: Element): Rect => { const b = e.getBoundingClientRect(); return { x: b.left - f.left, y: b.top - f.top, w: b.width, h: b.height }; };
  const one = (sel: string): Rect | null => { const e = felt.querySelector(sel); if (!e) return null; const r = rel(e); return r.w > 0 && r.h > 0 ? r : null; };
  const screen = felt.closest(".table-screen") ?? felt;
  const obstacles = [...felt.querySelectorAll(OBSTACLES), ...screen.querySelectorAll(OVERLAYS)]
    .filter((e) => !e.closest(".table-companions")).map(rel).filter((r) => r.w > 2 && r.h > 2);
  const plates: Layout["plates"] = {};
  for (const pos of ["left", "top", "right"] as const) {
    const r = one(`.opponent.pos-${pos}`);
    if (r) plates[pos] = r;
  }
  return { felt: { w: f.width, h: f.height }, plates, tagline: one(".you-tagline"), row: one(".you-row"), obstacles };
}

/** Where a seat sits from the viewer's chair, as the trick area draws it. */
const SIDES: readonly SeatPos[] = ["bottom", "left", "top", "right"];

const at = (s: Spot) => `translate(${s.x}px, ${s.y}px)`;

/** One companion by its player's nameplate. It stands on its zone's home,
 *  and every 8 to 15 s walks a few hopping steps to another clear spot of
 *  its zone, facing the way it goes; when cards land on it, it walks to the
 *  nearest clear spot. Every move is a Web Animation of a transform. Under
 *  Reduce Motion it stands on its home; while the page is hidden it rests. */
function Walker({ player, team, level, size, px, pos, zone, layout, pose, you, onEnd }: {
  player: StatePlayer; team: Team; level: number; size: { base: number; max: number }; px: number; pos: SeatPos;
  zone: Zone; layout: Layout; pose: Pose; you: boolean; onEnd: () => void;
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
  const ended = useRef(onEnd);
  ended.current = onEnd;
  const layoutNow = useRef(layout);
  layoutNow.current = layout;
  // a figure with nowhere clear to stand is not drawn, and keeps no clock
  const placed = zone.home !== null;
  useFidget(box, placed && move === "idle");

  const stop = () => { for (const a of walking.current) a.cancel(); walking.current = []; };
  const place = (s: Spot) => { cur.current = s; if (walk.current) walk.current.style.transform = at(s); };
  const goTo = (to: Spot) => {
    const from = cur.current;
    const el = walk.current;
    // a walk that would cross cards or a control, or a figure the layout left
    // outside its zone, goes there at once instead
    if (!from || !el || typeof el.animate !== "function" || prefersReducedMotion() || document.visibilityState === "hidden"
        || !pathClear(from, to, px, you, layoutNow.current)) {
      place(to);
      return;
    }
    stop();
    const dist = Math.hypot(to.x - from.x, to.y - from.y);
    const ms = Math.min(WALK_MS[1], Math.max(WALK_MS[0], WALK_MS[0] + (dist / px) * 250));
    const dir = to.x < from.x ? -1 : 1;
    if (face.current) face.current.style.transform = `scaleX(${dir})`;
    const a = el.animate([{ transform: at(from) }, { transform: at(to) }], { duration: ms, easing: "ease-in-out" });
    const gait = face.current?.animate([
      { transform: `scaleX(${dir}) translateY(0)` }, { transform: `scaleX(${dir}) translateY(-12%)`, offset: 0.45 },
      { transform: `scaleX(${dir}) translateY(0)` }], { duration: STEP_MS, iterations: Math.max(2, Math.round(ms / STEP_MS)) });
    walking.current = gait ? [a, gait] : [a];
    place(to);
    void a.finished.then(() => { walking.current = walking.current.filter((x) => x !== a && x !== gait); }, () => {});
  };

  // stand on the home, or step off a spot cards have landed on
  useLayoutEffect(() => {
    if (!zone.home) return;
    const now = cur.current;
    if (!now) {
      place(zone.home);
      if (face.current) face.current.style.transform = `scaleX(${pos === "right" ? -1 : 1})`;
      return;
    }
    const near = nearest(zone, now);
    const off = !near || Math.hypot(near.x - now.x, near.y - now.y) > px / 2;
    if (off || !clear(now, px, you, layout)) goTo(off ? zone.home : near);
  }, [zone, layout, px, you]);

  // a walk now and then, on its own clock, while the page is shown
  const zoneNow = useRef(zone);
  zoneNow.current = zone;
  const idle = placed && move === "idle";
  useEffect(() => {
    if (!idle || prefersReducedMotion()) return;
    let timer = 0;
    const wait = () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        // a spot it can reach without crossing anything; it stays put when none is
        const from = cur.current;
        for (let i = 0; from && i < 6; i++) {
          const to = nextSpot(zoneNow.current, from, px, Math.random());
          if (to && pathClear(from, to, px, you, layoutNow.current)) { goTo(to); break; }
        }
        wait();
      }, WALK_GAP[0] + Math.random() * (WALK_GAP[1] - WALK_GAP[0]));
    };
    const seen = () => { window.clearTimeout(timer); if (document.visibilityState !== "hidden") wait(); };
    seen();
    document.addEventListener("visibilitychange", seen);
    return () => { window.clearTimeout(timer); document.removeEventListener("visibilitychange", seen); };
  }, [idle, px]);
  useEffect(() => stop, []);

  useEffect(() => {
    if (move !== "hop" && move !== "cheer" && move !== "react") return;
    const run = play(box.current, move === "cheer" ? "cheer" : "hop");
    let live = true;
    void run.done.then(() => { if (live) ended.current(); });
    return () => { live = false; run.stop(); };
  }, [move]);

  if (!zone.home) return null;
  return (
    <span className="tc-seat" data-seat={player.seat} data-pos={pos}>
      <span className="tc-walk" ref={walk}>
        {you ? <span className="tc-you">{t("table.companionYou")}</span> : null}
        <span className="tc-face" ref={face}>
          <span className="tc-move" ref={box} data-move={move === "react" ? "hop" : move}>
            <Companion kind={kind} colour={colour} size={size.base} max={size.max} level={level} team={team}
                       state={move === "cheer" ? "cheer" : move === "sleep" ? "sleep" : "idle"} still idle="rest" />
          </span>
        </span>
      </span>
    </span>
  );
}

/** The walking zones, measured from the felt and measured again whenever
 *  the cards, the phase or the layout change (and twice more as cards
 *  finish flying in). */
function useLayout(root: RefObject<HTMLDivElement | null>, on: boolean, key: string): Layout | null {
  const [layout, setLayout] = useState<Layout | null>(null);
  useLayoutEffect(() => {
    if (!on) return;
    const felt = root.current?.parentElement;
    if (!felt) return;
    const read = () => setLayout(measure(felt));
    read();
    // once more as the cards finish flying in, and again after a slow flight
    const later = window.setTimeout(read, 450);
    const last = window.setTimeout(read, 1200);
    window.addEventListener("resize", read);
    let ro: ResizeObserver | null = null;
    if (typeof ResizeObserver === "function") {
      ro = new ResizeObserver(read);
      ro.observe(felt);
    }
    return () => { window.clearTimeout(later); window.clearTimeout(last); window.removeEventListener("resize", read); ro?.disconnect(); };
  }, [root, on, key]);
  return on ? layout : null;
}

export default function TableCompanions({ state }: { state: GameState }) {
  const shown = useCollection();
  const account = useAuth();
  const mode = useCompanionMode(account.status === "in" ? account.user : null);
  const tablet = useMediaQuery(TABLET_SCREEN);
  const [poses, setPoses] = useState<Record<number, Pose>>({});
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
  const key = JSON.stringify([state.phase, state.trick, state.last_trick?.winner, state.players.map((p) => [p.seat, p.is_bot, p.left]), tablet]);
  const layout = useLayout(root, on, key);
  if (!on) return null;
  const me = state.players.find((p) => p.seat === state.you);
  const ours = me?.team ?? 0;
  const people = state.players.filter((p) => !p.is_bot && !p.left);
  const end = (seat: number) => () => setPoses((p) => ({ ...p, [seat]: "idle" }));
  const size = tablet ? SEAT_SIZE.tablet : SEAT_SIZE.phone;
  return (
    <div className="table-companions" ref={root} aria-hidden="true">
      {layout ? people.map((p) => {
        const level = levelIndex(state.levels[p.team]);
        const px = companionSize(size.base, level, size.max);
        const pos = SIDES[(p.seat - state.you + 4) % 4];
        const you = p.seat === state.you;
        return (
          <Walker key={p.seat} player={p} team={p.team === ours ? "us" : "them"} level={level} size={size} px={px}
                  pos={pos} zone={zoneFor(pos, px, layout, you)} layout={layout} pose={poses[p.seat] ?? "idle"}
                  you={you} onEnd={end(p.seat)} />
        );
      }) : null}
    </div>
  );
}
