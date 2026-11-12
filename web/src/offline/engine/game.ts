// Multi-round game state: team levels, banker rotation, games won. A port
// of server/shengji/engine/game.py. Seats 0 and 2 are team 0; 1 and 3 team 1.
import { type Card, RANKS } from "./cards";
import { EngineAssertion } from "./legal";
import { type RoundState, newRound } from "./round";

const A_INDEX = RANKS.length - 1;

export interface RoundResult {
  attackerPoints: number;
  kittyPoints: number;
  kittyCards: Card[];
  winnerTeam: number;
  levelChange: number;
  nextBanker: number;
  newLevels: [string, string];
  gameOver: boolean;
  /** Games won by each team so far (a team wins one by defending at A). */
  gamesWon: [number, number];
  /** True on the round that won a game. */
  pointScored: boolean;
}

export interface GameState {
  levelIdx: [number, number];
  startIdx: number;
  /** Games a team must win to end the match; null plays on indefinitely. */
  gamesToWin: number | null;
  gamesWon: [number, number];
  banker: number | null;
  round: RoundState | null;
  roundNo: number;
  gameOver: boolean;
  result: RoundResult | null;
}

export function newGame(opts: { startLevel?: string; gamesToWin?: number | null } = {}): GameState {
  const startLevel = opts.startLevel ?? RANKS[0];
  const start = (RANKS as readonly string[]).indexOf(startLevel);
  if (start < 0) throw new Error(`unknown start level: ${startLevel}`);
  return {
    levelIdx: [start, start],
    startIdx: start,
    gamesToWin: opts.gamesToWin === undefined ? 1 : opts.gamesToWin,
    gamesWon: [0, 0],
    banker: null,
    round: null,
    roundNo: 0,
    gameOver: false,
    result: null,
  };
}

export function gameLevels(game: GameState): [string, string] {
  return [RANKS[game.levelIdx[0]], RANKS[game.levelIdx[1]]];
}

/** The trump rank the next round is dealt at: the banker team's level. */
export function nextTrumpRank(game: GameState): string {
  return RANKS[game.levelIdx[game.banker !== null ? game.banker % 2 : 0]];
}

/** Start the next round with `deck` (108 cards in deal order). */
export function startRound(game: GameState, deck: readonly Card[]): RoundState {
  if (game.gameOver) throw new EngineAssertion("game is over");
  game.round = newRound(deck, nextTrumpRank(game), game.banker);
  game.roundNo += 1;
  game.result = null;
  return game.round;
}

/**
 * Score a round on the attackers' points: 80+ and they win, gaining a level
 * per 40 over 80, and the deal passes to the next seat; otherwise the
 * defenders gain 3 (shut out), 2 (under 40) or 1 and the banker's partner
 * deals. A game is won only by defending at A.
 */
export function roundOutcome(
  attackerPoints: number,
  banker: number,
): { winnerTeam: number; levelChange: number; nextBanker: number } {
  const bankerTeam = banker % 2;
  const p = attackerPoints;
  if (p >= 80) return { winnerTeam: 1 - bankerTeam, levelChange: Math.floor((p - 80) / 40), nextBanker: (banker + 1) % 4 };
  return { winnerTeam: bankerTeam, levelChange: p === 0 ? 3 : p < 40 ? 2 : 1, nextBanker: (banker + 2) % 4 };
}

/** Apply the finished round to the game (levels, banker, games won). */
export function finishRound(game: GameState): RoundResult {
  const rnd = game.round;
  if (!rnd || rnd.phase !== "round_end" || rnd.banker === null) throw new EngineAssertion("round not finished");
  const bankerTeam = rnd.banker % 2;
  const { winnerTeam, levelChange, nextBanker } = roundOutcome(rnd.attackerPoints, rnd.banker);
  const scored = winnerTeam === bankerTeam && game.levelIdx[bankerTeam] === A_INDEX;
  let over = false;
  if (scored) {
    game.gamesWon[winnerTeam] += 1;
    over = game.gamesToWin !== null && game.gamesWon[winnerTeam] >= game.gamesToWin;
    // The final result keeps the winning levels; a continuing table restarts.
    if (!over) game.levelIdx = [game.startIdx, game.startIdx];
  } else {
    game.levelIdx[winnerTeam] = Math.min(A_INDEX, game.levelIdx[winnerTeam] + levelChange);
  }
  game.banker = nextBanker;
  game.gameOver = over;
  game.result = {
    attackerPoints: rnd.attackerPoints,
    kittyPoints: rnd.kittyBonus,
    kittyCards: [...rnd.buried],
    winnerTeam,
    levelChange,
    nextBanker,
    newLevels: gameLevels(game),
    gameOver: over,
    gamesWon: [game.gamesWon[0], game.gamesWon[1]],
    pointScored: scored,
  };
  return game.result;
}
