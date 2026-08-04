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
  | { type: "join_room"; room: string; name: string; seat?: number; token?: string }
  | { type: "leave_room" }; // anytime after joining; server replies {type:"left"}

// ---------- Server -> Client ----------

export interface ErrorMsg {
  type: "error";
  message: string;
  /** Machine-readable case. Typed so a new server code cannot be handled by
   *  a stale client branch that silently falls through to a generic toast. */
  code?: ErrorCode;
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
  /** "human" | "bot" | "bot_cover" — explicit, not inferred from is_bot. */
  controller: Controller;
  /** Name of the absent owner while a bot covers their seat. */
  reserved_for: string | null;
  /** Seconds this seat stays exclusively its owner's after a drop; null once
   *  the window has passed and anyone may claim it. Same deadline as
   *  takeover_in, so the two can never disagree. */
  reserved_secs: number | null;
}

export interface Trump {
  suit: string | null; // "S" | "H" | "D" | "C" | "NT"
  rank: string;
  declarer: number | null;
}

/** What a play IS, as decided by the engine. The client cannot compute this:
 *  whether pairs form a tractor depends on consecutiveness under the trump
 *  ordering, where trump-rank cards and jokers sit outside their printed
 *  ranks. */
export type PlayShape = "single" | "pair" | "tractor" | "throw";

export interface TrickPlay {
  seat: number;
  cards: string[]; // codes only for other players
  shape?: PlayShape;
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

export type ServerMsg =
  | ErrorMsg
  | RoomMsg
  | GameState
  | EventMsg
  | LeftMsg
  | RoomSeats
  | ChatMsg
  | ChatHistory
  | ResumeMsg;

/** Every coded error the server can send. Keep in sync with server.py —
 *  an unlisted code silently falls through to a generic toast. */
export type ErrorCode =
  | "room_not_found"
  | "room_full"
  | "choose_seat"
  | "seat_unavailable"
  | "seat_reserved"
  | "stale_connection";

/** "human" — a connected person; "bot" — a permanent bot seat;
 *  "bot_cover" — a bot covering someone who dropped. Never infer from is_bot. */
export type Controller = "human" | "bot" | "bot_cover";

export interface ChatHistory {
  type: "chat_history";
  room: string;
  through_id: number;
  messages: ChatMsg[];
}

export interface ChatMsg {
  type: "chat";
  id: number;
  room: string;
  seat: number;      // -1 marks a system line
  name: string;
  text: string;
  t: number;
}

export interface ResumeMsg {
  type: "resume";
  token: string;
  gen: number;
}

export interface RoomSeats {
  type: "room_seats";
  room: string;
  in_game: boolean;
  seats: {
    seat: number; name: string; is_bot: boolean; connected: boolean;
    team: number;
    /** Bot seat, OR a human who has dropped (a bot is covering it). */
    claimable: boolean;
    controller: Controller;
    reserved_secs: number | null;
  }[];
}
