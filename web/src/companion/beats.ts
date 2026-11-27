// What a table companion does in answer to the game: it gets ready when the
// turn comes to its person, watches each card played, and marks a big play
// (a jump for a trick of 20 points or more, two quick hops for a tractor led,
// a droop when the other side takes 20 or more, the special for a kitty
// taken on the last trick). Here are the events read from the game state,
// the keyframes, how far each reaches past the figure's own box (so the
// table plays the largest that stays clear where the figure stands), and the
// limits that keep a figure from doing too much.
//
// Every keyframe is a transform of a box the figure already owns, written as
// `translateY(%) rotate(deg) scale(x, y)` (the face box with `scaleX(±1)`
// before it), so two keyframes always meet value by value.
import type { GameState } from "../protocol";
import { attackingTeam, isYourTurnCue } from "../tableCopy";
import type { Pose } from "./Companion";
import { clearBox, figureBox, TAG_H } from "./seatZones";
import type { Layout, Rect, SeatPos, Spot } from "./seatZones";

/** A move a figure makes at the table: a drawing's pose, or a big play. */
export type TableMove = Pose | "big" | "droop" | "chug";

/** A trick worth this many points or more is cheered; a smaller one hopped. */
export const CHEER_POINTS = 10;
/** A trick worth this many or more is a big play: the winners jump, the losers droop. */
export const BIG_POINTS = 20;
/** Big plays (the jump and droop, a tractor's hops) are at least this far apart at one table. */
export const BIG_GAP_MS = 8000;
/** The ready jump is played at most this often; a turn that comes round
 *  sooner (a fast table), or to a figure already at `BEAT_MAX` moves this
 *  minute, only grows the figure to its ready size. */
export const READY_JUMP_GAP_MS = 8000;
/** A figure turns to watch a card at most this often. */
export const WATCH_GAP_MS = 4000;
/** The moves a figure starts in a minute before it stops adding its own
 *  (a watch, a walk on its own clock): yours, and any other figure's. What
 *  the game calls for (ready, a trick taken) is never held back. */
export const BEAT_BUDGET = { you: 8, other: 4 } as const;
/** With this many moves started in the last minute a ready turn only grows the figure, with no jump. */
export const BEAT_MAX = 12;
const MINUTE_MS = 60000;

/** Whether the table is waiting on the viewer. */
export const yourTurn = (state: GameState): boolean => isYourTurnCue(state);

/** The newest card played to the trick on the table: who played it, and a
 *  key that changes with each play; null with no card down or outside play. */
export function lastPlay(state: GameState): { seat: number; key: string } | null {
  const plays = state.phase === "play" ? state.trick?.plays ?? [] : [];
  const last = plays[plays.length - 1];
  return last ? { seat: last.seat, key: `${state.tricks_done ?? ""}:${state.trick!.leader}:${plays.length}:${last.seat}:${last.cards.join(",")}` } : null;
}

/** The tricks resolved this round, where the server counts them; null from one that does not. */
const tricksDone = (state: GameState): number | null => (typeof state.tricks_done === "number" ? state.tricks_done : null);

/** Whether a trick was taken between `prev` and `state`. Two tricks of one
 *  round can be the same cards from the same seats for the same points (two
 *  decks), so a trick is told from the one before by the server's count of
 *  tricks resolved; only a server that sends no count has the tricks
 *  themselves compared. */
export function trickTaken(state: GameState, prev: GameState): boolean {
  if (!state.last_trick) return false;
  const now = tricksDone(state), was = tricksDone(prev);
  if (now !== null && was !== null) return now !== was;
  return JSON.stringify(state.last_trick) !== JSON.stringify(prev.last_trick);
}

/** The seat that led a tractor on this frame; null when no tractor was just
 *  led. The lead is new when the trick it opens is (the count of tricks
 *  resolved moved) or it was not the lead a frame ago. */
export function tractorLed(state: GameState, prev: GameState | null): number | null {
  if (!prev || state.phase !== "play") return null;
  const lead = state.trick?.plays[0];
  if (!lead || lead.shape !== "tractor" || lead.seat !== state.trick!.leader) return null;
  const now = tricksDone(state), was = tricksDone(prev);
  if (now !== null && was !== null && now !== was) return lead.seat;
  return JSON.stringify(lead) === JSON.stringify(prev.trick?.plays[0]) ? null : lead.seat;
}

/** The team that took the kitty at this round's end (the attackers, by
 *  winning the last trick with points buried); null otherwise. */
export function kittyCapture(state: GameState): 0 | 1 | null {
  const result = state.round_result;
  const last = state.last_trick;
  const attack = attackingTeam(state);
  if (state.phase !== "round_end" || !result || !last || attack === null) return null;
  return last.winner % 2 === attack && result.kitty_points > 0 ? attack : null;
}

/** What each seat's companion does on this frame. Its team took a trick: a
 *  hop, a cheer for 10 points or more, and for 20 or more a big jump while
 *  the other team droops. A tractor led: its team's two quick hops. Big
 *  plays are `BIG_GAP_MS` apart (`limit.big` is the last one's time): one
 *  inside the gap is the plain cheer, and nothing for the losers. Nothing
 *  big starts behind the round-end sheet. A level gained is not here: it
 *  waits for the sheet to close (`useLevelUps`). */
export function reactions(state: GameState, prev: GameState | null, now: number, limit: { big: number }): Record<number, TableMove> {
  const out: Record<number, TableMove> = {};
  if (!prev) return out;
  const here = (seat: number) => { const p = state.players.find((q) => q.seat === seat); return !!p && p.connected && !p.away; };
  const free = () => state.phase !== "round_end" && now - limit.big >= BIG_GAP_MS;
  const done = state.last_trick;
  if (done && trickTaken(state, prev)) {
    const team = state.players.find((p) => p.seat === done.winner)?.team;
    const big = done.points >= BIG_POINTS && free();
    if (big) limit.big = now;
    const pose: TableMove = big ? "big" : done.points >= CHEER_POINTS ? "cheer" : "hop";
    for (const p of state.players) {
      if (!here(p.seat)) continue;
      if (p.team === team) out[p.seat] = pose;
      else if (big) out[p.seat] = "droop";
    }
  }
  const led = tractorLed(state, prev);
  if (led !== null && free()) {
    const team = state.players.find((p) => p.seat === led)?.team;
    const seats = state.players.filter((p) => p.team === team && here(p.seat) && !(p.seat in out));
    if (seats.length) limit.big = now;
    for (const p of seats) out[p.seat] = "chug";
  }
  return out;
}

/** When a figure's moves started, for its limits. */
export class BeatLog {
  private at: number[] = [];
  note(now: number): void {
    this.at.push(now);
    while (this.at.length && now - this.at[0] > MINUTE_MS) this.at.shift();
  }
  /** The moves started in the minute before `now`. */
  count(now: number): number { return this.at.filter((t) => now - t <= MINUTE_MS).length; }
  last(): number { return this.at.length ? this.at[this.at.length - 1] : -Infinity; }
}
/** Whether a figure may add a move of its own (a walk on its clock). */
export const underBudget = (log: BeatLog, now: number, you: boolean): boolean => log.count(now) < (you ? BEAT_BUDGET.you : BEAT_BUDGET.other);
/** Whether a figure may turn to watch a card now. */
export const canWatch = (log: BeatLog, now: number, you: boolean): boolean => now - log.last() >= WATCH_GAP_MS && underBudget(log, now, you);

const f = (y: number, r: number, sx: number, sy: number, offset?: number): Keyframe =>
  ({ transform: `translateY(${y}%) rotate(${r}deg) scale(${sx}, ${sy})`, ...(offset === undefined ? {} : { offset }) });

/** A move of the move box: its keyframes, its length, and (`still`) the
 *  pose held for its length under Reduce Motion, where it has one. */
export interface Beat { name: string; frames: Keyframe[]; ms: number; easing: string; still?: string }
const SPRING = "cubic-bezier(0.3, 0.7, 0.3, 1)";

/** How much larger a figure stands while its person's turn lasts. */
export const READY_SCALE = 1.17;
export const READY_HELD = `scale(${READY_SCALE})`;
const R = READY_SCALE;
/** Ready: one jump as the turn arrives, landing larger. The highest that
 *  stays clear is played; with no room to jump it only grows. */
export const GROW: Beat = { name: "grow", ms: 200, easing: "ease-out", frames: [f(0, 0, 1, 1), f(0, 0, R, R)] };
export const PERKS: readonly Beat[] = [
  ...[26, 18, 10].map((peak): Beat => ({ name: `perk${peak}`, ms: 520, easing: SPRING, frames: [
    f(0, 0, 1, 1), f(0, 0, 1.1, 0.86, 0.16), f(-peak, 0, 0.96, 1.08, 0.5), f(0, 0, 1.22, 1.08, 0.84), f(0, 0, R, R)] })),
  GROW,
];
/** A small bob while the turn lasts, from the ready size and back to it. */
export const READY_BOB: Beat = { name: "bob", ms: 420, easing: SPRING, frames: [
  f(0, 0, R, R), f(-7, 0, 1.14, 1.2, 0.45), f(0, 0, 1.19, 1.14, 0.8), f(0, 0, R, R)] };
/** The bobs after the jump, and the time from one to the next. */
export const READY_BOBS = 3;
export const READY_BOB_GAP_MS = 1100;
/** Back to its own size as the turn passes. */
export const RELAX: Beat = { name: "relax", ms: 320, easing: "ease-out", frames: [f(0, 0, R, R), f(0, 0, 1.02, 0.97, 0.6), f(0, 0, 1, 1)] };

/** A big play: a two-bounce jump. Where it has no room the table plays the cheer. */
export const BIG: Beat = { name: "big", ms: 1500, easing: SPRING, frames: [
  f(0, 0, 1, 1), f(0, 0, 1.16, 0.82, 0.07), f(-36, 0, 0.92, 1.1, 0.24), f(0, 0, 1.18, 0.8, 0.42),
  f(-24, 0, 0.94, 1.08, 0.58), f(0, 0, 1.12, 0.88, 0.74), f(-9, 0, 0.98, 1.03, 0.86), f(0, 0, 1, 1)] };
/** The other side took 20 or more: a squash and a tip, held, then a small shake back up. */
export const DROOPS: readonly Beat[] = [6, 4, 2].map((tip): Beat => ({ name: `droop${tip}`, ms: 1700, easing: "ease-in-out",
  still: `rotate(${tip}deg) scale(1.07, 0.84)`, frames: [
    f(0, 0, 1, 1), f(0, tip, 1.07, 0.84, 0.14), f(0, tip, 1.07, 0.84, 0.74), f(0, -2, 0.99, 1.03, 0.9), f(0, 0, 1, 1)] }));
/** A tractor led: its team's two quick hops. */
export const CHUGS: readonly Beat[] = [18, 12].map((peak): Beat => ({ name: `chug${peak}`, ms: 560, easing: SPRING, frames: [
  f(0, 0, 1, 1), f(0, 0, 1.06, 0.92, 0.1), f(-peak, 0, 0.98, 1.03, 0.28), f(0, 0, 1.06, 0.92, 0.5),
  f(-peak, 0, 0.98, 1.03, 0.72), f(0, 0, 1.04, 0.95, 0.9), f(0, 0, 1, 1)] }));

/** How a figure faces and holds itself as it watches: mirrored or not,
 *  leaning `lean` degrees the way it faces (negative: back), or stretched
 *  up to look at a seat above it. */
export interface Facing { dir: 1 | -1; lean: number; up: boolean }
export const facingCss = (p: Facing): string =>
  (p.lean === 0 && !p.up ? `scaleX(${p.dir})` : `scaleX(${p.dir}) translateY(0%) rotate(${p.lean}deg) scale(${p.up ? "0.97, 1.07" : "1, 1"})`);
const full = (p: Facing, y = 0, k = 1): string =>
  `scaleX(${p.dir}) translateY(${y}%) rotate(${p.lean * k}deg) scale(${p.up ? "0.97, 1.07" : "1, 1"})`;
/** The turn to watch a card, and the turn back as the trick is collected. */
export const LOOK_MS = 260;
export const LOOK_BACK_MS = 200;
/** The lean toward a card, in degrees: the largest that stays clear. */
export const LEANS = [8, 7, 6, 5, 4] as const;
/** The face box from one facing to another; `hop` adds the small rise of a turn. */
export const lookFrames = (from: Facing, to: Facing, hop: boolean): Keyframe[] =>
  (hop ? [{ transform: full(from) }, { transform: full(to, -9, 0.3), offset: 0.5 }, { transform: full(to) }] : [{ transform: full(from) }, { transform: full(to) }]);

/** How far a transform takes a figure `px` wide past its own box on each
 *  side, in px, turning and scaling about its feet. */
export interface Reach { l: number; r: number; up: number; down: number }
export function reachOf(transform: string, px: number): Reach {
  const num = (re: RegExp, d: number) => { const m = re.exec(transform); return m ? Number(m[1]) : d; };
  const mirror = num(/scaleX\((-?[\d.]+)\)/, 1);
  const y = (num(/translateY\((-?[\d.]+)%\)/, 0) / 100) * px;
  const a = (num(/rotate\((-?[\d.]+)deg\)/, 0) * Math.PI) / 180;
  const s = /scale\((-?[\d.]+)(?:,\s*(-?[\d.]+))?\)/.exec(transform);
  const sx = s ? Number(s[1]) : 1;
  const sy = s ? Number(s[2] ?? s[1]) : 1;
  const xs: number[] = [];
  const ys: number[] = [];
  for (const [cx, cy] of [[-px / 2, -px], [px / 2, -px], [-px / 2, 0], [px / 2, 0]]) {
    const x = cx * sx, v = cy * sy;
    xs.push(mirror * (x * Math.cos(a) - v * Math.sin(a)));
    ys.push(x * Math.sin(a) + v * Math.cos(a) + y);
  }
  return { l: Math.max(0, -px / 2 - Math.min(...xs)), r: Math.max(0, Math.max(...xs) - px / 2),
           up: Math.max(0, -px - Math.min(...ys)), down: Math.max(0, Math.max(...ys)) };
}
/** The furthest any of `frames` reaches. */
export function reachOfFrames(frames: readonly Keyframe[], px: number): Reach {
  const out = { l: 0, r: 0, up: 0, down: 0 };
  for (const k of frames) {
    const r = reachOf(String(k.transform ?? ""), px);
    out.l = Math.max(out.l, r.l); out.r = Math.max(out.r, r.r); out.up = Math.max(out.up, r.up); out.down = Math.max(out.down, r.down);
  }
  return out;
}
/** The box a figure at `s` takes through a move that reaches `reach`: its
 *  standing box (`figureBox`), grown wherever the move goes past it. Its
 *  tag rides over its head. */
export function beatBox(s: Spot, px: number, tag: boolean, reach: Reach): Rect {
  const b = figureBox(s, px, tag);
  const x0 = Math.min(b.x, s.x - reach.l), x1 = Math.max(b.x + b.w, s.x + px + reach.r);
  const y0 = Math.min(b.y, s.y - reach.up - (tag ? TAG_H : 0)), y1 = Math.max(b.y + b.h, s.y + px + reach.down);
  return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
}
/** Whether a figure at `s` stays clear of the table through `frames`. */
export const fits = (frames: readonly Keyframe[], s: Spot, px: number, tag: boolean, layout: Layout): boolean =>
  clearBox(beatBox(s, px, tag, reachOfFrames(frames, px)), layout);
/** The first of `beats` that stays clear where the figure stands; null for none. */
export const pickBeat = (beats: readonly Beat[], s: Spot | null, px: number, tag: boolean, layout: Layout): Beat | null =>
  (s ? beats.find((b) => fits(b.frames, s, px, tag, layout)) ?? null : null);

/** Where a seat is, for a figure looking at it: its nameplate's middle, or
 *  for the viewer's own seat the foot of the felt. */
export function seatPoint(pos: SeatPos, layout: Layout): Spot {
  const plate = pos === "bottom" ? null : layout.plates[pos];
  if (plate) return { x: plate.x + plate.w / 2, y: plate.y + plate.h / 2 };
  const { w, h } = layout.felt;
  return pos === "left" ? { x: 0, y: h / 2 } : pos === "right" ? { x: w, y: h / 2 } : pos === "top" ? { x: w / 2, y: 0 } : { x: w / 2, y: h };
}
/** How a figure standing at `s` holds itself to watch the seat at `pos`.
 *  A seat to one side: it turns that way and leans in (`flips`, your team's
 *  figures), or only leans without turning (the other team's). A seat over
 *  its head: it stretches up. A seat under it: as it stood. The lean is the
 *  largest of `LEANS` that stays clear, none where none does. */
export function aim(s: Spot, px: number, tag: boolean, now: Facing, pos: SeatPos, flips: boolean, layout: Layout): Facing {
  const to = seatPoint(pos, layout);
  const dx = to.x - (s.x + px / 2);
  const dy = to.y - (s.y + px);
  if (Math.abs(dx) < px * 0.75) {
    const up: Facing = { dir: now.dir, lean: 0, up: dy < 0 };
    return up.up && fits(lookFrames(now, up, true), s, px, tag, layout) ? up : { dir: now.dir, lean: 0, up: false };
  }
  const side = dx < 0 ? -1 : 1;
  const dir = flips ? side : now.dir;
  for (const lean of LEANS) {
    const p: Facing = { dir, lean: lean * side * dir, up: false };
    if (fits(lookFrames(now, p, true), s, px, tag, layout)) return p;
  }
  return { dir, lean: 0, up: false };
}
export const sameFacing = (a: Facing, b: Facing): boolean => a.dir === b.dir && a.lean === b.lean && a.up === b.up;
