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
  /** A seat's resume: its hello is out and the socket opens once the host
   *  has answered it (bound the seat and sent its state). */
  private resuming = false;
  /** The host's frames that came while resuming, handed on after the open. */
  private early: string[] = [];

  /** `greet`: a seated joiner's resume, called once the link is up. When it
   *  gives a table_join, this socket sends it as the hello and reports open
   *  only once the host's answer (a room, state or error frame) is in, so
   *  the page shows the table as connected and sends a move only after the
   *  seat is bound to this link and its fresh state applied. */
  constructor(transport: NearbyTransport, code: string, onState: ((state: LinkState, detail?: string) => void) | null = null,
              clock: Clock = realClock, greet: (() => Record<string, unknown> | null) | null = null) {
    this.onState = onState;
    this.clock = clock;
    const started = clock.now();
    // a seated joiner's new link: its hello will be the resume
    const resume = greet !== null && greet() !== null;
    if (resume) {
      // a resume that has not reached the host by now is stuck (a stale
      // path after the network came back): this attempt ends, and the page
      // makes a fresh one
      clock.setTimeout(() => {
        if (this.readyState === NearbySocket.CONNECTING && this.link === null) {
          nearbyLog("socket", `resume: no link after ${LIMITS.linkSeconds} s; a fresh attempt`);
          this.finish();
        }
      }, LIMITS.linkSeconds);
    }
    transport
      .join(code, {
        message: (text) => {
          if (this.resuming) {
            this.heard = this.clock.now();
            if (text === PONG_TEXT) return;
            this.early.push(text);
            const type = frameType(text);
            nearbyLog("socket", `resume: in ${type}`);
            if (type === "state" || type === "room" || type === "error") this.resumed(type);
            return;
          }
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
        resume,
      })
      .then(
        (link) => {
          if (this.readyState !== NearbySocket.CONNECTING) {
            link.close();
            return;
          }
          this.link = link;
          this.heard = this.clock.now();
          const hello = greet?.() ?? null;
          const text = hello === null ? null : NearbySocket.outbound(JSON.stringify(hello));
          if (text === null) {
            this.readyState = NearbySocket.OPEN;
            nearbyLog("socket", "open");
            this.ping(link);
            this.onopen?.({} as Event);
            return;
          }
          this.resuming = true;
          nearbyLog("socket", `resume: link up in ${Math.round((this.clock.now() - started) * 1000)} ms; hello sent (${hello!.token ? "with" : "no"} token)`);
          try {
            link.send(text);
          } catch {
            this.close();
            return;
          }
          this.clock.setTimeout(() => {
            if (this.link === link && this.resuming) {
              nearbyLog("socket", `resume: no answer in ${LIMITS.resumeSeconds} s; a fresh attempt`);
              this.close();
            }
          }, LIMITS.resumeSeconds);
        },
        () => this.finish(),
      );
  }

  /** The host answered the resume: the socket is open, and the frames that
   *  came with the answer go to the page after its open, in order. */
  private resumed(type: string): void {
    const link = this.link!;
    this.resuming = false;
    this.readyState = NearbySocket.OPEN;
    nearbyLog("socket", `resume: accepted (${type}); open`);
    this.ping(link);
    this.onopen?.({} as Event);
    const early = this.early;
    this.early = [];
    for (const text of early) {
      if (this.readyState !== NearbySocket.OPEN) return;
      this.onmessage?.({ data: text } as MessageEvent);
    }
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
    this.resuming = false;
    this.early = [];
    this.link = null;
    this.onclose?.({} as CloseEvent);
  }
}
