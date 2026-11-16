// Replays rounds recorded by server/scripts/gen_offline_engine_fixtures.py
// through this engine and reports every disagreement with the Python engine.
// Pure: the caller supplies the parsed fixture records.
import { type Card, orderingFor } from "./cards";
import { type GameState, finishRound, gameLevels, newGame, startRound } from "./game";
import { IllegalPlay, countLeadCandidates, countSubmultisets, leadCandidates, submultisets } from "./legal";
import {
  type PlayCheck,
  applyPlay,
  bury,
  checkPlay,
  dealNext,
  legalPlays,
  declare,
  declareOptions,
  finalizeDeclare,
  roundOrdering,
} from "./round";

type ProbeOutcome = { err?: string; forced?: Card[]; msg?: string };

export interface RoundRecord {
  game: number;
  round: number;
  config?: { bot: string; startLevel: string; gamesToWin: number | null };
  levels: [string, string];
  banker: number | null;
  gamesWon: [number, number];
  trumpRank: string;
  deck: Card[];
  declareEvents: (
    | [number, number, "declare", Card[]]
    | [number, number, "opts", Card[][]]
    | [number, number, "try", Card[], string | null]
  )[];
  trump: { suit: "S" | "H" | "D" | "C" | null; nt: boolean; banker: number };
  bury: Card[];
  handsAfterBury: Card[][];
  plays: ([number, Card[]] | [number, Card[], Card[], string])[];
  probes: [number, Card[], ProbeOutcome][];
  enums: [number, "lead" | "follow", number, string | null, [number, Card[]][] | null][];
  tricks: [number, number, number][];
  end: { attackerPoints: number; kittyBonus: number; lastTrickWinner: number | null };
  result: Record<string, unknown>;
}

export interface ReplayCounts {
  rounds: number;
  games: number;
  plays: number;
  legalityChecks: number;
  illegalAttempts: number;
  failedThrows: number;
  botFailedThrows: number;
  tricks: number;
  declareChecks: number;
  enumeratedDecisions: number;
  enumSkipped: number;
}

export interface Mismatch {
  game: number;
  round: number;
  area: string;
  detail: string;
}

const FOLLOW_CODES: Record<string, string> = {
  "You must follow suit.": "s",
  "You must play pairs from the led suit.": "p",
  "You must play all your cards of the led suit.": "a",
};

function followCode(err: string | null): string {
  if (err === null) return ".";
  if (err in FOLLOW_CODES) return FOLLOW_CODES[err];
  if (err.startsWith("Must play exactly")) return "c";
  if (err.startsWith("You must follow with a tractor")) return "t";
  return "?";
}

const j = (x: unknown): string => JSON.stringify(x);
const same = (a: unknown, b: unknown): boolean => j(a) === j(b);

function outcomeOf(check: PlayCheck, attempted: Card[]): ProbeOutcome {
  if (!check.ok) return { err: check.error };
  if (check.message !== null) return { forced: check.actual, msg: check.message };
  if (!same(check.actual, attempted)) return { forced: check.actual };
  return {};
}

export class FixtureReplayer {
  readonly counts: ReplayCounts = {
    rounds: 0,
    games: 0,
    plays: 0,
    legalityChecks: 0,
    illegalAttempts: 0,
    failedThrows: 0,
    botFailedThrows: 0,
    tricks: 0,
    declareChecks: 0,
    enumeratedDecisions: 0,
    enumSkipped: 0,
  };
  readonly mismatches: Mismatch[] = [];
  /** Mismatch count per rule area (all of them, not only the kept details). */
  readonly areaCounts: Record<string, number> = {};
  private game: GameState | null = null;
  private gameId = -1;
  private readonly keep: number;

  constructor(keep = 50) {
    this.keep = keep;
  }

  private miss(rec: RoundRecord, area: string, detail: string): void {
    this.areaCounts[area] = (this.areaCounts[area] ?? 0) + 1;
    if (this.mismatches.length < this.keep) this.mismatches.push({ game: rec.game, round: rec.round, area, detail });
  }

  /** Replay one round; returns false when the round had to be abandoned. */
  replayRound(rec: RoundRecord): boolean {
    try {
      return this.replay(rec);
    } catch (e) {
      this.miss(rec, "exception", String(e));
      this.game = null;
      return false;
    }
  }

  private replay(rec: RoundRecord): boolean {
    if (rec.config) {
      this.game = newGame({ startLevel: rec.config.startLevel, gamesToWin: rec.config.gamesToWin });
      this.gameId = rec.game;
      this.counts.games += 1;
    }
    const game = this.game;
    if (!game || this.gameId !== rec.game) {
      this.miss(rec, "game", "no game state for this round (an earlier round was abandoned)");
      return false;
    }
    if (!same(gameLevels(game), rec.levels) || game.banker !== rec.banker || !same(game.gamesWon, rec.gamesWon)) {
      this.miss(rec, "game", `pre-round state ${j([gameLevels(game), game.banker, game.gamesWon])} != ${j([rec.levels, rec.banker, rec.gamesWon])}`);
      return false;
    }
    const rnd = startRound(game, rec.deck);
    if (rnd.trumpRank !== rec.trumpRank) this.miss(rec, "game", `trump rank ${rnd.trumpRank} != ${rec.trumpRank}`);

    // Deal and declare.
    for (const ev of rec.declareEvents) {
      while (rnd.phase === "deal" && rnd.dealPos < ev[0]) dealNext(rnd);
      const seat = ev[1];
      this.counts.declareChecks += ev[2] === "declare" ? 0 : 1;
      if (ev[2] === "opts") {
        const got = declareOptions(rnd, seat);
        if (!same(got, ev[3])) this.miss(rec, "declare", `options seat ${seat} @${ev[0]}: ${j(got)} != ${j(ev[3])}`);
      } else if (ev[2] === "try") {
        let verdict: string | null = null;
        try {
          declare(structuredClone(rnd), seat, ev[3]);
        } catch (e) {
          if (!(e instanceof IllegalPlay)) throw e;
          verdict = e.message;
        }
        if (verdict !== ev[4]) this.miss(rec, "declare", `try ${j(ev[3])} seat ${seat}: ${verdict} != ${ev[4]}`);
      } else {
        declare(rnd, seat, ev[3]);
      }
    }
    while (rnd.phase === "deal") dealNext(rnd);
    finalizeDeclare(rnd);
    if (rnd.trumpSuit !== rec.trump.suit || rnd.trumpIsNt !== rec.trump.nt || rnd.banker !== rec.trump.banker) {
      this.miss(rec, "declare", `trump ${j([rnd.trumpSuit, rnd.trumpIsNt, rnd.banker])} != ${j(rec.trump)}`);
      return false;
    }
    bury(rnd, rnd.banker!, rec.bury);
    if (!same(rnd.hands, rec.handsAfterBury)) {
      this.miss(rec, "bury", "hands after bury differ");
      return false;
    }

    // Tricks.
    const o = roundOrdering(rnd);
    const probesAt = new Map<number, [Card[], ProbeOutcome][]>();
    for (const [idx, cards, out] of rec.probes) {
      const list = probesAt.get(idx) ?? [];
      list.push([cards, out]);
      probesAt.set(idx, list);
    }
    const enumsAt = new Map(rec.enums.map((e) => [e[0], e] as const));
    let trickNo = 0;
    for (let idx = 0; idx < rec.plays.length; idx++) {
      const play = rec.plays[idx];
      const seat = play[0];
      if (rnd.turn !== seat) {
        this.miss(rec, "turn", `play ${idx}: turn ${rnd.turn} != ${seat}`);
        return false;
      }
      const hand = rnd.hands[seat];
      const leading = rnd.trick!.plays.length === 0;
      for (const [cards, out] of probesAt.get(idx) ?? []) {
        this.counts.legalityChecks += 1;
        if (out.err !== undefined) this.counts.illegalAttempts += 1;
        if (out.forced !== undefined) this.counts.failedThrows += 1;
        const got = outcomeOf(checkPlay(rnd, seat, cards), cards);
        if (!same(got, out)) {
          const area = out.forced || got.forced ? "throw" : leading ? "lead" : "follow";
          this.miss(rec, area, `play ${idx} probe ${j(cards)}: ${j(got)} != ${j(out)}`);
        }
      }
      const en = enumsAt.get(idx);
      if (en) {
        const legalNow = this.checkEnum(rec, en, hand, leading, rnd.trick!.plays[0]?.cards ?? [], (cards) => checkPlay(rnd, seat, cards), o);
        if (legalNow !== null && !same(legalPlays(rnd, seat, Infinity), legalNow)) {
          this.miss(rec, "enum", `play ${idx}: legalPlays differs from the recorded legal candidates`);
        }
      }

      const attempted = play[1];
      const expected = play.length === 4 ? play[2] : attempted;
      const expectedMsg = play.length === 4 ? play[3] : null;
      const trick = rnd.trick!;
      let actual: Card[];
      try {
        actual = applyPlay(rnd, seat, attempted);
      } catch (e) {
        this.miss(rec, leading ? "lead" : "follow", `play ${idx} ${j(attempted)} rejected: ${String(e)}`);
        return false;
      }
      this.counts.plays += 1;
      this.counts.legalityChecks += 1;
      if (play.length === 4) {
        this.counts.failedThrows += 1;
        this.counts.botFailedThrows += 1;
      }
      if (!same(actual, expected) || (leading && rnd.message !== expectedMsg)) {
        this.miss(rec, "throw", `play ${idx} ${j(attempted)}: ${j([actual, rnd.message])} != ${j([expected, expectedMsg])}`);
        return false;
      }
      if (trick.winner !== null) {
        const want = rec.tricks[trickNo++];
        this.counts.tricks += 1;
        if (!want || trick.leader !== want[0] || trick.winner !== want[1] || trick.points !== want[2]) {
          this.miss(rec, "trick", `trick ${trickNo - 1}: ${j([trick.leader, trick.winner, trick.points])} != ${j(want)}`);
          return false;
        }
      }
    }
    if (rnd.phase !== "round_end" || trickNo !== rec.tricks.length) {
      this.miss(rec, "round", `round did not end with the recorded plays (phase ${rnd.phase})`);
      return false;
    }
    const end = { attackerPoints: rnd.attackerPoints, kittyBonus: rnd.kittyBonus, lastTrickWinner: rnd.lastTrickWinner };
    if (!same(end, rec.end)) this.miss(rec, "kitty", `${j(end)} != ${j(rec.end)}`);
    const result = finishRound(game);
    if (!same(result, rec.result)) {
      this.miss(rec, "result", `${j(result)} != ${j(rec.result)}`);
      return false;
    }
    this.counts.rounds += 1;
    return true;
  }

  private checkEnum(
    rec: RoundRecord,
    en: RoundRecord["enums"][number],
    hand: Card[],
    leading: boolean,
    lead: Card[],
    check: (cards: Card[]) => PlayCheck,
    o: ReturnType<typeof orderingFor>,
  ): Card[][] | null {
    const [idx, kind, nC, verdict, forced] = en;
    if ((kind === "lead") !== leading) {
      this.miss(rec, "enum", `play ${idx}: kind ${kind}`);
      return null;
    }
    const count = leading ? countLeadCandidates(hand, o) : countSubmultisets(hand, lead.length);
    if (count !== nC) {
      this.miss(rec, "enum", `play ${idx} ${kind}: ${count} candidates != ${nC}`);
      return null;
    }
    if (verdict === null) {
      this.counts.enumSkipped += 1;
      return null;
    }
    this.counts.enumeratedDecisions += 1;
    const cands = leading ? leadCandidates(hand, o) : submultisets(hand, lead.length);
    const forcedAt = new Map((forced ?? []).map(([i, cards]) => [i, cards] as const));
    let got = "";
    cands.forEach((cand, i) => {
      const r = check(cand);
      this.counts.legalityChecks += 1;
      if (leading) {
        if (!r.ok) {
          got += "!";
        } else if (r.message !== null) {
          got += "f";
          this.counts.failedThrows += 1;
          const want = forcedAt.get(i);
          if (!same(r.actual, want)) this.miss(rec, "throw", `play ${idx} lead candidate ${j(cand)}: forced ${j(r.actual)} != ${j(want)}`);
        } else got += ".";
      } else {
        const c = followCode(r.ok ? null : r.error);
        if (c !== ".") this.counts.illegalAttempts += 1;
        got += c;
      }
    });
    if (got !== verdict) {
      const i = [...got].findIndex((c, k) => c !== verdict[k]);
      this.miss(rec, leading ? "throw" : "follow", `play ${idx} ${kind} enum differs first at ${j(cands[i])}: ${got[i]} != ${verdict[i]}`);
    }
    return cands.filter((_, i) => verdict[i] !== "!" && (leading || verdict[i] === "."));
  }
}
