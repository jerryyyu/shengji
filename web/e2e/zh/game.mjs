import { base, hand, plays, HAND25 } from "../fake.mjs";
const NAMES = ["Cheerful Tractor", "Bot Wei", "Quiet Panda", "Bot Li"];
const opts = { names: NAMES, humans: [0, 2] };
const DEAL14 = ["S3", "S5", "S9", "SK", "SA", "H3", "H4", "H10", "HK", "HA", "D6", "C2", "H2", "BJ"];
const dealt = { phase: "deal", banker: null, trump: null, turn: null, trick: null, attacker_points: 0, declare_deadline: 12, ranked: false };
export const DECLARE = base({ ...dealt, hand: hand(DEAL14), declare_options: [[12], [13]], current_declaration: { seat: 1, cards: ["D2"] } }, { ...opts, banker: null });
export const PLAY = base({ trick: { leader: 1, plays: [{ seat: 1, cards: ["HA"] }, { seat: 2, cards: ["H5"] }, { seat: 3, cards: ["HQ"] }] }, turn: 0, attacker_points: 35,
  last_trick: { leader: 0, plays: plays(0, 4, 1), winner: 1, points: 10 }, levels: ["5", "2"], trump: { suit: "S", rank: "5", declarer: 0 } }, { ...opts, banker: 0 });
const result = { attacker_points: 50, kitty_points: 15, kitty_cards: ["S5", "H10", "D3", "D4", "C6", "C7", "S8", "H9"], winner_team: 0, level_change: 1, next_banker: 2, new_levels: ["6", "2"], games_won: [0, 0], point_scored: false, game_over: false,
  rating: { rating: 1219, delta: 7 } };
export const ROUND_END = base({ phase: "round_end", guest: false, ranked: true, matched: true, turn: null, trick: null, attacker_points: 50, hand: [], levels: ["5", "2"], trump: { suit: "S", rank: "5", declarer: 0 },
  last_trick: { leader: 0, plays: plays(0, 4, 1), winner: 0, points: 10 }, round_result: result }, { ...opts, banker: 0 });
