// The matchmaking queue's messages (PROTOCOL.md "Matchmaking queue"). Times
// named `*_at`, `since`, `deadline` and `cooldown_until` are Unix seconds on
// the server's clock; `deadline_in` and `cooldown_secs` are relative seconds.

export type QueueClientMsg =
  | { type: "queue_join"; party_id?: string }
  | { type: "queue_leave" }
  | { type: "match_accept"; match_id: string }
  | { type: "match_decline"; match_id: string; keep_waiting?: boolean }
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
}

export interface QueueCountMsg { type: "queue_count"; count: number }

export interface MatchMsg {
  type: "match";
  match_id: string;
  deadline: number;
  deadline_in: number;
  /** Humans who must accept. */
  size: number;
  /** Bot seats. */
  bots: number;
  party_id: string | null;
}

export interface MatchReadyMsg {
  type: "match_ready";
  match_id: string;
  accepted: number;
  of: number;
  /** The humans in seat order, only once everyone has accepted. */
  names?: string[];
}

export interface MatchStartedMsg { type: "match_started"; match_id: string | null; room: string; rated: boolean }

export interface MatchCancelledMsg {
  type: "match_cancelled";
  match_id: string;
  reason: "player_missed" | "keep_waiting" | "server_error";
}

export interface QueueRemovedMsg {
  type: "queue_removed";
  reason: "declined" | "missed" | "away" | "in_room";
  cooldown_until: number | null;
  match_id?: string;
  /** For a pair: the member who missed or left. */
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
  | MatchMsg
  | MatchReadyMsg
  | MatchStartedMsg
  | MatchCancelledMsg
  | QueueRemovedMsg
  | PartyMsg
  | PartyClosedMsg;

export type QueueErrorCode =
  | "signed_in_only" | "in_room" | "rate_limited" | "cooldown" | "not_leader"
  | "bad_party" | "party_incomplete" | "party_changed" | "partner_unavailable"
  | "not_queued" | "match_pending" | "no_match" | "stale_match" | "start_failed"
  | "party_not_found" | "party_full" | "party_busy" | "in_queue" | "in_party"
  | "not_in_party";

export const QUEUE_ERROR_CODES: ReadonlySet<string> = new Set<QueueErrorCode>([
  "signed_in_only", "in_room", "rate_limited", "cooldown", "not_leader",
  "bad_party", "party_incomplete", "party_changed", "partner_unavailable",
  "not_queued", "match_pending", "no_match", "stale_match", "start_failed",
  "party_not_found", "party_full", "party_busy", "in_queue", "in_party",
  "not_in_party",
]);
