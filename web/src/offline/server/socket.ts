// A WebSocket look-alike whose peer is the in-page LocalServer, so ws.ts's
// Connection (reconnects, leave barrier, chat buffer, resume token) runs
// unchanged in offline mode. Frames cross it as JSON text, both ways, exactly
// as they would cross the network.
import { LocalServer, type LocalConnection } from "./server";

let shared: LocalServer | null = null;

/** The page's one offline server: a reconnect finds its room again. */
export function localServer(): LocalServer {
  shared ??= new LocalServer();
  return shared;
}

type Handler<E> = ((ev: E) => void) | null;

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
    if (this.readyState !== LocalSocket.OPEN) return;
    this.server.clock.setTimeout(() => this.conn.receive(data), 0);
  }

  close(): void {
    if (this.readyState >= LocalSocket.CLOSING) return;
    this.readyState = LocalSocket.CLOSED;
    this.conn.close();
    this.server.clock.setTimeout(() => this.onclose?.({} as CloseEvent), 0);
  }
}
