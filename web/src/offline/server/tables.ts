// The canonical table_* names on the device, as server/shengji/api/tables.py
// rewrites them: each becomes the message the offline server already handles,
// so every check and refusal of that message applies to it. Those handled
// names are the server's own: a frame that carries one is refused unread
// (`RETIRED`), as the game server refuses it. The rewrite keeps every field
// the client sent and changes only `type` and the fields the target names
// differently.

type Json = Record<string, unknown>;

/** The canonical names the offline server takes. */
export const CANONICAL: ReadonlySet<string> = new Set([
  "table_move", "table_start", "table_start_now", "table_start_bots", "table_allow_joiners",
  "table_start_level", "table_bot_level", "table_chat", "table_leave", "table_join", "table_peek",
]);

/** tables.py LOBBY: what sets a table up before its game. A room's game has
 *  always started, so in a room each is refused. */
export const LOBBY: ReadonlySet<string> = new Set([
  "table_move", "table_start", "table_start_now", "table_start_bots", "table_start_level",
  "table_bot_level",
]);

/** tables.py RETIRED: the names a canonical name replaced, the created
 *  room's old lobby controls, `code_lookup`, whose question `table_peek`
 *  answers, the Duo made by its own code and the ready check's answers.
 *  `queue_join` is one only with a `code`. */
export const RETIRED: ReadonlySet<string> = new Set([
  "swap_seats", "lobby_ready", "table_unready", "start_game", "queue_start_bots",
  "allow_joiners", "set_start_level", "chat", "leave_room", "queue_leave",
  "join_room", "queue_join", "peek_room", "code_lookup",
  "add_bot", "remove_bot", "remove_player", "set_ranked",
  "party_create", "party_invite", "party_join", "match_accept", "match_decline",
]);

/** tables.py RETIRED_MESSAGE. */
export const RETIRED_MESSAGE = "This page is out of date. Reload to play.";

/** tables.py retired: whether a client frame uses a retired name. */
export function retired(msg: Json): boolean {
  const t = msg.type;
  if (typeof t !== "string" || !RETIRED.has(t)) return false;
  return t !== "queue_join" || (msg.code !== undefined && msg.code !== null);
}

const as = (msg: Json, type: string, fields: Json = {}): Json => ({ ...msg, type, ...fields });

/** tables.py normalize_code. */
const normalizeCode = (raw: unknown): string => String(raw ?? "").trim().toUpperCase();

/** `msg` (a canonical name) from a socket outside any room, or null when its
 *  target is a queue message: the device has no queue, so those go nowhere,
 *  as their old names do. A Join's code is always a room's: the device has
 *  no queue tables, so a code that names nothing gets the room's refusal. */
export function forQueue(msg: Json): Json | null {
  const t = msg.type;
  if (t === "table_join") return as(msg, "join_room", { room: normalizeCode(msg.code) });
  if (t === "table_peek") return as(msg, "peek_room", { room: normalizeCode(msg.code) });
  return null;
}

/** `msg` (a canonical name) from a person seated in a room's game. The names
 *  that set a table up before its game (`LOBBY`) stay as they are, for the
 *  room to refuse. */
export function forRoom(msg: Json): Json {
  switch (msg.type) {
    case "table_allow_joiners": return as(msg, "allow_joiners");
    case "table_chat": return as(msg, "chat");
    case "table_leave": return as(msg, "leave_room");
    case "table_join": return as(msg, "join_room", { room: msg.code ?? "" });
    case "table_peek": return as(msg, "peek_room", { room: msg.code ?? "" });
    default: return msg;
  }
}
