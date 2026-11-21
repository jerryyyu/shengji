// The whole-app soak's people: each phone plays as one persona, drawn from a
// mix, with the declarer's calls and the menu walker's visits on top. A
// persona decides only from what its seat's own frames show, so the same
// rules drive the device soak (nearbySoakDriver.ts) and its tests. Loaded
// only with the soak (nearbySoak.ts), in a build with its Autoplay switch.
import type { SmartBot } from "./offline/bot";
import { viewFromFrame, type SeatMemory } from "./nearbySoak";

type Frame = Record<string, unknown> & { type: string };
type Rand = () => number;

/** The persona that sets a phone's pace and its flows:
 *  - pacer: a person's pace, 0.5-2 s a move;
 *  - sloth: 55-59 s a move, sometimes past the 60 s move clock, and then
 *    im_back;
 *  - twitch: 0-50 ms, a move sent twice, one decided on the frame before,
 *    one sent while the socket is not open;
 *  - leaver: Leave at a random phase (sometimes with the link down), back by
 *    code 3-90 s later, sometimes with the kept token forgotten;
 *  - seatSwapper: lobby seat moves, Start given and taken back. */
export type Persona = "pacer" | "sloth" | "twitch" | "leaver" | "seatSwapper";

export const PERSONAS: readonly Persona[] = ["pacer", "sloth", "twitch", "leaver", "seatSwapper"];

/** The weights a phone's persona is drawn with. */
export type PersonaMix = Record<Persona, number>;

export const DEFAULT_MIX: PersonaMix = { pacer: 0.5, sloth: 0.15, twitch: 0.15, leaver: 0.1, seatSwapper: 0.1 };

export interface Personas {
  main: Persona;
  /** Declares and overcalls while dealing and in the declare window (on
   *  for every phone unless switched off). */
  declarer: boolean;
  /** Opens and closes the ⋯ menu, a setting and How to play between moves. */
  menuWalker: boolean;
  /** Joins only once the game is under way (a third phone). */
  latecomer: boolean;
}

/** One phone's personas: `main` drawn from `mix`; the host never leaves
 *  (its Leave ends the table), so a host leaver plays as a pacer. */
export function pickPersonas(rand: Rand, opts: { mix?: PersonaMix; role?: "host" | "joiner"; menuWalker?: number; latecomer?: boolean; declarer?: boolean } = {}): Personas {
  const mix = opts.mix ?? DEFAULT_MIX;
  const total = PERSONAS.reduce((a, p) => a + Math.max(0, mix[p]), 0);
  let x = rand() * (total > 0 ? total : 1);
  let main: Persona = "pacer";
  for (const p of PERSONAS) {
    const w = Math.max(0, mix[p]);
    if (x < w) {
      main = p;
      break;
    }
    x -= w;
  }
  if (opts.role === "host" && main === "leaver") main = "pacer";
  return {
    main,
    declarer: opts.declarer ?? true,
    menuWalker: rand() < (opts.menuWalker ?? 0.3),
    latecomer: opts.role === "joiner" && opts.latecomer === true,
  };
}

/** The move clock: a human seat's turn lasts this long before the room
 *  plays it and marks the seat away. */
export const MOVE_CLOCK_MS = 60_000;

/** How long `p` takes over one decision, in ms. A sloth is past the move
 *  clock one time in five. */
export function moveDelay(p: Persona, rand: Rand): number {
  if (p === "twitch") return rand() * 50;
  if (p === "sloth") return rand() < 0.2 ? MOVE_CLOCK_MS + rand() * 6000 : 55_000 + rand() * 4000;
  return 500 + rand() * 1500;
}

/** A twitch's extras on one move: the same move again at once, a move
 *  decided on the frame before this one, a send while the socket is not
 *  open (each tried, and logged, whatever the page does with it). */
export interface TwitchPlan { double: boolean; stale: boolean; whileClosed: boolean }

export function twitchPlan(rand: Rand): TwitchPlan {
  return { double: rand() < 0.3, stale: rand() < 0.15, whileClosed: rand() < 0.1 };
}

/** The phases a leaver's Leave may come in. */
export const LEAVE_PHASES = ["lobby", "deal", "declare", "bury", "play", "round_end"] as const;
export type LeavePhase = (typeof LEAVE_PHASES)[number];

export interface LeavePlan {
  /** The Leave comes on the next frame in this phase... */
  phase: LeavePhase;
  /** ...or while the socket is not open (the person leaves with the link down). */
  whileDown: boolean;
  /** The rejoin by code, this long after the Leave. */
  rejoinMs: number;
  /** The rejoin forgets the kept seat token first (a fresh install's join). */
  dropToken: boolean;
}

export function leavePlan(rand: Rand): LeavePlan {
  return {
    phase: LEAVE_PHASES[Math.min(LEAVE_PHASES.length - 1, Math.floor(rand() * LEAVE_PHASES.length))],
    whileDown: rand() < 0.25,
    rejoinMs: 3000 + rand() * 87_000,
    dropToken: rand() < 0.2,
  };
}

/** The idsFor of nearbySoak.ts, for a declaration's codes. */
function optionFor(f: Frame, codes: string[]): number[] | null {
  const hand = (f.hand as { id: number; code: string }[]) ?? [];
  const byId = new Map(hand.map((c) => [c.id, c.code]));
  const want = [...codes].sort().join(",");
  const opts = (f.declare_options as number[][] | undefined) ?? [];
  return opts.find((o) => o.map((i) => byId.get(i) ?? "?").sort().join(",") === want) ?? null;
}

/** A declarer's call on frame `f`, or null: while dealing (each frame with
 *  options, one time in three) and in the declare window (once there is an
 *  option), the bot's pick of the options if it has one, else the strongest
 *  offered (the last); an overcall when another seat holds the declaration. */
export function declareMove(f: Frame, mem: SeatMemory, bot: Pick<SmartBot, "declare">, rand: Rand): Record<string, unknown> | null {
  if (f.type !== "state") return null;
  const phase = f.phase as string;
  if (phase !== "deal" && phase !== "declare") return null;
  const opts = (f.declare_options as number[][] | undefined) ?? [];
  if (opts.length === 0) return null;
  if (phase === "declare" && ((f.passed as number[] | undefined) ?? []).includes(f.you as number)) return null;
  const decl = f.current_declaration as { seat: number } | null;
  if (decl && decl.seat === f.you) return null;
  if (phase === "deal" && rand() >= 1 / 3) return null;
  let pick: number[] | null = null;
  try {
    const view = viewFromFrame(f, mem);
    const cards = view ? bot.declare(view, phase === "declare") : null;
    if (cards) pick = optionFor(f, cards);
  } catch {
    pick = null;
  }
  return { type: "declare", card_ids: pick ?? opts[opts.length - 1] };
}

/** A seat swapper's lobby step on room frame `f`: a move to an open seat,
 *  or its Start given or taken back. Null when it owes nothing. */
export function lobbyMove(f: Frame, rand: Rand, opts: { swapper: boolean }): Record<string, unknown> | null {
  if (f.type !== "room") return null;
  const you = f.you as number;
  const ready = ((f.nearby as { ready?: number[] } | undefined)?.ready) ?? [];
  const mine = ready.includes(you);
  if (!opts.swapper) return mine ? null : { type: "table_start" };
  const taken = new Set(((f.players as { seat: number }[] | undefined) ?? []).map((p) => p.seat));
  const open = [0, 1, 2, 3].filter((s) => !taken.has(s));
  const r = rand();
  if (r < 0.4 && open.length) return { type: "table_move", seat: open[Math.min(open.length - 1, Math.floor(rand() * open.length))] };
  if (r < 0.65 && mine) return { type: "table_start", on: false };
  return mine ? null : { type: "table_start" };
}
