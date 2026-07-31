// TypeScript contract for the Sheng Ji WebSocket protocol (PROTOCOL.md v1).
// Card codes: suited = suit letter (S H D C) + rank ("S2".."SA", "H10", ...);
// jokers = "LJ" (little/black) and "BJ" (big/red).

export interface HandCard {
  id: number;
  code: string;
}

export type Phase = "deal" | "declare" | "bury" | "play" | "round_end" | "game_over";

// ---------- Client -> Server ----------

export type ClientMsg =
  | { type: "create_room"; name: string }
  | { type: "join_room"; room: string; name: string }
  | { type: "add_bot" }
  | { type: "remove_bot" }
  | { type: "start_game" }
  | { type: "declare"; card_ids: number[] } // anytime during deal or declare phase
  | { type: "pass_declare" } // declare phase: marks you done with the declare window
  | { type: "bury"; card_ids: number[] }
  | { type: "play"; card_ids: number[] }
  | { type: "next_round" };

// ---------- Server -> Client ----------

export interface ErrorMsg {
  type: "error";
  message: string;
}

export interface RoomPlayer {
  seat: number;
  name: string;
  is_bot: boolean;
  connected: boolean;
}

export interface RoomMsg {
  type: "room";
  room: string;
  you: number;
  host: number;
  players: RoomPlayer[];
}

export interface StatePlayer {
  seat: number;
  name: string;
  is_bot: boolean;
  connected: boolean;
  team: 0 | 1; // seat % 2
  cards_left: number;
  is_banker: boolean;
}

export interface Trump {
  suit: string | null; // "S" | "H" | "D" | "C" | "NT"
  rank: string;
  declarer: number | null;
}

export interface TrickPlay {
  seat: number;
  cards: string[]; // codes only for other players
}

export interface Trick {
  leader: number;
  plays: TrickPlay[];
}

export interface LastTrick extends Trick {
  winner: number;
  points: number;
}

export interface Declaration {
  seat: number;
  cards: string[];
}

export interface RoundResult {
  attacker_points: number;
  kitty_points: number;
  kitty_cards: string[];
  winner_team: 0 | 1;
  level_change: number;
  next_banker: number;
  new_levels: [string, string];
  game_over: boolean;
}

export interface GameState {
  type: "state";
  room: string;
  you: number;
  phase: Phase;
  players: StatePlayer[];
  hand: HandCard[];
  levels: [string, string];
  banker: number | null;
  trump: Trump | null;
  turn: number | null; // whose action is awaited (bury/play); null during deal/declare
  // deal & declare phases (declaration is a race, not a rotation)
  declare_options: number[][]; // your valid declarations right now; [] if you can't beat the current one
  current_declaration: Declaration | null;
  passed: number[]; // seats done with the declare window (cleared when someone declares)
  // play phase
  trick: Trick | null;
  last_trick: LastTrick | null;
  attacker_points: number;
  kitty_count: number;
  // round_end / game_over
  round_result: RoundResult | null;
  message: string | null;
}

export interface EventMsg {
  type: "event";
  kind: string;
  [key: string]: unknown;
}

export type ServerMsg = ErrorMsg | RoomMsg | GameState | EventMsg;
