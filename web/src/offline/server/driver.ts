// The parity fixtures' human player, ported from HumanDriver in
// server/scripts/gen_offline_server_fixtures.py: after App's Play-vs-bots
// create_room {start: true} began the game, SmartBot's decisions for seat 0 sent as ordinary client messages. It
// decides only on a frame that matches the live round, as the Python driver
// does, so both servers see the same messages at the same points.
import { orderingFor } from "../engine/cards";
import { decompose } from "../engine/combos";
import type { RoundState } from "../engine/round";
import { SmartBot, viewFor } from "../bot";

export const HUMAN_SEAT = 0;
const PLAIN_SUITS = ["S", "H", "D", "C"] as const;

type Frame = Record<string, unknown> & { type: string };
interface HandCard {
  id: number;
  code: string;
}
type Action = Record<string, unknown>;

function idsFor(hand: HandCard[], codes: string[]): number[] {
  const pool = [...hand];
  return codes.map((code) => {
    const k = pool.findIndex((c) => c.code === code);
    if (k < 0) throw new Error(`driver: ${code} not in the frame's hand`);
    return pool.splice(k, 1)[0].id;
  });
}

const sameCards = (a: string[], b: string[]) => [...a].sort().join(",") === [...b].sort().join(",");

export class HumanDriver {
  private bot = new SmartBot();
  private roundsDone = 0;
  private leaving = false;
  private acted = new Set<string>();
  private rounds: number;
  private liveRound: () => RoundState | null;
  private throws: boolean;
  private seat: number;
  /** The round whose end this driver has answered. */
  private answered: RoundState | null = null;

  /** `seat` is the seat it plays; the fixtures' human sits at HUMAN_SEAT. */
  constructor(rounds: number, liveRound: () => RoundState | null, throws = false, seat = HUMAN_SEAT) {
    this.rounds = rounds;
    this.liveRound = liveRound;
    this.throws = throws;
    this.seat = seat;
  }

  private fresh(msg: Frame, rnd: RoundState): boolean {
    const decl = msg.current_declaration as { seat: number; cards: string[] } | null;
    const live = rnd.declaration;
    const declEq = decl === null ? live === null : live !== null && decl.seat === live.seat && decl.cards.join(",") === live.cards.join(",");
    const trick = msg.trick as { plays: unknown[] } | null;
    const passed = msg.passed as number[];
    const livePassed = [...rnd.passed].sort((a, b) => a - b);
    return (
      msg.phase === rnd.phase &&
      (msg.hand as HandCard[]).length === rnd.hands[this.seat].length &&
      msg.turn === rnd.turn &&
      declEq &&
      passed.join(",") === livePassed.join(",") &&
      (trick ? trick.plays.length : 0) === (rnd.trick ? rnd.trick.plays.length : 0) &&
      (msg.last_trick === null) === (rnd.lastTrick === null)
    );
  }

  react(msg: Frame): Action[] {
    if (msg.type !== "state" || this.leaving) return [];
    const phase = msg.phase as string;
    if (phase === "round_end") {
      if ((msg.ready as number[]).includes(this.seat)) return [];
      // one answer per round end, however many frames arrive before the
      // server has counted it
      const ended = this.liveRound();
      if (ended !== null && (ended === this.answered || ended.phase !== "round_end")) return [];
      this.answered = ended;
      this.roundsDone += 1;
      if (this.roundsDone >= this.rounds) {
        this.leaving = true;
        return [{ type: "table_leave" }];
      }
      return [{ type: "next_round" }];
    }
    const rnd = this.liveRound();
    if (rnd === null || !this.fresh(msg, rnd)) return [];
    const hand = msg.hand as HandCard[];
    if (phase === "deal" || phase === "declare") {
      if (phase === "declare" && (msg.passed as number[]).includes(this.seat)) return [];
      const final = phase === "declare";
      const options = msg.declare_options as number[][];
      const cards = options.length ? this.bot.declare(viewFor(rnd, this.seat), final) : null;
      if (cards) {
        const byId = new Map(hand.map((c) => [c.id, c.code]));
        const ids = options.find((o) => sameCards(o.map((i) => byId.get(i)!), cards));
        if (!ids) throw new Error("driver: declaration is not among the frame's options");
        return [{ type: "declare", card_ids: ids }];
      }
      return final ? [{ type: "pass_declare" }] : [];
    }
    if (msg.turn !== this.seat) return [];
    const key = `${this.roundsDone}|${phase}|${rnd.history.length}|${rnd.trick ? rnd.trick.plays.length : -1}`;
    if (this.acted.has(key)) return [];
    this.acted.add(key);
    if (phase === "bury") {
      return [{ type: "bury", card_ids: idsFor(hand, this.bot.bury(viewFor(rnd, this.seat))) }];
    }
    if (phase === "play") {
      const cards = (this.throws ? this.throwAttempt(rnd) : null) ?? this.bot.play(viewFor(rnd, this.seat));
      return [{ type: "play", card_ids: idsFor(hand, cards) }];
    }
    return [];
  }

  /** On a lead: every card of the first plain suit holding more than one component. */
  private throwAttempt(rnd: RoundState): string[] | null {
    if (rnd.trick!.plays.length) return null;
    const o = orderingFor(rnd.trumpSuit, rnd.trumpRank);
    for (const suit of PLAIN_SUITS) {
      const cards = rnd.hands[this.seat].filter((c) => o.effSuit(c) === suit);
      if (decompose(cards, o).components.length > 1) return cards;
    }
    return null;
  }
}
