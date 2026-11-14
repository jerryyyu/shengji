// TypeScript contract for the Sheng Ji WebSocket protocol (PROTOCOL.md v1).
// Card codes: suited = suit letter (S H D C) + rank ("S2".."SA", "H10", ...);
// jokers = "LJ" (little/black) and "BJ" (big/red).

import type { QueueClientMsg, QueueErrorCode, QueueServerMsg } from "./queue/messages";

export interface HandCard {
  id: number;
  code: string;
}

export type Phase = "deal" | "declare" | "bury" | "play" | "round_end" | "game_over";

/** Ranks a game is played at, low to high. A team climbs through these, so the
 *  same list is the set of levels a room can be started at.
 *  Mirrors RANKS in server/shengji/engine/cards.py -- keep in sync. */
export const RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "10",
                      "J", "Q", "K", "A"] as const;
export type Rank = (typeof RANKS)[number];

// ---------- Client -> Server ----------

export type ClientMsg =
  | { type: "ping"; nonce: number }
  | {
      type: "create_room";
      name: string;
      /** Rank both teams start at. Omit for the standard game (2). */
      start_level?: Rank;
      /** Experimental W32 is available only through the guarded lobby UI. */
      test_policy?: "w32";
      test_access_key?: string;
      /** Continue this saved game of the signed-in account: the room is made
       *  with the account in its saved seat and bots in the other three, and
       *  starts at that game's last levels with its next banker. */
      resume_from?: string;
    }
  | { type: "add_bot" }
  /** Host only, before the game starts: the rank both teams begin at. */
  | { type: "set_start_level"; start_level: Rank }
  /** Host only, before the game starts: whether this created room is ranked
   *  (its rounds rated). A room starts unranked. */
  | { type: "set_ranked"; on: boolean }
  | { type: "remove_bot" }
  /** Before the game starts: the host exchanges the occupants of any two
   *  seats; anyone else moves themselves (one of a, b is their seat) to an
   *  empty seat, until they tap Start (`lobby_ready`). */
  /** `expect`: who the sender saw at a and b (null: empty); the server refuses if either changed. */
  | { type: "swap_seats"; a: number; b: number; expect?: [SeatOccupant | null, SeatOccupant | null] }
  /** Host only, before the game starts: send the person in this seat out of the room. */
  | { type: "remove_player"; seat: number; expect?: SeatOccupant }
  /** The opener's Start: the game starts at once. With others seated the
   *  room panel offers it as "Start now" once `start_now_in` reaches 0. */
  | { type: "start_game" }
  /** A created room's Start, anyone seated, before the game: the game starts
   *  when every connected person has tapped it. `on: false` takes it back. */
  | { type: "lobby_ready"; on?: boolean }
  | { type: "declare"; card_ids: number[] } // anytime during deal or declare phase
  | { type: "pass_declare" } // declare phase: marks you done with the declare window
  | { type: "bury"; card_ids: number[] }
  | { type: "play"; card_ids: number[] }
  | { type: "next_round" }
  /** Ranked table: the player is back after the move timer marked them away. */
  | { type: "im_back" }
  /** Any ordinary table, ranked or casual: whether newcomers may be offered
   *  a bot seat; anyone seated may switch it, a created room from its lobby. */
  | { type: "allow_joiners"; on: boolean }
  | { type: "chat"; text: string }
  /** Report another seat's player; the server answers report_received or a coded error. */
  | { type: "report_player"; seat: number; reason: ReportReason }
  | { type: "peek_room"; room: string }
  /** Which kind of thing a typed or linked code names (PROTOCOL.md "Codes"). */
  | { type: "code_lookup"; code: string }
  | { type: "join_room"; room: string; name: string; seat?: number; token?: string }
  | { type: "leave_room" } // anytime after joining; server replies {type:"left"}
  | QueueClientMsg;

export type ReportReason = "abuse" | "spam" | "cheating" | "other";

// ---------- Server -> Client ----------

export interface ErrorMsg {
  type: "error";
  message: string;
  /** Machine-readable case. Typed so a new server code cannot be handled by
   *  a stale client branch that silently falls through to a generic toast. */
  code?: ErrorCode;
  /** Set on a refused code_lookup only: the code it was asked about. */
  lookup?: string;
  /** A queue cooldown's end (Unix seconds, server clock), on code "cooldown". */
  cooldown_until?: number;
}

/** A seat's occupant as a room frame shows it, for a lobby action to name. */
export interface SeatOccupant { name: string; is_bot: boolean }

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
  /** Rank both teams start at, fixed when the room was created. */
  start_level: Rank;
  /** Present only for rooms explicitly created with the W32 test policy. */
  experimental_policy?: "w32";
  /** Built by the matchmaking queue: a rated game between strangers. */
  matched?: boolean;
  /** A created room its host switched to Ranked: its rounds are rated. */
  ranked?: boolean;
  /** The opener: the same seat as `host`. Only it sets the starting level
   *  and Ranked, and may Start now. */
  opener?: number;
  /** Whether newcomers may be offered a bot seat once the game is in play
   *  (any ordinary room; on at creation). Absent on a test room. */
  allow_joiners?: boolean;
  /** A signed-in player is seated, so the opener may switch Ranked on. */
  rankable?: boolean;
  /** The seats that tapped Start (`lobby_ready`). */
  ready?: number[];
  /** With someone besides the opener seated: seconds until the opener is
   *  offered Start now (0 once it is). Tick it down locally. */
  start_now_in?: number;
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
  /** Move timer (ranked tables): seconds this seat has left for the decision
   *  it owes (a play, a bury or the round-end Next); null when no clock runs
   *  for it. Tick it down locally, like takeover_in. Absent at a table
   *  without the move timer (casual and offline). */
  turn_deadline?: number | null;
  /** The move timer ran out too often: the bot is playing every decision for
   *  this present player until they are back. Absent where turn_deadline is. */
  away?: boolean;
  /** The owner pressed Leave: a bot plays the seat at once, and the table
   *  names it "Bot (Alice left)". Sent only while true. */
  left?: boolean;
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
  games_won: [number, number];
  /** True on the round that took a team past A. */
  point_scored: boolean;
  game_over: boolean;
  /** The receiving seat's own rating after this round; present only for a
   *  signed-in player, and only once the server has stored the round. */
  rating?: RoundRating;
  /** This seat was taken mid-round from an open table: not ranked for it. */
  unranked?: "joined" | "guest";
}

/** The table's corner line about an open-table newcomer: "trick", they take
 *  the seat after this trick; "round", they were seated at this round end and
 *  play from the next round. */
export interface JoinNotice {
  seat: number;
  name: string;
  when: "trick" | "round";
}

export interface RoundRating {
  rating: number;
  /** This round's change, rounded to a whole point. */
  delta: number;
  /** The change over the whole game, on the round that wins a game. */
  game_delta?: number;
}

export interface GameState {
  type: "state";
  room: string;
  you: number;
  /** Present only for rooms explicitly created with the W32 test policy. */
  experimental_policy?: "w32";
  /** Built by the matchmaking queue: a rated game between strangers. */
  matched?: boolean;
  /** A created room its host switched to Ranked: its rounds are rated. */
  ranked?: boolean;
  /** This viewer sits as a guest: their rounds are not ranked. */
  guest?: boolean;
  /** Tables that take joiners, ranked or casual: whether newcomers may be
   *  offered a bot seat. */
  allow_joiners?: boolean;
  /** Tables that take joiners: newcomers taking a seat (see JoinNotice). */
  joining?: JoinNotice[];
  /** Sent only to a newcomer waiting for its handover: `you` is the seat it
   *  takes, which the bot plays until the trick ends. */
  joining_you?: boolean;
  phase: Phase;
  ready?: number[];   // seats that confirmed the round end
  players: StatePlayer[];
  hand: HandCard[];
  levels: [string, string];
  /** Games won by each team. A team wins one by holding A; the levels
   *  then restart and play continues. NOT card points. */
  games_won: [number, number];
  banker: number | null;
  trump: Trump | null;
  turn: number | null; // whose action is awaited (bury/play); null during deal/declare
  // deal & declare phases (declaration is a race, not a rotation)
  declare_options: number[][]; // your valid declarations right now; [] if you can't beat the current one
  current_declaration: Declaration | null;
  passed: number[]; // seats done with the declare window (cleared when someone declares)
  /** Seconds left in the post-deal declare window; null outside it. Tick it
   *  down locally, like turn_deadline. */
  declare_deadline?: number | null;
  // play phase
  trick: Trick | null;
  last_trick: LastTrick | null;
  attacker_points: number;
  kitty_count: number;
  // round_end / game_over
  round_result: RoundResult | null;
  message: string | null;
  /** A notice outlives `message`, which the very next play clears. Today the
   *  only kind is a refused throw: the player needs to see WHAT they threw,
   *  and with bots the clearing play lands about 0.7 s later. The client may
   *  dismiss it early; that is per-viewer and never told to the server. */
  notice: Notice | null;
}

export interface Notice {
  /** Bumps per notice, so a dismissal applies to one notice, not the slot. */
  id: number;
  kind: "failed_throw";
  seat: number;
  /** What the player tried to throw. */
  attempted: string[];
  /** What the engine forced instead. Never the card that beat it: that is
   *  hidden information the thrower has not earned by throwing. */
  forced: string[];
}

export interface EventMsg {
  type: "event";
  kind: string;
  [key: string]: unknown;
}

/** Confirmation of leave_room; the connection may create/join rooms again. */
export interface LeftMsg {
  type: "left";
  /** Why the server sent this without a leave_room: the host removed this
   *  player; the away owner came back before a newcomer's handover
   *  (reclaimed); the game ended first (table_closed); or this away
   *  player's seat went to a newcomer (seat_given). */
  reason?: "removed" | "reclaimed" | "table_closed" | "seat_given" | "partner_left";
  message?: string;
}

export type ServerMsg =
  | { type: "heartbeat_ready" }
  | { type: "pong"; nonce: number }
  | ErrorMsg
  | RoomMsg
  | GameState
  | EventMsg
  | LeftMsg
  | RoomSeats
  | CodeKindMsg
  | ChatMsg
  | ChatHistory
  | ResumeMsg
  | ReportReceivedMsg
  | QueueServerMsg;

/** The server stored this viewer's report; ``message`` is shown as a toast. */
export interface ReportReceivedMsg {
  type: "report_received";
  seat: number;
  message: string;
}

/** Every coded error the server can send. Keep in sync with server.py —
 *  an unlisted code silently falls through to a generic toast. */
export type ErrorCode =
  | "room_not_found"
  | "room_full"
  | "choose_seat"
  | "seat_unavailable"
  | "seat_reserved"
  | "ranked_sign_in"
  | "ranked_queue_only"
  /** This device already holds a seat at the table (another tab). */
  | "same_device"
  /** The account plays a ranked game on another socket (or this device's
   *  signed-out guest would sit beside its own account's seat). */
  | "account_in_game"
  | "table_full"
  | "table_left"
  | "test_room_unavailable"
  | "bad_start_level"
  | "resume_unavailable"
  | "stale_connection"
  | "report_sign_in"
  | "report_bad_seat"
  | "report_bad_reason"
  | "report_bot"
  | "report_guest"
  | "report_rate_limited"
  | "report_not_stored"
  | QueueErrorCode;

/** "human" — a connected person; "bot" — a permanent bot seat;
 *  "bot_cover" — a bot covering someone who dropped. Never infer from is_bot. */
export type Controller = "human" | "bot" | "bot_cover";

/** Reply to code_lookup: room and pair codes share one space, so a code
 *  names a live room, a live pair, or nothing. */
export interface CodeKindMsg {
  type: "code_kind";
  code: string;
  kind: "room" | "party" | "none";
}

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
  /** A ranked table: `claimable` marks the seats its invite may take (bot
   *  seats, away seats from a round boundary); signed-in players only. */
  ranked?: boolean;
  /** A ranked table with no seat to take. */
  full?: boolean;
}
