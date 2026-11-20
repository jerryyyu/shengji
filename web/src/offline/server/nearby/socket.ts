// The joiner's socket: a WebSocket look-alike over the nearby link, handed to
// ws.ts's Connection in place of the game server's socket, so the client
// protocol and the table UI run unchanged. It opens no URL, so the device key
// in socketUrl() never crosses; it sends only the hello and the joiner
// allow-list (protocol.ts), so presence, the queue, heartbeats, telemetry and
// chat stay on the phone.
import { type Clock, realClock } from "../clock";
import { LIMITS, NEARBY_V, PING_TEXT, PONG_TEXT, cleanJoinerMessage, parseObject, utf8Bytes, type NearbyHello } from "./protocol";
import type { JoinLink, LinkState, NearbyTransport } from "./transport";

type Handler<E> = ((ev: E) => void) | null;

export class NearbySocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;

  readyState = NearbySocket.CONNECTING;
  onopen: Handler<Event> = null;
  onmessage: Handler<MessageEvent> = null;
  onclose: Handler<CloseEvent> = null;
  onerror: Handler<Event> = null;
  private link: JoinLink | null = null;
  private onState: ((state: LinkState, detail?: string) => void) | null;
  private clock: Clock;
  /** Clock time of the host's latest frame, for the liveness check. */
  private heard = 0;

  constructor(transport: NearbyTransport, code: string, onState: ((state: LinkState, detail?: string) => void) | null = null,
              clock: Clock = realClock) {
    this.onState = onState;
    this.clock = clock;
    transport
      .join(code, {
        message: (text) => {
          if (this.readyState !== NearbySocket.OPEN) return;
          this.heard = this.clock.now();
          if (text === PONG_TEXT) return;
          this.onmessage?.({ data: text } as MessageEvent);
        },
        closed: () => this.finish(),
        state: (state, detail) => this.onState?.(state, detail),
      })
      .then(
        (link) => {
          if (this.readyState !== NearbySocket.CONNECTING) {
            link.close();
            return;
          }
          this.link = link;
          this.readyState = NearbySocket.OPEN;
          this.heard = this.clock.now();
          this.ping(link);
          this.onopen?.({} as Event);
        },
        () => this.finish(),
      );
  }

  /** Ping the host every LIMITS.pingSeconds, so it knows this phone is
   *  still there; a host silent for LIMITS.silentSeconds is gone, and the
   *  socket closes, as a dropped link would. */
  private ping(link: JoinLink): void {
    this.clock.setTimeout(() => {
      if (this.link !== link || this.readyState !== NearbySocket.OPEN) return;
      if (this.clock.now() - this.heard >= LIMITS.silentSeconds) {
        this.close();
        return;
      }
      try {
        link.send(PING_TEXT);
      } catch {
        this.close();
        return;
      }
      this.ping(link);
    }, LIMITS.pingSeconds);
  }

  /** The text that would cross the link for `data`, or null when nothing may. */
  static outbound(data: string): string | null {
    const msg = parseObject(data);
    if (msg === null) return null;
    let out: Record<string, unknown> | null;
    if (msg.type === "table_join" || msg.type === "table_peek") {
      const peek = msg.type === "table_peek";
      const seat = msg.seat;
      const hello: NearbyHello = {
        type: "nearby_hello",
        nearby_v: NEARBY_V,
        name: !peek && typeof msg.name === "string" ? msg.name.slice(0, LIMITS.name) : "",
        token: !peek && typeof msg.token === "string" && msg.token ? msg.token.slice(0, LIMITS.token) : null,
        peek,
        seat: !peek && typeof seat === "number" && Number.isInteger(seat) && seat >= 0 && seat < 4 ? seat : null,
      };
      out = { ...hello };
    } else {
      out = cleanJoinerMessage(msg);
    }
    if (out === null) return null;
    const text = JSON.stringify(out);
    return utf8Bytes(text) <= LIMITS.frameBytes ? text : null;
  }

  send(data: string): void {
    if (this.readyState !== NearbySocket.OPEN || !this.link) return;
    const text = NearbySocket.outbound(data);
    if (text === null) return;
    try {
      this.link.send(text);
    } catch {
      this.close();
    }
  }

  close(): void {
    if (this.readyState >= NearbySocket.CLOSING) return;
    this.link?.close();
    this.finish();
  }

  private finish(): void {
    if (this.readyState === NearbySocket.CLOSED) return;
    this.readyState = NearbySocket.CLOSED;
    this.link = null;
    this.onclose?.({} as CloseEvent);
  }
}
