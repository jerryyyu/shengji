// The matchmaking queue's messages (PROTOCOL.md "Matchmaking queue"). Times
// named `*_at` and `since` are Unix seconds on the server's clock.

/** A queue message; a guest adds the name it plays under (the server keeps
 *  an account's own name and ignores this one). */
export type QueueClientMsg = { name?: string } & (
  /** What the queue holds for this socket; answered with queue_state. */
  | { type: "queue_status" }
  /** `mode` (default "ranked"): which tables to sit at, join or open.
   *  Casual tables are unrated and never seat a ranked searcher, or the
   *  reverse. Guests may queue in either. */
  | {
      type: "queue_join"; party_id?: string; mode?: QueueMode;
      /** A friend's table code (its invite link, or a code_kind "table"):
       *  sit at that waiting table, in its mode and with its settings
       *  (`mode`, `allow_joiners` and `start_level` are then ignored). */
      code?: string;
      /** Your own table's Allow joiners (default true). */
      allow_joiners?: boolean;
      /** Your own casual table's starting level (default "2"); a ranked
       *  table refuses anything but "2" with `ranked_level_fixed`. */
      start_level?: string;
      /** Open your own table as a Duo: the seat opposite you is held for
       *  the first single who joins by the table's code (ignored with
       *  `code`, and for a full party, which queues as the pair). */
      duo?: boolean;
    }
  | { type: "queue_leave" }
  /** `panel_seq` is the queue_state's: a Start sent against a panel that has
   *  since changed is refused with `panel_changed`. */
  | { type: "table_start"; panel_seq?: number }
  | { type: "queue_start_bots"; panel_seq?: number }
  /** Move yourself to an empty seat at your waiting table (singles only,
   *  before your Start). */
  | { type: "table_move"; seat: number }
  /** Answer the "still here?" prompt (`still_here_until`). */
  | { type: "table_here" }
  /** A chat line to everyone at your waiting table (<=300 chars, trimmed;
   *  30 a minute). Never logged; it becomes the room's chat when the table
   *  starts. */
  | { type: "table_chat"; text: string }
  /** Your table's Allow joiners, alone or at a waiting table (anyone
   *  seated, as in a room). Off: Play seats no stranger with you and
   *  offers you no open table; your code still works. */
  | { type: "table_allow_joiners"; on: boolean }
  /** Your casual table's starting level (the opener only). Clears every
   *  Start at the table. */
  | { type: "table_start_level"; start_level: string }
  | { type: "queue_wait_players" }
  | { type: "queue_allow_bots" }
  | { type: "party_create" }
  | { type: "party_join"; code: string }
  | { type: "party_leave" }
  /** Take this seat at the offered open table; the first confirm wins. */
  | { type: "open_table_join"; room: string; seat: number; panel_seq?: number }
  /** Keep looking: the offered table is not offered again by itself in this
   *  search; the next queue_join forgets it. */
  | { type: "open_table_wait" }
  /** The bar's open-table chip: the offer again, with a fresh clock. */
  | { type: "open_table_show"; room?: string });

export type QueueMode = "ranked" | "casual";

export interface QueueStateMsg {
  type: "queue_state";
  queued: boolean;
  /** Queued: the mode the search is in. */
  mode?: QueueMode;
  count: number;
  since?: number;
  front?: boolean;
  party_id?: string | null;
  leader?: boolean;
  /** Null while the entry waits for real players only. */
  bots_at?: number | null;
  wait_players?: boolean;
  /** Another socket of yours took the search over: on another device or
   *  in another window of this one (`by`), stopping it (`stopped`) or
   *  holding it there. */
  replaced?: boolean;
  by?: "device" | "window";
  stopped?: boolean;
  /** Not queued: a queue cooldown runs until then (Play counts it down). */
  cooldown_until?: number;
  /** Another socket of yours (another device or window) holds the search:
   *  no table, offer or timer is sent here; any queue action takes it over. */
  elsewhere?: boolean;
  /** The waiting table you sit at; null while you are alone in the queue. */
  table?: WaitingTableMsg | null;
  /** Your bot wait stands still: an open table is offered or can be joined. */
  bots_paused?: boolean;
  /** An open table offered to you now; null when none is. */
  offer?: OpenTableOfferMsg | null;
  /** Open tables you waited on that can still be joined (the bar's chip). */
  open_tables?: number;
  /** Changes whenever the panel's kind or target changes (alone, an offer of
   *  one room, a waiting table); the same across re-renders of one panel.
   *  Send it back with a Start or Join. */
  panel_seq?: number;
  /** Asked "still here?" at a table with no timer: answer with table_here
   *  before then, or you leave the table (queue_removed idle). */
  still_here_until?: number | null;
  /** Queued: your table's code (alone, your own; at a waiting table, its
   *  opener's). Invite links are `/?code=CODE`; the room the table starts
   *  has this code. */
  code?: string;
  /** Queued: your table's Allow joiners and starting level. */
  allow_joiners?: boolean;
  start_level?: string;
  /** Queued: you opened this table (alone, always), so you set its level
   *  and Allow joiners. */
  opener?: boolean;
  /** Queued: a Duo table's opener, or either member of a Duo made there. */
  duo?: boolean;
  /** Queued: the seat your entry holds for your friend (2 while alone),
   *  else your table's first held seat, or null. */
  held_seat?: number | null;
  /** Queued in a Duo made at a table: how many of you tapped Start (each
   *  member taps; null otherwise), and whether you did. */
  duo_ready?: number | null;
  you_ready?: boolean;
}

/** A seat at an offered open table, in seat order (team 0 at seats 0+2). */
export interface OfferSeatMsg {
  name: string;
  bot: boolean;
  /** You may take it: a bot's seat, or an away player's from a round end. */
  open: boolean;
}

/** A ranked game in progress with a seat for you. */
export interface OpenTableOfferMsg {
  room: string;
  seats: OfferSeatMsg[];
  /** The seat picked for you: the lone player's partner when it is open. */
  pick: number;
  /** When the offer lapses into Wait. */
  expires_at: number;
  /** At a round end you play, ranked, from the next round; mid-round the
   *  round you join is unranked for you. */
  round_end: boolean;
  /** A Duo's offer: your partner's seat (opposite yours) and name. Neither
   *  of you picks; either Join takes both seats. */
  partner?: { seat: number; name: string } | null;
}

/** One taken seat at a waiting table. */
export interface TableSeatMsg {
  name: string;
  you: boolean;
  /** Tapped Start (for a pair, its leader did). */
  ready: boolean;
  /** The app is away; the seat is held for a minute. */
  reconnecting: boolean;
  /** When this person sat down. */
  since: number | null;
  pair: boolean;
  leader: boolean;
}

/** A shared ranked waiting table: four seats in seat order (team 0 at seats
 *  0+2), null for an empty one, which a bot takes when the table starts. */
export interface WaitingTableMsg {
  id: string;
  /** The table's code (its opener's), which the room keeps. */
  code?: string;
  /** The opener's seat. */
  opener?: number;
  /** The empty seats held for a Duo opener's friend, and the first of
   *  them (null when none). */
  held_seat?: number | null;
  held_seats?: number[];
  seats: (TableSeatMsg | null)[];
  you: number;
  /** The table's bot timer and whose it is; null when every switch is on. */
  timer: { at: number; name: string; you: boolean } | null;
  /** People whose Start is in, of the people seated. */
  ready: number;
  of: number;
  you_ready: boolean;
  /** Who else has yet to tap Start, by name (a pair by its leader). */
  waiting_for: string[];
}

export interface QueueCountMsg { type: "queue_count"; count: number }

/** The Play tab's presence line, to every lobby socket on change. Counts
 *  only: open tables, connected people at them, people queued, and the open
 *  tables split by mode (`ranked` + `casual` = `tables`). */
export interface PresenceMsg {
  type: "presence"; tables: number; playing: number; waiting: number;
  ranked?: number; casual?: number;
}

/** A line of your table's chat; you get your own lines too. `id` counts up
 *  per table; `seat` is the sender's seat there (alone: the seat you take
 *  against bots). */
export interface TableChatMsg {
  /** The waiting table's id, or null while you wait alone at your own table. */
  type: "table_chat"; table: string | null; id: number; seat: number; name: string; text: string; t: number;
}

/** Your table's chat so far, replacing what you hold: when you sit down at
 *  a table that has some, when a newcomer's lines from alone merge in, or
 *  when you come back (`table` null: your own table, alone). */
export interface TableChatHistoryMsg {
  type: "table_chat_history"; table: string | null;
  messages: Omit<TableChatMsg, "type" | "table">[];
}

/** Someone else at your waiting table moved to `seat` (the queue_state
 *  with the new seats arrives just before it). */
export interface TableMovedMsg { type: "table_moved"; name: string; seat: number; your_team: boolean }

/** Once per game you started alone: its first newcomer's Join landed. */
export interface FirstJoinerMsg {
  type: "first_joiner";
  name: string;
  seat: number;
  /** The move clock that runs from now on; null without one. */
  move_secs: number | null;
  /** The newcomer plays from the next round. */
  round_end: boolean;
}

export interface MatchStartedMsg {
  type: "match_started"; match_id: string | null; room: string; rated: boolean;
  /** An open table's seat is yours after the bot's trick (state frames carry joining_you). */
  joining?: boolean;
  seat?: number;
  /** The seat is a guest's: its rounds are not ranked. */
  guest?: boolean;
}

/** The room could not be built: you are back in the queue at the front. */
export interface MatchCancelledMsg {
  type: "match_cancelled";
  match_id: string | null;
  reason: "server_error";
}

export interface QueueRemovedMsg {
  type: "queue_removed";
  reason: "away" | "in_room" | "idle";
  cooldown_until: null;
  /** For a pair: the member who left. */
  by?: string;
}

export interface PartyMember { name: string; leader: boolean; you: boolean }

export interface PartyMsg {
  type: "party";
  party_id: string;
  /** A Duo made at a table (`table`) has no code of its own: this is its
   *  table's code while queued, else empty. */
  code: string;
  table?: boolean;
  you_lead: boolean;
  members: PartyMember[];
  expires_at: number;
}

export interface PartyClosedMsg {
  type: "party_closed";
  party_id: string;
  reason: "left" | "expired";
  by?: string;
  you?: boolean;
}

export type QueueServerMsg =
  | QueueStateMsg
  | QueueCountMsg
  | PresenceMsg
  | TableChatMsg
  | TableChatHistoryMsg
  | TableMovedMsg
  | FirstJoinerMsg
  | MatchStartedMsg
  | MatchCancelledMsg
  | QueueRemovedMsg
  | PartyMsg
  | PartyClosedMsg;

export type QueueErrorCode =
  | "signed_in_only" | "in_room" | "rate_limited" | "not_leader"
  | "bad_party" | "party_incomplete" | "party_changed" | "partner_unavailable"
  | "not_queued" | "not_seated" | "no_match" | "start_failed"
  | "party_not_found" | "party_full" | "party_busy" | "in_queue" | "in_party"
  | "not_in_party" | "cooldown" | "no_offer" | "bad_seat" | "seat_taken" | "table_closed"
  | "pair_seats_fixed" | "already_ready" | "panel_changed" | "bad_mode"
  | "table_not_found" | "own_table" | "table_full" | "not_opener"
  | "ranked_level_fixed" | "bad_setting";

export const QUEUE_ERROR_CODES: ReadonlySet<string> = new Set<QueueErrorCode>([
  "signed_in_only", "in_room", "rate_limited", "not_leader",
  "bad_party", "party_incomplete", "party_changed", "partner_unavailable",
  "not_queued", "not_seated", "no_match", "start_failed",
  "party_not_found", "party_full", "party_busy", "in_queue", "in_party",
  "not_in_party", "cooldown", "no_offer", "bad_seat", "seat_taken", "table_closed",
  "pair_seats_fixed", "already_ready", "panel_changed", "bad_mode",
  "table_not_found", "own_table", "table_full", "not_opener",
  "ranked_level_fixed", "bad_setting",
]);
