// The joiner's socket: a WebSocket look-alike over the nearby link, handed to
// ws.ts's Connection in place of the game server's socket, so the client
// protocol and the table UI run unchanged. It opens no URL, so the device key
// in socketUrl() never crosses; it sends only the hello and the joiner
// allow-list (protocol.ts), so presence, the queue, heartbeats, telemetry and
// chat stay on the phone.
import { type Clock, realClock } from "../clock";
import { frameType, nearbyLog } from "../../../nearbyLog";
import { KEEPALIVE_TEXT, LIMITS, NEARBY_V, PING_TEXT, PONG_TEXT, cleanJoinerMessage, parseObject, utf8Bytes, type NearbyHello } from "./protocol";
import type { JoinLink, LinkState, NearbyTransport } from "./transport";

type Handler<E> = ((ev: E) => void) | null;

/** The peer-to-peer keepalive, on unless a device-test build turns it off
 *  to compare. */
let keepaliveOn = true;
const keepaliveListeners = new Set<() => void>();

export function nearbyKeepalive(): boolean {
  return keepaliveOn;
}

export function setNearbyKeepalive(on: boolean): void {
  if (keepaliveOn === on) return;
  keepaliveOn = on;
  nearbyLog("socket", `keepalive ${on ? "on" : "off"}`);
  for (const fn of [...keepaliveListeners]) fn();
}

export function subscribeNearbyKeepalive(fn: () => void): () => void {
  keepaliveListeners.add(fn);
  return () => { keepaliveListeners.delete(fn); };
}

/** When each clock's sockets last gave up on a stuck link, so a run of
 *  them never makes new links faster than LIMITS.stuckSpacingSeconds. */
const lastStuck = new WeakMap<Clock, number>();

/** The link state's detail when the host refused a seat's resume: the
 *  table no longer knows its token. */
export const SEAT_GONE = "seat_gone";

/** A resume's link that has answered nothing by LIMITS.resumeSeconds gets
 *  this much longer for the host's answer before a fresh attempt. */
const RESUME_GRACE_SECONDS = 2;

/** The moves the host may not have had, kept across a seat's links so the
 *  link that replaces a stuck one sends the last of them again, once. */
type MoveKind = "play" | "bury" | "declare" | "pass_declare" | "next_round" | "table_start";
const MOVE_KINDS: ReadonlySet<string> = new Set<MoveKind>(["play", "bury", "declare", "pass_declare", "next_round", "table_start"]);

/** A move the host has not answered. */
interface Unanswered {
  text: string;
  kind: MoveKind;
  /** The cards of a play, bury or declare; empty otherwise. */
  ids: number[];
  /** A table_start's `on`: false takes the Start back. */
  on: boolean;
  /** Already sent again on a later link: never a third time. */
  resent: boolean;
}

/** Each clock's unanswered moves, by seat token, the latest of each kind
 *  in the order sent: a stale move the page sends after a real one (a pass
 *  after its bury) never takes the real one's place. */
const unansweredMoves = new WeakMap<Clock, Map<string, Map<MoveKind, Unanswered>>>();

function movesOf(clock: Clock, token: string): Map<MoveKind, Unanswered> {
  let m = unansweredMoves.get(clock);
  if (!m) unansweredMoves.set(clock, m = new Map());
  let mine = m.get(token);
  if (!mine) m.set(token, mine = new Map());
  return mine;
}

const sameIds = (a: readonly unknown[], b: readonly number[]) =>
  a.length === b.length && [...a].sort().join(",") === [...b].sort().join(",");

/** Whether a table frame shows the host has not applied `move`, so sending
 *  it again applies it once: the frame still asks this seat for that move
 *  (a play or bury with its cards in hand, a declare still on offer, a pass
 *  or Next not yet counted) or, in the lobby, still shows its Start as it
 *  was. Anything else (another phase, a declaration that beat it, a new
 *  round) means it was applied or is stale, and it is never sent again. */
function stillOwed(frame: Record<string, unknown> | null, move: Unanswered): boolean {
  if (frame === null) return false;
  const you = frame.you;
  if (move.kind === "table_start") {
    const lobby = frame.type === "room" ? frame.nearby as { ready?: unknown } | undefined : undefined;
    if (!lobby || !Array.isArray(lobby.ready)) return false;
    return lobby.ready.includes(you) !== move.on;
  }
  if (frame.type !== "state" || frame.joining_you) return false;
  switch (move.kind) {
    case "declare": {
      if (frame.phase !== "deal" && frame.phase !== "declare") return false;
      const options = Array.isArray(frame.declare_options) ? frame.declare_options as unknown[] : [];
      return options.some((o) => Array.isArray(o) && sameIds(o, move.ids));
    }
    case "pass_declare":
      return frame.phase === "declare" && Array.isArray(frame.passed) && !frame.passed.includes(you);
    case "next_round":
      return frame.phase === "round_end" && Array.isArray(frame.ready) && !frame.ready.includes(you);
    default: {
      if (frame.turn !== you || frame.phase !== move.kind) return false;
      const hand = Array.isArray(frame.hand) ? frame.hand as { id?: unknown }[] : [];
      const ids = new Set(hand.map((c) => c?.id));
      return move.ids.every((id) => ids.has(id));
    }
  }
}

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
  /** Ping round trips and move-to-answer times, in ms, since the last summary. */
  private rtts: number[] = [];
  private moves: number[] = [];
  /** A game is on at this link (the latest table frame was a state). */
  private inGame = false;
  /** The keepalive loop is running. */
  private keeping = false;
  private offKeepalive: () => void = () => {};
  /** The seat's token (the hello's, or the host's resume frame), which
   *  keys its unanswered move across links. */
  private token: string | null = null;
  /** The moves this link sent again after its resume: the same text from
   *  the page (Table's own once-more, an autoplay) is not sent a second time. */
  private resentTexts = new Set<string>();

  /** `greet`: a seated joiner's resume, called once the link is up. When it
   *  gives a table_join, this socket sends it as the hello and reports open
   *  only once the host's answer (a room, state or error frame) is in, so
   *  the page shows the table as connected and sends a move only after the
   *  seat is bound to this link and its fresh state applied. */
  constructor(transport: NearbyTransport, code: string, onState: ((state: LinkState, detail?: string) => void) | null = null,
              clock: Clock = realClock, greet: (() => Record<string, unknown> | null) | null = null) {
    this.onState = onState;
    this.clock = clock;
    this.offKeepalive = subscribeNearbyKeepalive(() => this.resumeKeepalive());
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
            if (text === PONG_TEXT) this.pingSent = null;
            if (text === PONG_TEXT || text === KEEPALIVE_TEXT) return;
            this.early.push(text);
            const type = frameType(text);
            nearbyLog("socket", `resume: in ${type}`);
            if (type === "state" || type === "room" || type === "error") this.resumed(type);
            return;
          }
          if (this.readyState !== NearbySocket.OPEN) return;
          const now = this.clock.now();
          this.heard = now;
          if (text === KEEPALIVE_TEXT) return;
          if (text !== PONG_TEXT) this.noteAnswer(text);
          if (text === PONG_TEXT) {
            if (this.pingSent !== null) {
              const ms = Math.round((now - this.pingSent) * 1000);
              this.rtts.push(ms);
              nearbyLog("socket", `pong in ${ms} ms`);
            }
            this.pingSent = null;
            return;
          }
          const type = frameType(text);
          if (this.movedAt !== null && (type === "state" || type === "error" || type === "room")) {
            const ms = Math.round((now - this.movedAt) * 1000);
            this.moves.push(ms);
            nearbyLog("socket", `in ${type}, ${ms} ms after the move`);
            this.movedAt = null;
          } else nearbyLog("socket", `in ${type}`);
          this.noteTable(type);
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
          if (hello !== null && typeof hello.token === "string" && hello.token) this.token = hello.token;
          const text = hello === null ? null : NearbySocket.outbound(JSON.stringify(hello));
          if (text === null) {
            this.readyState = NearbySocket.OPEN;
            nearbyLog("socket", "open");
            this.ping(link);
            this.summarize(link);
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
          // the ping behind the hello says whether the link carries
          if (!this.sendPing(link)) return;
          this.awaitResume(link, this.clock.now());
        },
        () => this.finish(),
      );
  }

  /** The hello is out on a link that is up, with a ping behind it. By
   *  LIMITS.resumeSeconds a link that has answered that ping carries (the
   *  hello is on TCP and still on its way): it is kept, pinged every
   *  LIMITS.pingSeconds, until the answer, a missed pong, or
   *  LIMITS.silentSeconds. One that has answered nothing gets
   *  RESUME_GRACE_SECONDS more, then the attempt ends for a fresh one. */
  private awaitResume(link: JoinLink, since: number): void {
    const live = () => this.link === link && this.resuming;
    const carry = () => {
      if (!live()) return;
      if (this.clock.now() - since >= LIMITS.silentSeconds - 1e-6) {
        nearbyLog("socket", `resume: no answer in ${LIMITS.silentSeconds} s; a fresh attempt`);
        this.close();
        return;
      }
      if (this.pingSent !== null) {
        nearbyLog("socket", "resume: no answer and no pong; a fresh attempt");
        this.close();
        return;
      }
      if (!this.sendPing(link)) return;
      this.clock.setTimeout(carry, LIMITS.pingSeconds);
    };
    this.clock.setTimeout(() => {
      if (!live()) return;
      if (this.pingSent === null) {
        nearbyLog("socket", `resume: no answer in ${LIMITS.resumeSeconds} s, but the link carries; kept`);
        carry();
        return;
      }
      this.clock.setTimeout(() => {
        if (!live()) return;
        if (this.pingSent === null) {
          carry();
          return;
        }
        nearbyLog("socket", `resume: no answer and no pong in ${LIMITS.resumeSeconds + RESUME_GRACE_SECONDS} s; a fresh attempt`);
        this.close();
      }, RESUME_GRACE_SECONDS);
    }, LIMITS.resumeSeconds);
  }

  /** The host answered the resume: the socket is open, and the frames that
   *  came with the answer go to the page after its open, in order. */
  private resumed(type: string): void {
    const link = this.link!;
    const refusal = type === "error" ? parseObject(this.early[this.early.length - 1])?.code : null;
    if (refusal === "room_not_found" || refusal === "room_full") {
      // the table no longer knows this seat's token: no new link can take
      // it back, so the page is told and goes to the seat picker, rather
      // than trying the same token until the host's window runs out
      nearbyLog("socket", `resume: refused (${refusal}); the seat is gone`);
      this.onState?.("failed", SEAT_GONE);
      this.close();
      return;
    }
    this.resuming = false;
    this.readyState = NearbySocket.OPEN;
    nearbyLog("socket", `resume: accepted (${type}); open`);
    const early = this.early;
    this.early = [];
    for (const text of early) if (frameType(text) === "resume") this.noteAnswer(text);
    this.sendAgain(link, type === "state" || type === "room" ? parseObject(early[early.length - 1]) : null);
    this.ping(link);
    this.summarize(link);
    this.onopen?.({} as Event);
    for (const text of early) {
      if (this.readyState !== NearbySocket.OPEN) return;
      this.noteTable(frameType(text));
      this.onmessage?.({ data: text } as MessageEvent);
    }
  }

  /** A frame from the host: the seat's token from a resume frame; an
   *  unanswered move is settled by an error, or a state or room frame that
   *  no longer shows it owed. */
  private noteAnswer(text: string): void {
    const type = frameType(text);
    if (type === "resume") {
      const tok = parseObject(text)?.token;
      if (typeof tok === "string" && tok) this.token = tok;
      return;
    }
    if (this.token === null || (type !== "state" && type !== "error" && type !== "room")) return;
    const frame = type === "error" ? null : parseObject(text);
    const moves = movesOf(this.clock, this.token);
    const owed = new Set<string>();
    for (const [kind, move] of moves) {
      if (stillOwed(frame, move)) owed.add(move.text);
      else moves.delete(kind);
    }
    // a move sent again is settled: the same text later is a new move
    // (card ids repeat from round to round)
    for (const t of this.resentTexts) if (!owed.has(t)) this.resentTexts.delete(t);
  }

  /** Just resumed: a move the last link sent and the host never answered
   *  goes once more, before the page hears anything, when the resumed
   *  state or lobby frame shows it was not applied (stillOwed). */
  private sendAgain(link: JoinLink, frame: Record<string, unknown> | null): void {
    if (this.token === null) return;
    const moves = movesOf(this.clock, this.token);
    let sent = false;
    for (const [kind, move] of [...moves]) {
      if (move.resent || !stillOwed(frame, move)) {
        moves.delete(kind);
        continue;
      }
      try {
        link.send(move.text);
      } catch {
        return;
      }
      move.resent = true;
      this.resentTexts.add(move.text);
      this.movedAt = this.clock.now();
      sent = true;
      nearbyLog("socket", `resume: the unanswered ${move.kind} sent again`);
    }
    if (sent) this.probe(link);
  }

  /** Ping the host every LIMITS.pingSeconds, so it knows this phone is
   *  still there; a host silent for LIMITS.silentSeconds is gone, and a
   *  ping unanswered for LIMITS.pongSeconds means this phone's frames are
   *  not reaching it: either way the socket closes, as a dropped link
   *  would, and the page makes a new link and takes its seat back. */
  private ping(link: JoinLink): void {
    this.clock.setTimeout(() => {
      if (this.link !== link || this.readyState !== NearbySocket.OPEN) return;
      // a stuck link that is given more time, and answers, stays watched:
      // the loop goes on until the link is replaced
      if (this.clock.now() - this.heard >= LIMITS.silentSeconds) this.stuck("the host is silent", link);
      else if (this.pingSent !== null && this.clock.now() - this.pingSent >= this.pongWindow(link)) this.stuck("no pong", link);
      else if (this.pingSent === null && !this.sendPing(link)) return;
      if (this.link === link && this.readyState === NearbySocket.OPEN) this.ping(link);
    }, LIMITS.pingSeconds);
  }

  /** A state frame means a game is on, a room frame the lobby: the
   *  keepalive runs only during a game on a peer-to-peer link. */
  private noteTable(type: string): void {
    if (type === "state") this.inGame = true;
    else if (type === "room") this.inGame = false;
    else return;
    if (this.link) this.keepAwake(this.link);
  }

  /** While a game is on over peer-to-peer Wi-Fi (and the page is in view):
   *  a tiny frame every LIMITS.keepaliveSeconds, which the host answers, so
   *  the AWDL radio does not doze between moves and hold the next one. */
  private keepAwake(link: JoinLink): void {
    if (this.keeping || !link.peerToPeer || !this.inGame || !keepaliveOn) return;
    this.keeping = true;
    nearbyLog("socket", "keepalive running (peer-to-peer, in a game)");
    const tick = () => {
      const hidden = typeof document !== "undefined" && document.visibilityState === "hidden";
      if (this.link !== link || this.readyState !== NearbySocket.OPEN || !this.inGame || !keepaliveOn) {
        this.keeping = false;
        nearbyLog("socket", "keepalive stopped");
        return;
      }
      if (!hidden) {
        try {
          link.send(KEEPALIVE_TEXT);
        } catch {
          this.keeping = false;
          this.close();
          return;
        }
      }
      this.clock.setTimeout(tick, LIMITS.keepaliveSeconds);
    };
    this.clock.setTimeout(tick, LIMITS.keepaliveSeconds);
  }

  /** Turned back on: the open link's keepalive starts again. */
  private resumeKeepalive(): void {
    if (this.link) this.keepAwake(this.link);
  }

  /** Every LIMITS.summarySeconds while the link is open: the spread of its
   *  ping round trips and move answers, so a device log shows the spikes. */
  private summarize(link: JoinLink): void {
    this.clock.setTimeout(() => {
      if (this.link !== link || this.readyState !== NearbySocket.OPEN) return;
      nearbyLog("socket", `last ${LIMITS.summarySeconds} s: ping ${spread(this.rtts)}; move ${spread(this.moves)}`);
      this.rtts = [];
      this.moves = [];
      this.summarize(link);
    }, LIMITS.summarySeconds);
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
    if (this.pingSent === null) {
      if (!this.sendPing(link)) return;
      nearbyLog("socket", "probe sent");
    }
    const sent = this.pingSent;
    const window = this.pongWindow(link) - (sent === null ? 0 : this.clock.now() - sent);
    this.clock.setTimeout(() => {
      if (this.link === link && this.readyState === NearbySocket.OPEN && this.pingSent === sent && sent !== null) {
        this.stuck("no pong after a move", link);
      }
    }, Math.max(0, window));
  }

  /** How long a ping may go unanswered: longer over peer-to-peer Wi-Fi. */
  private pongWindow(link: JoinLink): number {
    return link.peerToPeer ? LIMITS.pongSecondsPeerToPeer : LIMITS.pongSeconds;
  }

  /** The link is stuck: a new one is made, but never sooner than
   *  LIMITS.stuckSpacingSeconds after the last; meanwhile an answer that
   *  arrives (a pong, any frame) keeps this link. */
  private stuck(why: string, link: JoinLink): void {
    const now = this.clock.now();
    const wait = (lastStuck.get(this.clock) ?? -Infinity) + LIMITS.stuckSpacingSeconds - now;
    if (wait > 0) {
      nearbyLog("socket", `slow: ${why}; giving it ${wait.toFixed(1)} s more`);
      const heard = this.heard;
      const ping = this.pingSent;
      this.clock.setTimeout(() => {
        if (this.link !== link || this.readyState !== NearbySocket.OPEN) return;
        // the ping answered (or, with none out, anything heard): alive
        if (ping !== null ? this.pingSent !== ping : this.heard !== heard) return;
        this.stuck(why, link);
      }, wait);
      return;
    }
    lastStuck.set(this.clock, now);
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
    if (this.resentTexts.has(text)) {
      nearbyLog("socket", `out ${frameType(text)}: already sent again on this link`);
      return;
    }
    this.noteMove(text);
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

  /** A move going out is the seat's unanswered move until the host
   *  answers it. */
  private noteMove(text: string): void {
    if (this.token === null) return;
    const msg = parseObject(text);
    if (msg === null || typeof msg.type !== "string" || !MOVE_KINDS.has(msg.type)) return;
    const kind = msg.type as MoveKind;
    const moves = movesOf(this.clock, this.token);
    // re-inserted, so the kinds stay in the order sent
    moves.delete(kind);
    moves.set(kind, {
      text, kind, ids: Array.isArray(msg.card_ids) ? msg.card_ids as number[] : [],
      on: msg.on !== false, resent: false,
    });
  }

  close(): void {
    if (this.readyState >= NearbySocket.CLOSING) return;
    this.link?.close();
    this.finish();
  }

  private finish(): void {
    if (this.readyState === NearbySocket.CLOSED) return;
    this.readyState = NearbySocket.CLOSED;
    this.offKeepalive();
    this.resuming = false;
    this.early = [];
    this.link = null;
    this.onclose?.({} as CloseEvent);
  }
}

/** "n=12 p50 40 p95 380 max 512 ms", or "none". */
export function spread(ms: readonly number[]): string {
  if (!ms.length) return "none";
  const sorted = [...ms].sort((a, b) => a - b);
  const at = (q: number) => sorted[Math.min(sorted.length - 1, Math.floor(q * sorted.length))];
  return `n=${sorted.length} p50 ${at(0.5)} p95 ${at(0.95)} max ${sorted[sorted.length - 1]} ms`;
}
