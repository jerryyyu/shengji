// The matchmaking queue's messages (PROTOCOL.md "Matchmaking queue"). Times
// named `*_at` and `since` are Unix seconds on the server's clock.

export type QueueClientMsg =
  | { type: "queue_join"; party_id?: string }
  | { type: "queue_leave" }
  | { type: "table_start" }
  | { type: "queue_start_bots" }
  | { type: "queue_wait_players" }
  | { type: "queue_allow_bots" }
  | { type: "party_create" }
  | { type: "party_join"; code: string }
  | { type: "party_leave" };

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
  /** The waiting table you sit at; null while you are alone in the queue. */
  table?: WaitingTableMsg | null;
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

export interface MatchStartedMsg { type: "match_started"; match_id: string | null; room: string; rated: boolean }

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
  | "not_in_party";

export const QUEUE_ERROR_CODES: ReadonlySet<string> = new Set<QueueErrorCode>([
  "signed_in_only", "in_room", "rate_limited", "not_leader",
  "bad_party", "party_incomplete", "party_changed", "partner_unavailable",
  "not_queued", "not_seated", "no_match", "start_failed",
  "party_not_found", "party_full", "party_busy", "in_queue", "in_party",
  "not_in_party",
]);
