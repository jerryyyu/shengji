// Replays rounds recorded by server/scripts/gen_offline_bot_fixtures.py: the
// TS engine drives each round with the recorded Python decisions, and at
// every decision point the TS bot for that seat is asked first and compared.
import type { Card } from "../engine/cards";
import { type GameState, finishRound, gameLevels, newGame, startRound } from "../engine/game";
import { applyPlay, bury, dealNext, declare, finalizeDeclare } from "../engine/round";
import { HeuristicBot } from "./heuristic";
import { SmartBot } from "./smart";
import { viewFor } from "./view";

export type BotKind = "smart" | "heuristic";
export type DecisionType = "declare" | "bury" | "lead" | "follow";

export interface BotRoundRecord {
  game: number;
  round: number;
  config?: { seats: BotKind[]; startLevel: string; gamesToWin: number | null };
  levels: [string, string];
  banker: number | null;
  gamesWon: [number, number];
  trumpRank: string;
  deck: Card[];
  /** [dealPos, seat, final (0/1), cards] for every declaration made; every other ask was a pass. */
  declares: [number, number, number, Card[]][];
  trump: [string | null, number];
  bury: Card[];
  plays: Card[][];
  attackerPoints: number;
}

export interface BotMismatch {
  game: number;
  round: number;
  kind: BotKind;
  type: DecisionType;
  detail: string;
}

const j = (x: unknown): string => JSON.stringify(x);
const same = (a: unknown, b: unknown): boolean => j(a) === j(b);

export class BotReplayer {
  /** Decisions checked, by "<bot>_<type>"; declares also count declarations made. */
  readonly counts: Record<string, number> = {};
  readonly mismatchCounts: Record<string, number> = {};
  readonly mismatches: BotMismatch[] = [];
  /** Milliseconds per decision, by decision type, when timing is on. */
  readonly times: Record<DecisionType, number[]> = { declare: [], bury: [], lead: [], follow: [] };
  rounds = 0;
  games = 0;
  private game: GameState | null = null;
  private gameId = -1;
  private seats: BotKind[] = [];
  private bots: (SmartBot | HeuristicBot)[] = [];

  private readonly timing: boolean;
  private readonly keep: number;

  constructor(timing = false, keep = 50) {
    this.timing = timing;
    this.keep = keep;
  }

  private bump(table: Record<string, number>, key: string): void {
    table[key] = (table[key] ?? 0) + 1;
  }

  private ask<T>(type: DecisionType, fn: () => T): T {
    if (!this.timing) return fn();
    const t0 = performance.now();
    const out = fn();
    this.times[type].push(performance.now() - t0);
    return out;
  }

  private check(rec: BotRoundRecord, seat: number, type: DecisionType, got: unknown, want: unknown, where: string): void {
    const kind = this.seats[seat];
    this.bump(this.counts, `${kind}_${type}`);
    if (same(got, want)) return;
    this.bump(this.mismatchCounts, `${kind}_${type}`);
    if (this.mismatches.length < this.keep) {
      this.mismatches.push({ game: rec.game, round: rec.round, kind, type, detail: `${where} seat ${seat}: ${j(got)} != ${j(want)}` });
    }
  }

  replayRound(rec: BotRoundRecord): void {
    if (rec.config) {
      this.game = newGame({ startLevel: rec.config.startLevel, gamesToWin: rec.config.gamesToWin });
      this.gameId = rec.game;
      this.seats = rec.config.seats;
      this.bots = this.seats.map((k) => (k === "smart" ? new SmartBot() : new HeuristicBot()));
      this.games += 1;
    }
    const game = this.game;
    if (!game || this.gameId !== rec.game) throw new Error(`no game state for game ${rec.game} round ${rec.round}`);
    if (!same(gameLevels(game), rec.levels) || game.banker !== rec.banker || !same(game.gamesWon, rec.gamesWon)) {
      throw new Error(`game ${rec.game} round ${rec.round}: pre-round state differs`);
    }
    const rnd = startRound(game, rec.deck);
    const made = new Map(rec.declares.map(([pos, seat, final, cards]) => [`${pos}:${seat}:${final}`, cards]));
    const askDeclare = (seat: number, final: boolean): void => {
      const got = this.ask("declare", () => this.bots[seat].declare(viewFor(rnd, seat), final));
      const want = made.get(`${rnd.dealPos}:${seat}:${final ? 1 : 0}`) ?? null;
      this.check(rec, seat, "declare", got, want, `declare @${rnd.dealPos}${final ? " final" : ""}`);
      if (want) {
        this.bump(this.counts, `${this.seats[seat]}_declares_made`);
        declare(rnd, seat, want);
      }
    };
    while (rnd.phase === "deal") {
      const [seat] = dealNext(rnd);
      askDeclare(seat, false);
    }
    for (let seat = 0; seat < 4; seat++) askDeclare(seat, true);
    finalizeDeclare(rnd);
    if (!same([rnd.trumpSuit, rnd.banker], rec.trump)) throw new Error(`game ${rec.game} round ${rec.round}: trump differs`);
    const banker = rnd.banker!;
    const gotBury = this.ask("bury", () => this.bots[banker].bury(viewFor(rnd, banker)));
    this.check(rec, banker, "bury", gotBury, rec.bury, "bury");
    bury(rnd, banker, rec.bury);
    rec.plays.forEach((want, idx) => {
      const seat = rnd.turn!;
      const type: DecisionType = rnd.trick!.plays.length ? "follow" : "lead";
      const got = this.ask(type, () => this.bots[seat].play(viewFor(rnd, seat)));
      this.check(rec, seat, type, got, want, `play ${idx}`);
      applyPlay(rnd, seat, want);
    });
    if (rnd.phase !== "round_end" || rnd.attackerPoints !== rec.attackerPoints) {
      throw new Error(`game ${rec.game} round ${rec.round}: round end differs`);
    }
    finishRound(game);
    this.rounds += 1;
  }
}

/** p50 / p95 / max of a list of milliseconds. */
export function percentiles(xs: number[]): { n: number; p50: number; p95: number; max: number } {
  const s = [...xs].sort((a, b) => a - b);
  const at = (q: number): number => (s.length ? s[Math.min(s.length - 1, Math.floor(q * s.length))] : 0);
  return { n: s.length, p50: at(0.5), p95: at(0.95), max: s.length ? s[s.length - 1] : 0 };
}
