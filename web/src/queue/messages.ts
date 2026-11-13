// The matchmaking queue's messages (PROTOCOL.md "Matchmaking queue"). Times
// named `*_at` and `since` are Unix seconds on the server's clock.

/** A queue message; a guest adds the name it plays under (the server keeps
 *  an account's own name and ignores this one). */
export type QueueClientMsg = { name?: string } & (
  /** What the queue holds for this socket; answered with queue_state. */
  | { type: "queue_status" }
  | { type: "queue_join"; party_id?: string }
  | { type: "queue_leave" }
  | { type: "table_start" }
  | { type: "queue_start_bots" }
  | { type: "queue_wait_players" }
  | { type: "queue_allow_bots" }
  | { type: "party_create" }
  | { type: "party_join"; code: string }
  | { type: "party_leave" }
  /** Take this seat at the offered open table; the first confirm wins. */
  | { type: "open_table_join"; room: string; seat: number }
  /** Keep queuing: the offered table is not offered again by itself. */
  | { type: "open_table_wait" }
  /** The bar's open-table chip: the offer again, with a fresh clock. */
  | { type: "open_table_show"; room?: string });

export interface QueueStateMsg {
  type: "queue_state";
  queued: boolean;
  count: number;
  since?: number;
  front?: boolean;
  party_id?: string | null;
  leader?: boolean;
  /** Null while the entry waits for real players only. */
  bots_at?: number | null;
  wait_players?: boolean;
  replaced?: boolean;
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
  /** A pair's offer: your partner's seat (opposite yours) and name. Neither
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
  code: string;
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
  | "not_in_party" | "cooldown" | "no_offer" | "bad_seat" | "seat_taken" | "table_closed";

export const QUEUE_ERROR_CODES: ReadonlySet<string> = new Set<QueueErrorCode>([
  "signed_in_only", "in_room", "rate_limited", "not_leader",
  "bad_party", "party_incomplete", "party_changed", "partner_unavailable",
  "not_queued", "not_seated", "no_match", "start_failed",
  "party_not_found", "party_full", "party_busy", "in_queue", "in_party",
  "not_in_party", "cooldown", "no_offer", "bad_seat", "seat_taken", "table_closed",
]);
