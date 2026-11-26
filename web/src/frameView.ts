// A bot's view of the table from what one seat can see: the latest state
// frame plus what the seat has seen earlier in the round (the finished tricks,
// its own bury). Shared by the Nearby soak's autoplay and the first game's
// hint pick. Types only from the offline bot, so importing this loads no bot.
import type { Card, TrumpSuit } from "./offline/engine/cards";
import type { RoundState } from "./offline/engine/round";
import type { BotView, PublicTrick } from "./offline/bot";

export type Frame = Record<string, unknown> & { type: string };
export interface FrameCard {
  id: number;
  code: string;
}
type TrickJson = { leader: number; plays: { seat: number; cards: string[] }[] } | null;

/** What the seat has seen this round, beyond the latest frame. */
export interface SeatMemory {
  /** Completed tricks, oldest first, from the frames' last tricks. */
  history: PublicTrick[];
  /** The ordinal (`tricks_done`) of the last trick recorded; 0 for none. */
  lastOrdinal: number;
  /** The last trick's plays, for a server that sends no `tricks_done`. */
  lastTrickKey: string;
  /** The cards this seat buried, as the banker. */
  buried: Card[];
  handSize: number;
  /** The latest frame's phase and `tricks_done`; "" and null before any. */
  phase: string;
  tricksDone: number | null;
}

export function freshMemory(): SeatMemory {
  return { history: [], lastOrdinal: 0, lastTrickKey: "", buried: [], handSize: 0, phase: "", tricksDone: null };
}

const copyTrick = (t: NonNullable<TrickJson>): PublicTrick => ({
  leader: t.leader,
  plays: t.plays.map((p) => ({ seat: p.seat, cards: [...p.cards] })),
});

/** Folds a state frame into the seat's memory. A round boundary clears it: a
 *  deal after any other phase, a deal with fewer cards than the last frame,
 *  or `tricks_done` going down. A last trick joins the history once: by its
 *  ordinal (`tricks_done`), so two tricks with the same cards stay two, or
 *  by its plays from a server that sends no count. Only the play and the
 *  round's end carry this round's tricks; a deal's leftover last trick is
 *  the previous round's. */
export function remember(mem: SeatMemory, f: Frame): void {
  const hand = (f.hand as FrameCard[] | undefined) ?? [];
  const phase = String(f.phase ?? "");
  const done = typeof f.tricks_done === "number" ? f.tricks_done : null;
  const boundary = (phase === "deal" && mem.phase !== "" && mem.phase !== "deal")
    || (phase === "deal" && hand.length < mem.handSize)
    || (done !== null && mem.tricksDone !== null && done < mem.tricksDone);
  if (boundary) Object.assign(mem, freshMemory());
  mem.handSize = hand.length;
  mem.phase = phase;
  if (done !== null) mem.tricksDone = done;
  if (phase !== "play" && phase !== "round_end") return;
  const last = f.last_trick as TrickJson;
  if (!last) return;
  if (done !== null) {
    if (done > mem.lastOrdinal) {
      mem.lastOrdinal = done;
      mem.history.push(copyTrick(last));
    }
    return;
  }
  const key = JSON.stringify(last.plays);
  if (key !== mem.lastTrickKey) {
    mem.lastTrickKey = key;
    mem.history.push(copyTrick(last));
  }
}

/** The bot's view from what this seat can see in `f`; null before trump is
 *  fixed (a view needs the trump rank). */
export function viewFromFrame(f: Frame, mem: SeatMemory): BotView | null {
  const trump = f.trump as { suit: string | null; rank: string } | null;
  if (!trump) return null;
  const seat = f.you as number;
  const decl = f.current_declaration as { seat: number; cards: string[] } | null;
  const trick = f.trick as TrickJson;
  return {
    seat,
    hand: (f.hand as FrameCard[]).map((c) => c.code),
    phase: f.phase as RoundState["phase"],
    trumpRank: trump.rank,
    trumpSuit: (trump.suit === "NT" ? null : trump.suit) as TrumpSuit,
    declaration: decl ? { seat: decl.seat, cards: [...decl.cards], strength: 1 } : null,
    banker: (f.banker as number | null) ?? null,
    ownBuried: f.banker === seat ? [...mem.buried] : [],
    history: mem.history.map((t) => ({ leader: t.leader, plays: t.plays.map((p) => ({ seat: p.seat, cards: [...p.cards] })) })),
    trick: trick ? copyTrick(trick) : null,
  };
}

/** The hand ids for `codes`, each card used once; null when one is missing. */
export function idsFor(hand: readonly FrameCard[], codes: readonly string[]): number[] | null {
  const pool = [...hand];
  const out: number[] = [];
  for (const code of codes) {
    const k = pool.findIndex((c) => c.code === code);
    if (k < 0) return null;
    out.push(pool.splice(k, 1)[0].id);
  }
  return out;
}
