// A WebSocket look-alike whose peer is the in-page LocalServer, so ws.ts's
// Connection (reconnects, leave barrier, chat buffer, resume token) runs
// unchanged in offline mode. Frames cross it as JSON text, both ways, exactly
// as they would cross the network.
import { nativeRemoteBot } from "./pybot";
import { LocalServer, type LocalConnection } from "./server";
import { retired } from "./tables";

let shared: LocalServer | null = null;

/** The page's one offline server: a reconnect finds its room again. In the
 *  app, creating it starts the release bot in the background (pybot.ts). The
 *  app sets `__shengjiOfflineAutoplay` only when launched with
 *  -offline-autoplay (a device check of the bots, run from Xcode). */
export function localServer(): LocalServer {
  const autoplay = (globalThis as { __shengjiOfflineAutoplay?: unknown }).__shengjiOfflineAutoplay === true;
  shared ??= new LocalServer({ remote: nativeRemoteBot(), autoplay });
  return shared;
}

type Handler<E> = ((ev: E) => void) | null;

/** The messages the on-device server answers. The page sends the game
 *  server's own as well (the queue, presence, code lookups, telemetry,
 *  heartbeats); offline they go nowhere, as to a server that has no such
 *  service, so none of them comes back as an error toast. */
export const LOCAL_MESSAGES: ReadonlySet<string> = new Set([
  "create_room", "declare", "pass_declare", "bury", "play", "next_round",
  // the canonical table names (tables.ts): a room refuses the ones that set a
  // table up before its game, and rewrites the rest to its own
  "table_move", "table_start", "table_start_now", "table_start_bots", "table_allow_joiners",
  "table_start_level", "table_relaxed_bots", "table_chat", "table_leave", "table_join", "table_peek",
]);

/** A message the device answers: one of LOCAL_MESSAGES, or a retired name,
 *  which it refuses as the game server does. */
function localType(data: string): boolean {
  try {
    const msg = JSON.parse(data) as Record<string, unknown> | null;
    if (typeof msg !== "object" || msg === null) return false;
    return (typeof msg.type === "string" && LOCAL_MESSAGES.has(msg.type)) || retired(msg);
  } catch {
    return false;
  }
}

export class LocalSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;

  readyState = LocalSocket.CONNECTING;
  onopen: Handler<Event> = null;
  onmessage: Handler<MessageEvent> = null;
  onclose: Handler<CloseEvent> = null;
  onerror: Handler<Event> = null;
  private conn: LocalConnection;
  private server: LocalServer;

  constructor(server: LocalServer = localServer()) {
    this.server = server;
    this.conn = server.connect((text) => {
      if (this.readyState === LocalSocket.OPEN) this.onmessage?.({ data: text } as MessageEvent);
    });
    server.clock.setTimeout(() => {
      if (this.readyState !== LocalSocket.CONNECTING) return;
      this.readyState = LocalSocket.OPEN;
      this.onopen?.({} as Event);
    }, 0);
  }

  send(data: string): void {
    if (this.readyState !== LocalSocket.OPEN || !localType(data)) return;
    this.server.clock.setTimeout(() => this.conn.receive(data), 0);
  }

  close(): void {
    if (this.readyState >= LocalSocket.CLOSING) return;
    this.readyState = LocalSocket.CLOSED;
    this.conn.close();
    this.server.clock.setTimeout(() => this.onclose?.({} as CloseEvent), 0);
  }
}
