// What may cross the nearby link from a joiner to the host. Both ends apply
// it: the joiner's NearbySocket so nothing else leaves the phone (no device
// key, account, telemetry or chat), and the host's NearbyHost because a
// modified joiner can send anything. A message is rebuilt from its allowed
// fields only; whatever else it carried is dropped, never forwarded.

/** Bumped on any change a host and a joiner must agree on. */
export const NEARBY_V = 2;
/** The Bonjour type; the native plugin and Info.plist carry the same one. */
export const NEARBY_SERVICE_TYPE = "_shengji-nearby._tcp";

export const LIMITS = {
  /** One frame either way, in UTF-8 bytes (NWProtocolWebSocket's cap). */
  frameBytes: 16 * 1024,
  /** Messages a joiner may send per second before the host closes it. */
  perSecond: 20,
  /** The hello must arrive this soon after the link opens. */
  helloSeconds: 5,
  /** Seated joiners plus links still in their hello. */
  peers: 6,
  /** Links not yet seated (in their hello or looking at the seats), one of
   *  them per phone. */
  unseated: 3,
  /** The joiner's socket pings this often while its link is open... */
  pingSeconds: 5,
  /** ...and either end treats a link silent this long as gone. */
  silentSeconds: 20,
  /** The host answers a ping at once: a joiner whose ping goes unanswered
   *  this long (after a move, or at its regular ping) treats the link as
   *  stuck, even while the host's own frames still arrive, and makes a new
   *  one. */
  pongSeconds: 4,
  /** A seat's resume must have its link up this soon (longer than the
   *  plugin's 4 s resume look plus its 3 s handshake), or the attempt is
   *  abandoned for a fresh one... */
  linkSeconds: 8,
  /** ...and the host's answer to its hello this soon after. */
  resumeSeconds: 5,
  /** The joiner logs the spread of its round trips this often. */
  summarySeconds: 30,
  /** A hand never holds more cards than this. */
  cardIds: 33,
  token: 64,
  name: 1000,
} as const;

type Json = Record<string, unknown>;

/** The liveness ping and its answer. They cross the link only: the host
 *  answers the ping itself and the joiner's socket keeps the pong. */
export const PING = "nearby_ping";
export const PONG = "nearby_pong";
export const PING_TEXT = JSON.stringify({ type: PING });
export const PONG_TEXT = JSON.stringify({ type: PONG });

/** The joiner's first message: version, display name and resume token, and
 *  nothing else. The code never crosses the link: holding it is what let the
 *  link's TLS handshake finish. */
export interface NearbyHello {
  type: "nearby_hello";
  nearby_v: number;
  name: string;
  token: string | null;
  /** Only look: the host answers with the table's seats and seats nobody,
   *  so the joiner can pick a seat before taking one. */
  peek?: boolean;
  /** The seat a newcomer asks for; the host gives the first free one when
   *  it is taken. */
  seat?: number | null;
}

const isInt = (v: unknown, lo: number, hi: number): v is number =>
  typeof v === "number" && Number.isInteger(v) && v >= lo && v <= hi;

function cardIds(v: unknown): number[] | null {
  if (!Array.isArray(v) || v.length < 1 || v.length > LIMITS.cardIds) return null;
  return v.every((i) => isInt(i, 0, 1_000_000)) ? (v as number[]) : null;
}

/** A joiner's game or lobby message, rebuilt from its allowed fields; null
 *  when its type is not allowed or a field is malformed. Chat, the opener's
 *  settings, Start now, create_room and every service message are absent;
 *  a joiner's own Start (and taking it back) is the shared table's ready. */
export function cleanJoinerMessage(msg: Json): Json | null {
  switch (msg.type) {
    case "declare":
    case "bury":
    case "play": {
      const ids = cardIds(msg.card_ids);
      return ids ? { type: msg.type, card_ids: ids } : null;
    }
    case "pass_declare":
    case "next_round":
    case "im_back":
    case "table_leave":
      return { type: msg.type };
    case "table_start":
      return msg.on === false ? { type: "table_start", on: false } : { type: "table_start" };
    case "table_move":
      // a joiner moves only themself
      return isInt(msg.seat, 0, 3) ? { type: "table_move", seat: msg.seat } : null;
    default:
      return null;
  }
}

/** The hello, checked; null when malformed. The joiner's page sends a
 *  table_join, which NearbySocket turns into this. */
export function cleanHello(msg: Json): NearbyHello | null {
  if (msg.type !== "nearby_hello" || typeof msg.nearby_v !== "number") return null;
  const name = typeof msg.name === "string" && msg.name.length <= LIMITS.name ? msg.name : "";
  const tok = msg.token;
  if (tok !== null && tok !== undefined && (typeof tok !== "string" || tok.length > LIMITS.token)) return null;
  const seat = isInt(msg.seat, 0, 3) ? msg.seat : null;
  return { type: "nearby_hello", nearby_v: msg.nearby_v, name, token: typeof tok === "string" && tok ? tok : null,
           peek: msg.peek === true, seat };
}

export function utf8Bytes(text: string): number {
  return new TextEncoder().encode(text).length;
}

/** Parses one frame as a JSON object, or null. */
export function parseObject(text: string): Json | null {
  try {
    const v = JSON.parse(text) as unknown;
    return typeof v === "object" && v !== null && !Array.isArray(v) ? (v as Json) : null;
  } catch {
    return null;
  }
}
