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
  lastTrickKey: string;
  /** The cards this seat buried, as the banker. */
  buried: Card[];
  handSize: number;
}

export function freshMemory(): SeatMemory {
  return { history: [], lastTrickKey: "", buried: [], handSize: 0 };
}

const copyTrick = (t: NonNullable<TrickJson>): PublicTrick => ({
  leader: t.leader,
  plays: t.plays.map((p) => ({ seat: p.seat, cards: [...p.cards] })),
});

/** Folds a state frame into the seat's memory: a new round clears it, and a
 *  last trick it has not seen joins the history. */
export function remember(mem: SeatMemory, f: Frame): void {
  const hand = (f.hand as FrameCard[] | undefined) ?? [];
  if (f.phase === "deal" && hand.length < mem.handSize) Object.assign(mem, freshMemory());
  mem.handSize = hand.length;
  const last = f.last_trick as TrickJson;
  if (last) {
    const key = JSON.stringify(last.plays);
    if (key !== mem.lastTrickKey) {
      mem.lastTrickKey = key;
      mem.history.push(copyTrick(last));
    }
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
