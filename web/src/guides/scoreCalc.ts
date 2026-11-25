// The score calculator's arithmetic: one hand's result from the attackers'
// points, the kitty and the last lead. It mirrors the engine's
// Game.finish_round (threshold, levels, next banker, the A cap, a won game)
// and rules_profile.kitty_multiplier (both variants), and
// __fixtures__/score_cases.json, written by
// server/scripts/seo_stats/calc_cases.py from the engine, holds it to them.
// The calculator page's own script (calculator.ts) is held to the same
// fixture.

export const RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"] as const;
export type Rank = (typeof RANKS)[number];

/** Seats in play order: 0 North, 1 East, 2 South, 3 West. Teams are 0+2 and 1+3. */
export type Seat = 0 | 1 | 2 | 3;

/** "site": twice the cards led (this site). "largest-part": twice the
 *  largest part of the lead (a tractor of k pairs is 2k cards). */
export type Variant = "site" | "largest-part";

/** A lead holds at most a whole hand. */
export const MAX_LEAD = 25;

export interface ScoreInput {
  /** Card points the attackers won in tricks: 0 to 200, a multiple of 5. */
  trickPoints: number;
  attackersWonLast: boolean;
  /** Points among the 8 buried cards: 0 to 80, a multiple of 5. */
  kittyPoints: number;
  /** Cards led to the last trick: 1 to 25. */
  leadCards: number;
  /** The lead's largest part: 1 (a single), 2 (a pair) or 2k (a tractor of k
   *  pairs), never more than the cards led. */
  leadLargest: number;
  variant: Variant;
  banker: Seat;
  /** Levels of team 0 (North–South) and team 1 (East–West) before the hand. */
  levels: [Rank, Rank];
}

export interface ScoreResult {
  multiplier: number;
  bonus: number;
  total: number;
  winner: "attackers" | "defenders";
  winnerTeam: 0 | 1;
  /** Before the A cap, as the engine reports it. */
  levelsGained: number;
  nextBanker: Seat;
  /** After the hand, capped at A. A won game leaves them as they were. */
  newLevels: [Rank, Rank];
  /** The defenders won a hand at their own level A. */
  gameWon: boolean;
}

export class ScoreInputError extends Error {}

const A_INDEX = RANKS.length - 1;

export function kittyMultiplier(leadCards: number, leadLargest: number, variant: Variant): number {
  return 2 * (variant === "largest-part" ? leadLargest : leadCards);
}

export function checkInput(input: ScoreInput): void {
  const fives = (n: number) => Number.isInteger(n) && n % 5 === 0;
  if (!fives(input.trickPoints) || input.trickPoints < 0 || input.trickPoints > 200) {
    throw new ScoreInputError("trick points run from 0 to 200 in fives");
  }
  if (!fives(input.kittyPoints) || input.kittyPoints < 0 || input.kittyPoints > 80) {
    throw new ScoreInputError("the kitty holds 0 to 80 points, in fives");
  }
  if (input.trickPoints + input.kittyPoints > 200) {
    throw new ScoreInputError("tricks and kitty together hold at most 200 points");
  }
  if (!RANKS.includes(input.levels[0]) || !RANKS.includes(input.levels[1])) throw new ScoreInputError("unknown level");
  // the lead matters, and is checked, only when the kitty scores
  if (!input.attackersWonLast) return;
  const { leadCards: n, leadLargest: k } = input;
  if (!Number.isInteger(n) || n < 1 || n > MAX_LEAD) throw new ScoreInputError("a lead is 1 to 25 cards");
  if (!Number.isInteger(k) || k < 1 || k > n || (k > 1 && k % 2 === 1)) {
    throw new ScoreInputError("the largest part is 1, a pair (2) or a tractor (4, 6 …), and no more than the cards led");
  }
}

export function score(input: ScoreInput): ScoreResult {
  checkInput(input);
  const multiplier = input.attackersWonLast ? kittyMultiplier(input.leadCards, input.leadLargest, input.variant) : 0;
  const bonus = input.kittyPoints * multiplier;
  const total = input.trickPoints + bonus;
  const bankerTeam = (input.banker % 2) as 0 | 1;
  const attackerTeam = (1 - bankerTeam) as 0 | 1;
  const attackersWin = total >= 80;
  const winnerTeam = attackersWin ? attackerTeam : bankerTeam;
  const levelsGained = attackersWin ? Math.floor((total - 80) / 40) : total === 0 ? 3 : total < 40 ? 2 : 1;
  const nextBanker = ((input.banker + (attackersWin ? 1 : 2)) % 4) as Seat;
  const idx = input.levels.map((r) => RANKS.indexOf(r));
  const gameWon = !attackersWin && idx[bankerTeam] === A_INDEX;
  if (!gameWon) idx[winnerTeam] = Math.min(A_INDEX, idx[winnerTeam] + levelsGained);
  return {
    multiplier, bonus, total,
    winner: attackersWin ? "attackers" : "defenders",
    winnerTeam, levelsGained, nextBanker,
    newLevels: [RANKS[idx[0]], RANKS[idx[1]]],
    gameWon,
  };
}
