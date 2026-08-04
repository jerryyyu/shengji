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
  | { type: "add_bot" }
  | { type: "remove_bot" }
  | { type: "start_game" }
  | { type: "declare"; card_ids: number[] } // anytime during deal or declare phase
  | { type: "pass_declare" } // declare phase: marks you done with the declare window
  | { type: "bury"; card_ids: number[] }
  | { type: "play"; card_ids: number[] }
  | { type: "next_round" }
  | { type: "chat"; text: string }
  | { type: "peek_room"; room: string }
  | { type: "join_room"; room: string; name: string; seat?: number }
  | { type: "leave_room" }; // anytime after joining; server replies {type:"left"}

// ---------- Server -> Client ----------

export interface ErrorMsg {
  type: "error";
  message: string;
  /** Machine-readable cases, e.g. "room_not_found" (clear saved room, back to lobby). */
  code?: string;
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
  /** Seconds until a bot covers this disconnected human; null otherwise.
   *  Tick it down locally — broadcasts are event-driven, not per-second. */
  takeover_in: number | null;
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
  ready?: number[];   // seats that confirmed the round end
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

/** Confirmation of leave_room; the connection may create/join rooms again. */
export interface LeftMsg {
  type: "left";
}

export type ServerMsg = ErrorMsg | RoomMsg | GameState | EventMsg | LeftMsg;

export interface RoomSeats {
  type: "room_seats";
  room: string;
  in_game: boolean;
  seats: { seat: number; name: string; is_bot: boolean; connected: boolean; team: number }[];
}
