// What a bot may see: its own hand plus public information. This mirrors the
// fields shengji/ai/heuristic.py, smart.py and memory.py read from the Round
// for their own seat; nothing else of the round reaches a bot.
import { type Card, type Ordering, type TrumpSuit, orderingFor } from "../engine/cards";
import type { Declaration, RoundState, TrickPlay } from "../engine/round";

export interface PublicTrick {
  leader: number;
  plays: TrickPlay[];
}

export interface BotView {
  seat: number;
  /** The seat's hand in engine order (dealt order, kitty appended, first matching card removed). */
  hand: Card[];
  phase: RoundState["phase"];
  trumpRank: string;
  /** Fixed once the declare window closes; null before that and for no trump. */
  trumpSuit: TrumpSuit;
  declaration: Declaration | null;
  banker: number | null;
  /** The banker's own buried cards; empty for every other seat. */
  ownBuried: Card[];
  /** Completed tricks, oldest first. */
  history: PublicTrick[];
  /** The trick in progress (possibly with no plays yet), or null outside play. */
  trick: PublicTrick | null;
}

const copyTrick = (t: { leader: number; plays: TrickPlay[] }): PublicTrick => ({
  leader: t.leader,
  plays: t.plays.map((p) => ({ seat: p.seat, cards: [...p.cards] })),
});

/** The view of `state` for `seat`: copies, so a bot cannot change the round. */
export function viewFor(state: RoundState, seat: number): BotView {
  return {
    seat,
    hand: [...state.hands[seat]],
    phase: state.phase,
    trumpRank: state.trumpRank,
    trumpSuit: state.trumpSuit,
    declaration: state.declaration ? { ...state.declaration, cards: [...state.declaration.cards] } : null,
    banker: state.banker,
    ownBuried: state.banker === seat ? [...state.buried] : [],
    history: state.history.map(copyTrick),
    trick: state.trick ? copyTrick(state.trick) : null,
  };
}

export function viewOrdering(view: BotView): Ordering {
  if (view.phase === "deal" || view.phase === "declare") throw new Error("trump is not fixed yet");
  return orderingFor(view.trumpSuit, view.trumpRank);
}
