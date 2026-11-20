// Every code an `error` frame can carry, and who says it to the player.
//
// says:
//   "toast"  the app's toast shows the server's message (also any code not
//            listed here, and an error with no code)
//   "queue"  the queue panel says it: its notice in `text`, or Play's place
//            in the server's words when there is no `text`
//   "join"   the Join panel says it (a peek's refusal is always "join")
//   "app"    App handles it itself (back to Play, its own words)
//   "silent" no one says it; the queue store resyncs
//
// Listeners still act on codes (codeJoin re-peeks, the store counts a
// cooldown down); this table decides only who speaks.
//
// One `name: {` per line: server/tests/test_client_server_constants.py
// reads the keys from this file and checks them against every code the
// server raises.
export type Says = "toast" | "queue" | "join" | "app" | "silent";

export interface ErrorRoute {
  says: Says;
  /** The client's own words (title, then sub-line), when it has them. */
  text?: readonly [string, string?];
}

/** The answers a queue action can get. On any other error the queue store
 *  drops a Play in flight. */
const QUEUE_ROUTES = {
  signed_in_only: { says: "toast" },
  in_room: { says: "toast" },
  rate_limited: { says: "toast" },
  not_leader: { says: "toast" },
  bad_party: { says: "toast" },
  party_changed: { says: "toast" },
  partner_unavailable: { says: "toast" },
  not_queued: { says: "toast" },
  not_seated: { says: "toast" },
  start_failed: { says: "app" },
  in_queue: { says: "toast" },
  not_in_party: { says: "silent" },
  cooldown: { says: "toast" },
  no_offer: { says: "queue", text: ["That table is no longer open."] },
  bad_seat: { says: "queue", text: ["Pick one of the open seats."] },
  seat_taken: { says: "queue", text: ["That seat was just taken.", "Pick another."] },
  table_closed: { says: "queue", text: ["That table is no longer open."] },
  pair_seats_fixed: { says: "queue", text: ["A Duo's seats stay together."] },
  already_ready: { says: "queue", text: ["You tapped Start, so your seat is set."] },
  panel_changed: { says: "silent" },
  bad_mode: { says: "toast" },
  table_not_found: { says: "toast" },
  own_table: { says: "toast" },
  table_full: { says: "join" },
  not_opener: { says: "toast" },
  ranked_level_fixed: { says: "toast" },
  ranked_bots_fixed: { says: "toast" },
  bad_setting: { says: "toast" },
  too_soon: { says: "toast" },
} as const satisfies Record<string, ErrorRoute>;

/** Rooms, seats, reports, blocks, and the queue's codes a queue action does not
 *  answer with (seat_changed answers a seat pick at a table). */
const OTHER_ROUTES = {
  account_in_game: { says: "queue" },
  room_not_found: { says: "app" },
  no_room: { says: "app" },
  ranked_queue_only: { says: "app" },
  room_full: { says: "toast" },
  choose_seat: { says: "toast" },
  seat_unavailable: { says: "toast" },
  seat_reserved: { says: "toast" },
  seat_changed: { says: "toast" },
  same_device: { says: "toast" },
  table_left: { says: "toast" },
  bad_start_level: { says: "toast" },
  resume_unavailable: { says: "toast" },
  stale_connection: { says: "toast" },
  account_suspended: { says: "toast" },
  server_busy: { says: "toast" },
  retired: { says: "toast" },
  report_sign_in: { says: "toast" },
  report_bad_seat: { says: "toast" },
  report_bad_reason: { says: "toast" },
  report_bot: { says: "toast" },
  report_rate_limited: { says: "toast" },
  report_not_stored: { says: "toast" },
  block_bad_seat: { says: "toast" },
  block_bot: { says: "toast" },
  block_rate_limited: { says: "toast" },
  block_full: { says: "toast" },
} as const satisfies Record<string, ErrorRoute>;

export const ERROR_ROUTES = { ...QUEUE_ROUTES, ...OTHER_ROUTES } as const satisfies Record<string, ErrorRoute>;

/** Every coded error the server can send. */
export type ErrorCode = keyof typeof ERROR_ROUTES;

export const QUEUE_ANSWERS: ReadonlySet<string> = new Set(Object.keys(QUEUE_ROUTES));

const TOAST: ErrorRoute = { says: "toast" };
const JOIN: ErrorRoute = { says: "join" };

/** Who says this error. */
export function routeOf(msg: { code?: string; peek?: string }): ErrorRoute {
  if (msg.peek !== undefined) return JOIN;
  if (!msg.code || !Object.hasOwn(ERROR_ROUTES, msg.code)) return TOAST;
  return ERROR_ROUTES[msg.code as ErrorCode];
}
