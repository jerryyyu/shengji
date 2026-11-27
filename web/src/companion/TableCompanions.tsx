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
import { REACT_MS } from "./kinds";
import type { Pose } from "./Companion";
import { useCollection } from "./feature";
import { parseLook } from "./look";
import { shownAtTable, useCompanionMode } from "./mode";
import { HAND_LIFT, clear, nearest, nearestClear, nextSpot, pathClear, zonesFor } from "./seatZones";
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

/** The moves at the table, as Web Animations of the box round a still
 *  drawing: no class or style changes as one starts or ends, so the
 *  compositor plays it and nothing is laid out or repainted. */
const MOVES: Record<"fidget" | "nudge" | "hop" | "cheer", { frames: Keyframe[]; ms: number; easing: string }> = {
  fidget: { ms: FIDGET_MS, easing: "ease-in-out", frames: [
    { transform: "rotate(0)" }, { transform: "rotate(-3deg)", offset: 0.35 }, { transform: "rotate(2deg)", offset: 0.7 }, { transform: "rotate(0)" }] },
  nudge: { ms: 420, easing: "cubic-bezier(0.3, 0.7, 0.3, 1)", frames: [
    { transform: "translateY(0) scale(1, 1)" }, { transform: "translateY(-7%) scale(0.99, 1.02)", offset: 0.45 },
    { transform: "translateY(0) scale(1.02, 0.98)", offset: 0.8 }, { transform: "translateY(0) scale(1, 1)" }] },
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
function play(el: HTMLElement | null, name: keyof typeof MOVES | "levelup", from = 1): { done: Promise<void>; stop: () => void } {
  const m = name === "levelup" ? { frames: levelUpFrames(from), ms: LEVEL_UP_MS, easing: "linear" } : MOVES[name];
  if (!el || typeof el.animate !== "function" || prefersReducedMotion()) {
    let timer = 0;
    const done = new Promise<void>((r) => { timer = window.setTimeout(r, name === "levelup" ? m.ms : Math.min(m.ms, FIDGET_MS)); });
    return { done, stop: () => window.clearTimeout(timer) };
  }
  const a = el.animate(m.frames, { duration: m.ms, easing: m.easing });
  return { done: a.finished.then(() => undefined, () => undefined), stop: () => a.cancel() };
}

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
  useEffect(() => {
    if (!on || prefersReducedMotion()) return;
    let timer = 0;
    let shut = 0;
    let turn = 0;
    let running: { stop: () => void } | null = null;
    const wait = () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        const kind = FIDGETS[turn++ % FIDGETS.length];
        if (kind === "blink") {
          blink.current(true);
          shut = window.setTimeout(() => blink.current(false), BLINK_MS);
        } else {
          running = play(el.current, kind === "sway" ? "fidget" : "nudge");
        }
        wait();
      }, FIDGET_GAP[0] + Math.random() * (FIDGET_GAP[1] - FIDGET_GAP[0]));
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
  }, [el, on]);
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
/** A walk's shortest and longest time; one hop of its gait. */
const WALK_MS: readonly [number, number] = [800, 1500];
const STEP_MS = 260;

/** What the table measures for the walking zones, in px relative to the felt. */
const OBSTACLES = ".trick-play, .trick-tag, .you-row .btn, .action-bar .btn, .you-tagline, .opponent, .last-trick-btn, .deal-deck, .hand-line";
const OVERLAYS = ".hud-group, .hud .chip, .hud button, .chat-launch, .away-pill";

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

function measure(felt: HTMLElement): Layout {
  const f = framed(felt, felt.getBoundingClientRect());
  const rel = (e: Element): Rect => { const b = framed(e, e.getBoundingClientRect()); return { x: b.x - f.x, y: b.y - f.y, w: b.w, h: b.h }; };
  const one = (sel: string): Rect | null => { const e = felt.querySelector(sel); if (!e) return null; const r = rel(e); return r.w > 0 && r.h > 0 ? r : null; };
  const screen = felt.closest(".table-screen") ?? felt;
  const obstacles = [...felt.querySelectorAll(OBSTACLES), ...screen.querySelectorAll(OVERLAYS)]
    .filter((e) => !e.closest(".table-companions")).map(rel).filter((r) => r.w > 2 && r.h > 2);
  // the hand from its cards' top, raised by a chosen card's lift
  const hand = one(".hand");
  const first = one(".hand .hand-slot");
  if (hand) {
    const top = (first?.y ?? hand.y) - HAND_LIFT;
    obstacles.push({ x: hand.x, y: top, w: hand.w, h: hand.y + hand.h - top });
  }
  const plates: Layout["plates"] = {};
  for (const pos of ["left", "top", "right"] as const) {
    const r = one(`.opponent.pos-${pos}`);
    if (r) plates[pos] = r;
  }
  // the side seats' nameplates sit at the screen's safe-area edges
  const safe = plates.left && plates.right ? { x0: plates.left.x, x1: plates.right.x + plates.right.w } : undefined;
  return { felt: { w: f.w, h: f.h }, plates, tagline: one(".you-tagline"), row: one(".you-row"), hand: first,
           ...(safe ? { safe } : {}), obstacles };
}

/** Where a seat sits from the viewer's chair, as the trick area draws it. */
const SIDES: readonly SeatPos[] = ["bottom", "left", "top", "right"];

const at = (s: Spot) => `translate(${s.x}px, ${s.y}px)`;

/** A tap on your own companion plays its special at most this often. */
export const SPECIAL_COOLDOWN_MS = 3000;
/** Taps on the felt that walk your companion are at least this far apart. */
export const TAP_THROTTLE_MS = 500;

/** One companion by its player's nameplate. It stands on its zone's home,
 *  and every 8 to 15 s walks a few hopping steps to another clear spot of
 *  its zone, facing the way it goes; when cards land on it, it walks to the
 *  nearest clear spot. `goal` (yours only) is where a tap on the felt sends
 *  it: it walks there, passing under the cards if they are in the way, and
 *  stays until its next walk takes it home. A tap on yours plays its special
 *  (at most every 3 s), and `wins` counts your team's rounds won, each
 *  played as a special once any level-up has ended. Every move is a Web
 *  Animation of a transform. Under Reduce Motion it stands on its home;
 *  while the page is hidden it rests. */
function Walker({ player, team, px, pos, zone, layout, pose, up, you, goal, wins, onEnd, onUpEnd }: {
  player: StatePlayer; team: Team; px: number; pos: SeatPos;
  zone: Zone; layout: Layout; pose: Pose; up: LevelUp | null; you: boolean; goal: { spot: Spot; n: number } | null;
  wins: number; onEnd: () => void; onUpEnd: () => void;
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
  // sent by a tap on the felt, away from its zone until its next walk
  const roaming = useRef(false);
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
  const placed = zone.home !== null;
  useFidget(box, placed && move === "idle" && !up && !playing, setBlink);

  const stop = () => { for (const a of walking.current) a.cancel(); walking.current = []; path.current = null; };
  const place = (s: Spot) => { cur.current = s; if (walk.current) walk.current.style.transform = at(s); };
  /** Walk to `to`; one that would cross cards goes there at once, unless
   *  `under` lets it pass beneath them (the table's layer is under the cards). */
  const goTo = (to: Spot, under = false) => {
    const from = cur.current;
    const el = walk.current;
    if (!from || !el || typeof el.animate !== "function" || prefersReducedMotion() || document.visibilityState === "hidden"
        || (!under && !pathClear(from, to, px, you, layoutNow.current))) {
      // a walk still in flight would end over the new spot: it stops first
      stop();
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
    path.current = under ? null : { from, to };
    place(to);
    void a.finished.then(() => {
      walking.current = walking.current.filter((x) => x !== a && x !== gait);
      if (path.current?.to === to) path.current = null;
    }, () => {});
  };

  // stand on the home, or step off a spot cards have landed on. A figure with
  // no clear spot is not drawn and forgets where it stood, so the next one
  // drawn is placed afresh; a walk in flight whose way or end the cards now
  // block stops where it was going and steps to the nearest clear spot. A
  // figure a tap sent away keeps its spot while it stays clear.
  useLayoutEffect(() => {
    if (!zone.home) {
      stop();
      cur.current = null;
      roaming.current = false;
      return;
    }
    const now = cur.current;
    if (!now || !walk.current?.style.transform) {
      place(now && clear(now, px, you, layout) ? now : zone.home);
      if (face.current && !now) face.current.style.transform = `scaleX(${pos === "right" ? -1 : 1})`;
      return;
    }
    if (roaming.current) {
      if (!clear(now, px, you, layout)) goTo(nearestClear({ x: now.x + px / 2, y: now.y + px }, px, you, layout) ?? zone.home, true);
      return;
    }
    const flight = path.current;
    if (flight && !pathClear(flight.from, flight.to, px, you, layout)) {
      stop();
      place(clear(now, px, you, layout) ? now : nearest(zone, now) ?? zone.home);
      return;
    }
    const near = nearest(zone, now);
    const off = !near || Math.hypot(near.x - now.x, near.y - now.y) > px / 2;
    if (off || !clear(now, px, you, layout)) goTo(off ? zone.home : near);
  }, [zone, layout, px, you]);

  // a tap on the felt sends yours there
  const goalN = goal?.n;
  useEffect(() => {
    if (!goal || !placed) return;
    roaming.current = true;
    goTo(goal.spot, true);
  }, [goalN, placed]);

  // a walk now and then, on its own clock, while the page is shown; one a
  // tap sent away walks home
  const zoneNow = useRef(zone);
  zoneNow.current = zone;
  const idle = placed && move === "idle" && !up && !playing;
  useEffect(() => {
    if (!idle || prefersReducedMotion()) return;
    let timer = 0;
    const wait = () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        const from = cur.current;
        const home = zoneNow.current.home;
        if (roaming.current && home) {
          roaming.current = false;
          goTo(home, true);
        } else {
          // a spot it can reach without crossing anything; it stays put when none is
          for (let i = 0; from && i < 6; i++) {
            const to = nextSpot(zoneNow.current, from, px, Math.random());
            if (to && pathClear(from, to, px, you, layoutNow.current)) { goTo(to); break; }
          }
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
    if (move !== "hop" && move !== "cheer") return;
    const run = play(box.current, move);
    let live = true;
    void run.done.then(() => { if (live) ended.current(); });
    return () => { live = false; run.stop(); };
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
    const timer = window.setTimeout(() => setPlaying(false), prefersReducedMotion() ? 1000 : REACT_MS[kind]);
    return () => { window.clearTimeout(timer); setPlaying(false); };
  }, [special, kind]);
  const tapped = (e: MouseEvent) => {
    e.stopPropagation();
    if (!you || away || playing || up || Date.now() - lastSpecial.current < SPECIAL_COOLDOWN_MS) return;
    setSpecial((n) => n + 1);
  };

  const drawn: Pose = away ? "sleep" : up ? "cheer" : playing ? "react" : move;

  if (!zone.home) return null;
  return (
    <span className="tc-seat" data-seat={player.seat} data-pos={pos}>
      <span className={`tc-walk${you ? " tc-mine" : ""}`} ref={walk} onClick={you ? tapped : undefined}>
        {you ? <span className="tc-you">{t("table.companionYou")}</span> : null}
        {up && !away ? <span className="tc-level" key={up.n}>{up.glyph}</span> : null}
        <span className="tc-face" ref={face}>
          <span className="tc-move" ref={box} data-move={up && !away ? "levelup" : playing && !away ? "react" : move}>
            <Companion kind={kind} colour={colour} size={px} team={team}
                       blink={blink && drawn === "idle"} still={!(drawn === "react" && playing)} idle="rest"
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
  const layout = useLayout(root, on, key);
  const people = state.players.filter((p) => !p.is_bot && !p.left);
  // the zones, worked out again only when the layout, the people or their sizes change
  const seatsKey = JSON.stringify(people.map((p) => [p.seat, p.team]));
  const zones = useMemo(() => (layout ? zonesFor(people.map((p) => ({
    pos: SIDES[(p.seat - state.you + 4) % 4], size: companionSize(size.base, levelIndex(levels[p.team]), size.max),
    tag: p.seat === state.you })), layout) : null),
  // eslint-disable-next-line react-hooks/exhaustive-deps
  [layout, seatsKey, state.you, size.base, size.max, levels[0], levels[1]]);
  const mine = me && !me.is_bot && !me.left ? zones?.bottom ?? null : null;

  // a tap on empty felt walks yours to the clear spot nearest the tap
  const tapState = useRef({ layout, mine, last: -Infinity, n: 0 });
  tapState.current.layout = layout;
  tapState.current.mine = mine;
  useEffect(() => {
    const felt = root.current?.parentElement;
    if (!on || !felt) return;
    const tap = (e: Event) => {
      const at = tapState.current;
      const target = e.target as Element | null;
      if (!at.layout || !at.mine?.home || !target || target.closest(NOT_FELT)) return;
      const now = Date.now();
      if (now - at.last < TAP_THROTTLE_MS) return;
      const f = framed(felt, felt.getBoundingClientRect());
      const { clientX, clientY } = e as globalThis.MouseEvent;
      const p = framedPoint(felt, clientX, clientY);
      const px = at.mine.size ?? size.base;
      const spot = nearestClear({ x: p.x - f.x, y: p.y - f.y }, px, true, at.layout);
      if (!spot) return;
      at.last = now;
      setGoal({ spot, n: ++at.n });
    };
    felt.addEventListener("click", tap);
    return () => felt.removeEventListener("click", tap);
  }, [on, size.base]);

  if (!on) return null;
  const end = (seat: number) => () => setPoses((p) => ({ ...p, [seat]: "idle" }));
  return (
    <div className="table-companions" ref={root} aria-hidden="true">
      {layout && zones ? people.map((p) => {
        const pos = SIDES[(p.seat - state.you + 4) % 4];
        const zone = zones[pos];
        const you = p.seat === state.you;
        return (
          <Walker key={p.seat} player={p} team={p.team === ours ? "us" : "them"}
                  px={zone.size ?? companionSize(size.base, levelIndex(levels[p.team]), size.max)}
                  pos={pos} zone={zone} layout={layout} pose={poses[p.seat] ?? "idle"}
                  up={ups[p.seat] ?? null} you={you} goal={you ? goal : null} wins={p.team === ours ? wins : 0}
                  onEnd={end(p.seat)} onUpEnd={done(p.seat)} />
        );
      }) : null}
    </div>
  );
}
