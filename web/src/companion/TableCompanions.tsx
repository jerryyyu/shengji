// The companions on the felt, in Team view: each team's people stand
// together in their team's corner (yours lower left, theirs upper right) on
// their team's pad in their team's scarf, so a team reads by place and shape
// as well as colour. A team's companions grow with its level, only at round
// end. A team's companions hop when it takes a trick, and cheer when the
// trick is worth 10 points or more or the team climbs; a companion sleeps
// while its person is away. Between moves they stand still, each with a
// short fidget every 6 to 10 s on its own clock, so a table at rest draws
// almost no frames; a hidden page fidgets not at all. Every move here is a
// transform of a box, never of the drawing's parts (`Figure`). A bot, and a seat its
// owner left, has none. Nothing here takes a tap: the felt under it stays
// the table's.
import { useEffect, useRef, useState } from "react";
import type { RefObject } from "react";
import type { GameState, StatePlayer } from "../protocol";
import { useAuth } from "../auth";
import { prefersReducedMotion } from "../motion";
import { useMediaQuery, TABLET_SCREEN } from "../phoneLayout";
import { Companion } from "./Companion";
import type { Pose } from "./Companion";
import { useCollection } from "./feature";
import { parseLook } from "./look";
import { useCompanionMode } from "./mode";
import { LEVELS } from "./rig";
import "./tableCompanions.css";
import type { Team } from "./rig";

/** A companion's base size and the most its seat area allows, in px: a
 *  phone's table, and a tablet's (or a desktop window's). */
export const TABLE_SIZE = { phone: { base: 44, max: 56 }, tablet: { base: 56, max: 72 } } as const;

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

/** One companion at the table. Its drawing never animates here: every move
 *  is a transform of the box around it (`MOVES`). A hop is that box's
 *  bounce; a cheer is its double jump with the drawing swapped for the
 *  cheer's peak (the open smile, the raised arms, the confetti); a fidget is
 *  a small sway. `data-move` names the move playing. */
function Figure({ player, team, level, size, pose, flip, onEnd }: {
  player: StatePlayer; team: Team; level: number; size: { base: number; max: number }; pose: Pose; flip: boolean;
  onEnd: () => void;
}) {
  const { kind, colour } = parseLook(player.look);
  const away = !player.connected || player.away === true;
  const move: Pose = away ? "sleep" : pose;
  const box = useRef<HTMLSpanElement | null>(null);
  const ended = useRef(onEnd);
  ended.current = onEnd;
  useFidget(box, move === "idle");
  useEffect(() => {
    if (move !== "hop" && move !== "cheer" && move !== "react") return;
    const run = play(box.current, move === "cheer" ? "cheer" : "hop");
    let live = true;
    void run.done.then(() => { if (live) ended.current(); });
    return () => { live = false; run.stop(); };
  }, [move]);
  return (
    <span className={`tc-fig${flip ? " tc-flip" : ""}`} data-seat={player.seat}>
      <span className="tc-move" ref={box} data-move={move === "react" ? "hop" : move}>
        <Companion kind={kind} colour={colour} size={size.base} max={size.max} level={level} team={team}
                   state={move === "cheer" ? "cheer" : move === "sleep" ? "sleep" : "idle"} still idle="rest" />
      </span>
    </span>
  );
}

export default function TableCompanions({ state }: { state: GameState }) {
  const shown = useCollection();
  const account = useAuth();
  const mode = useCompanionMode(account.status === "in" ? account.user : null);
  const tablet = useMediaQuery(TABLET_SCREEN);
  const [poses, setPoses] = useState<Record<number, Pose>>({});
  const prev = useRef<GameState | null>(null);
  useEffect(() => {
    const moves = reactions(state, prev.current);
    prev.current = state;
    if (Object.keys(moves).length) setPoses((p) => ({ ...p, ...moves }));
  }, [state]);
  // Individual is not designed yet: it draws nothing, as Off does
  if (!shown || mode !== "team") return null;
  const me = state.players.find((p) => p.seat === state.you);
  const ours = me?.team ?? 0;
  const size = tablet ? TABLE_SIZE.tablet : TABLE_SIZE.phone;
  const people = state.players.filter((p) => !p.is_bot && !p.left)
    .sort((a, b) => Number(b.seat === state.you) - Number(a.seat === state.you) || a.seat - b.seat);
  const end = (seat: number) => () => setPoses((p) => ({ ...p, [seat]: "idle" }));
  const side = (team: 0 | 1, name: Team) => {
    const here = people.filter((p) => p.team === team);
    if (here.length === 0) return null;
    const level = levelIndex(state.levels[team]);
    return (
      <div className={`tc-team tc-${name}`} data-level={state.levels[team]}>
        {here.map((p, i) => (
          <Figure key={p.seat} player={p} team={name} level={level} size={size} pose={poses[p.seat] ?? "idle"}
                  flip={name === "them" || i > 0} onEnd={end(p.seat)} />
        ))}
      </div>
    );
  };
  return (
    <div className="table-companions" aria-hidden="true">
      {side(ours, "us")}
      {side(ours === 0 ? 1 : 0, "them")}
    </div>
  );
}
