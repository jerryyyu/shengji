// The canonical table_* names on the device, as server/shengji/api/tables.py
// rewrites them: each becomes the message the offline server already handles,
// so every check and refusal of that message applies to both names alike.
// The rewrite keeps every field the client sent and changes only `type` and
// the fields the target names differently.

type Json = Record<string, unknown>;

/** The canonical names the offline server takes. `table_move` is not one:
 *  its room meaning is `swap_seats`, which the offline server has no handler
 *  for. */
export const CANONICAL: ReadonlySet<string> = new Set([
  "table_start", "table_start_now", "table_start_bots", "table_allow_joiners",
  "table_start_level", "table_chat", "table_leave", "table_join", "table_peek",
]);

/** The queue's own refusal for an early Start now, said the same way in a room. */
export const TOO_SOON = "Start now opens 30 seconds after the last person sits.";

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

/** `msg` (a canonical name) from the person at a room's seat, before or
 *  during its game. `table_start_now` is the host's `start_game`; the caller
 *  gates it. */
export function forRoom(msg: Json): Json {
  switch (msg.type) {
    case "table_start": return as(msg, "lobby_ready");
    case "table_start_bots": return as(msg, "lobby_ready", { on: true });
    case "table_start_now": return as(msg, "start_game");
    case "table_allow_joiners": return as(msg, "allow_joiners");
    case "table_start_level": return as(msg, "set_start_level");
    case "table_chat": return as(msg, "chat");
    case "table_leave": return as(msg, "leave_room");
    case "table_join": return as(msg, "join_room", { room: msg.code ?? "" });
    case "table_peek": return as(msg, "peek_room", { room: msg.code ?? "" });
    default: return msg;
  }
}
