// The joiner's socket: a WebSocket look-alike over the nearby link, handed to
// ws.ts's Connection in place of the game server's socket, so the client
// protocol and the table UI run unchanged. It opens no URL, so the device key
// in socketUrl() never crosses; it sends only the hello and the joiner
// allow-list (protocol.ts), so presence, the queue, heartbeats, telemetry and
// chat stay on the phone.
import { type Clock, realClock } from "../clock";
import { frameType, nearbyLog } from "../../../nearbyLog";
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
  /** Clock time of the ping still waiting for its pong, or null. */
  private pingSent: number | null = null;
  /** Clock time of the latest move sent, until the host's next state. */
  private movedAt: number | null = null;

  constructor(transport: NearbyTransport, code: string, onState: ((state: LinkState, detail?: string) => void) | null = null,
              clock: Clock = realClock) {
    this.onState = onState;
    this.clock = clock;
    transport
      .join(code, {
        message: (text) => {
          if (this.readyState !== NearbySocket.OPEN) return;
          const now = this.clock.now();
          this.heard = now;
          if (text === PONG_TEXT) {
            if (this.pingSent !== null) nearbyLog("socket", `pong in ${Math.round((now - this.pingSent) * 1000)} ms`);
            this.pingSent = null;
            return;
          }
          const type = frameType(text);
          if (this.movedAt !== null && (type === "state" || type === "error" || type === "room")) {
            nearbyLog("socket", `in ${type}, ${Math.round((now - this.movedAt) * 1000)} ms after the move`);
            this.movedAt = null;
          } else nearbyLog("socket", `in ${type}`);
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
          nearbyLog("socket", "open");
          this.ping(link);
          this.onopen?.({} as Event);
        },
        () => this.finish(),
      );
  }

  /** Ping the host every LIMITS.pingSeconds, so it knows this phone is
   *  still there; a host silent for LIMITS.silentSeconds is gone, and a
   *  ping unanswered for LIMITS.pongSeconds means this phone's frames are
   *  not reaching it: either way the socket closes, as a dropped link
   *  would, and the page makes a new link and takes its seat back. */
  private ping(link: JoinLink): void {
    this.clock.setTimeout(() => {
      if (this.link !== link || this.readyState !== NearbySocket.OPEN) return;
      if (this.clock.now() - this.heard >= LIMITS.silentSeconds) return this.stuck("the host is silent");
      if (this.pingSent !== null && this.clock.now() - this.pingSent >= LIMITS.pongSeconds) {
        return this.stuck("no pong");
      }
      if (this.pingSent === null && !this.sendPing(link)) return;
      this.ping(link);
    }, LIMITS.pingSeconds);
  }

  private sendPing(link: JoinLink): boolean {
    try {
      link.send(PING_TEXT);
    } catch {
      this.close();
      return false;
    }
    this.pingSent = this.clock.now();
    return true;
  }

  /** Right after a move: a ping, whose pong must come back within
   *  LIMITS.pongSeconds, so a move that is not getting through turns into
   *  a new link within seconds instead of waiting on the move clock. */
  private probe(link: JoinLink): void {
    if (this.pingSent === null && !this.sendPing(link)) return;
    const sent = this.pingSent;
    this.clock.setTimeout(() => {
      if (this.link === link && this.readyState === NearbySocket.OPEN && this.pingSent === sent && sent !== null) {
        this.stuck("no pong after a move");
      }
    }, LIMITS.pongSeconds);
  }

  private stuck(why: string): void {
    nearbyLog("socket", `STUCK: ${why}; making a new link`);
    this.close();
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
    const link = this.link;
    try {
      link.send(text);
    } catch {
      this.close();
      return;
    }
    nearbyLog("socket", `out ${frameType(text)}`);
    this.movedAt = this.clock.now();
    this.probe(link);
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
