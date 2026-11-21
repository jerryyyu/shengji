// The host phone's side of a nearby table: one LocalConnection on the room's
// server per linked joiner, exactly as LocalSocket is one for the host's own
// page, so a joiner gets the frames a seat's writer emits and nothing else.
// Every byte from a joiner passes this boundary first: size, rate, the hello
// and its version, and the joiner allow-list (protocol.ts). Anything that
// fails is dropped or ends that link; nothing here throws into the room.
import type { Clock } from "../clock";
import { nearbyPeekJson, type LocalConnection, type LocalRoom, type LocalServer } from "../server";
import { NEARBY_COPY } from "./copy";
import { frameType, nearbyLog } from "../../../nearbyLog";
import { KEEPALIVE, KEEPALIVE_TEXT, LIMITS, NEARBY_V, PING, PING_TEXT, PONG_TEXT, cleanHello, cleanJoinerMessage, parseObject, utf8Bytes } from "./protocol";
import { NearbyError, type HostLink, type LinkState, type NearbyTransport } from "./transport";

/** A link that has looked at the seats has this long, from its first look,
 *  to take one; looking again does not extend it. */
export const PEEK_SECONDS = 120;
/** A link the host ends after a last frame (a `left`, a refusal, a peek
 *  after the start) stays open this long first, so the frame goes out
 *  ahead of the close. */
export const DRAIN_SECONDS = 1;
/** After the host's Leave, its links stop once the room has told every
 *  joiner, or after this long at the most. */
export const STOP_FALLBACK_SECONDS = 3;

interface Peer {
  conn: LocalConnection | null;
  /** The transport's opaque id for the link's remote address, or null. An
   *  address is not a phone's identity (addresses are reused), so it only
   *  labels the link in the log: a seat is resumed by its token alone. */
  device: string | null;
  /** The seat token the room gave this link, from its resume frame. */
  token: string | null;
  /** Bumped at each hello deadline, so only the latest one fires. */
  deadline: number;
  /** The link has had its one look at the seats. */
  peeked: boolean;
  /** Clock times of this second's messages, for the rate limit. */
  recent: number[];
  /** The same for its pings and keepalives, on their own budget. */
  upkeep: number[];
  /** Clock time of the link's latest frame, for the liveness check. */
  heard: number;
  /** The host is ending the link after its last frame: nothing more is read. */
  ending: boolean;
  closed: boolean;
  /** The latest state frame sent on this link, until another kind of frame
   *  (chat aside) goes out after it. */
  lastState: string | null;
}

export interface NearbyHostEvents {
  state?(state: LinkState, detail?: string): void;
}

export class NearbyHost {
  private peers = new Map<string, Peer>();
  private link: HostLink | null = null;
  private stopped = false;
  private server: LocalServer;
  private room: LocalRoom;
  private clock: Clock;
  private events: NearbyHostEvents;
  /** Counts of what the boundary refused, by reason, for tests and the M1 page. */
  readonly refused: Record<string, number> = {};

  constructor(server: LocalServer, room: LocalRoom, events: NearbyHostEvents = {}) {
    this.server = server;
    this.room = room;
    this.clock = server.clock;
    this.events = events;
  }

  /** Advertise the room's table on `transport`. */
  async start(transport: NearbyTransport): Promise<void> {
    const link = await transport.host(this.room.code, {
      peer: (peer, connected, device) => (connected ? this.onPeer(peer, device ?? null) : this.onGone(peer)),
      message: (peer, text) => this.onMessage(peer, text),
      state: (state, detail) => {
        // the host was away past the joiners' window: the table is over
        if (state === "ended") this.server.endNearbyRoomForAll(this.room);
        this.events.state?.(state, detail);
      },
    });
    if (this.stopped) {
      // stopped while the listener was on its way: it must not stay up
      link.stop();
      throw new NearbyError("failed", "stopped");
    }
    this.link = link;
  }

  stop(): void {
    this.stopped = true;
    for (const id of [...this.peers.keys()]) this.end(id);
    this.link?.stop();
    this.link = null;
  }

  /** The host's Leave: the room tells every joiner the table is over, and
   *  the links stop once it has (or after STOP_FALLBACK_SECONDS). */
  stopWhenClosed(): void {
    if (this.stopped) return;
    // still starting: no joiner can be linked yet
    if (this.link === null) {
      this.stop();
      return;
    }
    const stopSoon = () => this.clock.setTimeout(() => this.stop(), DRAIN_SECONDS);
    if (this.room.closed) {
      stopSoon();
      return;
    }
    this.room.onClosed = stopSoon;
    this.clock.setTimeout(() => this.stop(), STOP_FALLBACK_SECONDS);
  }

  private refuse(reason: string, id = "", text = ""): void {
    this.refused[reason] = (this.refused[reason] ?? 0) + 1;
    nearbyLog("host", `REFUSED ${reason}${id ? ` from ${id}` : ""}${text ? ` (${frameType(text)})` : ""}`);
  }

  private onPeer(id: string, device: string | null): void {
    nearbyLog("host", `link ${id} up${device ? ` from ${device}` : ""}`);
    if (this.peers.size >= LIMITS.peers || this.room.closed || this.stopped) {
      this.refuse("peers");
      this.link?.close(id);
      return;
    }
    if ([...this.peers.values()].filter((p) => p.conn === null).length >= LIMITS.unseated) {
      // links only looking at the seats never crowd out a seat's resume: the
      // oldest of them makes room (it may look again)
      const looker = [...this.peers].find(([, p]) => p.conn === null && p.peeked);
      if (looker) {
        this.refuse("looker_replaced", looker[0]);
        this.end(looker[0]);
      }
    }
    if ([...this.peers.values()].filter((p) => p.conn === null).length >= LIMITS.unseated) {
      this.refuse("unseated");
      this.link?.close(id);
      return;
    }
    const peer: Peer = { conn: null, device, token: null, deadline: 0, peeked: false, recent: [], upkeep: [],
                         heard: this.clock.now(), ending: false, closed: false, lastState: null };
    this.peers.set(id, peer);
    this.helloBy(id, peer, LIMITS.helloSeconds);
    this.listen(id, peer);
  }

  /** The link must be seated within `seconds`, or it ends. */
  private helloBy(id: string, peer: Peer, seconds: number): void {
    const mine = ++peer.deadline;
    this.clock.setTimeout(() => {
      if (this.peers.get(id) === peer && peer.conn === null && peer.deadline === mine) {
        this.refuse("hello_timeout", id);
        this.end(id);
      }
    }, seconds);
  }

  /** A link that sends nothing for LIMITS.silentSeconds is gone (the phone
   *  walked away): its seat waits for a resume, as after any drop. The
   *  joiner's socket pings well inside it. */
  private listen(id: string, peer: Peer): void {
    const wait = Math.max(0, peer.heard + LIMITS.silentSeconds - this.clock.now());
    this.clock.setTimeout(() => {
      if (this.peers.get(id) !== peer || peer.closed) return;
      // within a microsecond counts as due: a clock's float time can land a
      // hair short, and a wait that small would never move it forward
      if (this.clock.now() - peer.heard >= LIMITS.silentSeconds - 1e-6) {
        this.refuse("silent", id);
        this.end(id);
      } else this.listen(id, peer);
    }, wait);
  }

  private onGone(id: string): void {
    const peer = this.peers.get(id);
    if (!peer) return;
    nearbyLog("host", `link ${id} gone${peer.conn ? " (seated)" : ""}`);
    this.peers.delete(id);
    peer.closed = true;
    peer.conn?.close();
  }

  /** End one link: its seat waits for a resume, as after a dropped socket. */
  private end(id: string): void {
    this.onGone(id);
    this.link?.close(id);
  }

  /** End one link after its last frame has had time to go out. */
  private endSoon(id: string, peer: Peer): void {
    if (peer.ending) return;
    peer.ending = true;
    this.clock.setTimeout(() => { if (this.peers.get(id) === peer) this.end(id); }, DRAIN_SECONDS);
  }

  private onMessage(id: string, text: string): void {
    const peer = this.peers.get(id);
    if (!peer || peer.closed || peer.ending) {
      nearbyLog("host", `IGNORED ${typeof text === "string" ? frameType(text) : "?"} from ${id}: ${!peer ? "no such link" : peer.closed ? "closed" : "ending"}`);
      return;
    }
    try {
      this.receive(id, peer, text);
    } catch (e) {
      // a defect in a handler must not take the host down with it
      this.refuse("exception", id, text);
      nearbyLog("host", `exception: ${String(e)}`);
      this.end(id);
    }
  }

  private receive(id: string, peer: Peer, text: string): void {
    if (typeof text !== "string" || utf8Bytes(text) > LIMITS.frameBytes) {
      this.refuse("size", id);
      this.end(id);
      return;
    }
    const now = this.clock.now();
    peer.heard = now;
    if (text === KEEPALIVE_TEXT || text === PING_TEXT) {
      // a link's own upkeep, answered here and never seen by the room. It
      // has its own, wider budget: a peer-to-peer link that paused hands
      // over its held keepalives in one burst, which is not a flood of moves
      peer.upkeep = peer.upkeep.filter((t) => now - t < 1);
      peer.upkeep.push(now);
      if (peer.upkeep.length > LIMITS.upkeepPerSecond) {
        this.refuse("rate", id, text);
        this.end(id);
        return;
      }
      this.link?.send(id, text === PING_TEXT ? PONG_TEXT : KEEPALIVE_TEXT);
      return;
    }
    peer.recent = peer.recent.filter((t) => now - t < 1);
    peer.recent.push(now);
    if (peer.recent.length > LIMITS.perSecond) {
      this.refuse("rate", id, text);
      this.end(id);
      return;
    }
    const msg = parseObject(text);
    if (msg === null) {
      this.refuse("json", id);
      this.end(id);
      return;
    }
    if (msg.type === KEEPALIVE || msg.type === PING) {
      // upkeep in another spelling: not a game message, so dropped
      this.refuse("message", id, text);
      return;
    }
    nearbyLog("host", `in ${frameType(text)} from ${id}${peer.conn === null ? " (unseated)" : ""}`);
    if (peer.conn === null) {
      this.hello(id, peer, msg);
      return;
    }
    const clean = cleanJoinerMessage(msg);
    if (clean === null) {
      // an unknown or malformed message is ignored, as the device ignores
      // the game server's own messages
      this.refuse("message", id, text);
      return;
    }
    peer.conn.receive(JSON.stringify(clean));
  }

  private hello(id: string, peer: Peer, msg: Record<string, unknown>): void {
    const hello = cleanHello(msg);
    if (hello === null) {
      this.refuse("hello", id, JSON.stringify(msg));
      this.end(id);
      return;
    }
    if (hello.nearby_v !== NEARBY_V) {
      this.refuse("version");
      this.link?.send(id, JSON.stringify({ type: "error", code: "nearby_version", message: NEARBY_COPY.versionMismatch }));
      this.endSoon(id, peer);
      return;
    }
    if (hello.peek) {
      // the seat picker: the seats, and the link stays unseated until its
      // pick, for one PEEK_SECONDS from its first look
      const seats = nearbyPeekJson(this.room, this.clock.now());
      this.link?.send(id, JSON.stringify(seats));
      if (seats.full) {
        // no seat for a newcomer: the look ends here
        this.endSoon(id, peer);
        return;
      }
      if (!peer.peeked) {
        peer.peeked = true;
        this.helloBy(id, peer, PEEK_SECONDS);
      }
      return;
    }
    // a hello without a seat's token is a newcomer, whatever address it
    // comes from: the room seats it as one, never in a person's held seat
    const token = hello.token;
    if (token) {
      // a joiner back with its token: any older link of its seat is closed,
      // so frames never reach that phone twice
      for (const [other, p] of this.peers) if (other !== id && p.token === token) this.end(other);
    }
    peer.conn = this.server.connect((frame) => this.deliver(id, peer, frame));
    // the join is handled in this call: the seat is bound to this link (its
    // older link ended above) before any later frame of the link is read,
    // and the resume and state frames go out after that
    peer.conn.receive(JSON.stringify({ type: "table_join", code: this.room.code, name: hello.name, token,
                                       seat: hello.seat ?? null }));
    const room = peer.conn.currentRoom;
    nearbyLog("host", `${token ? "resume" : "join"} from ${id}: ${room ? `seat ${room.seatIndex(peer.conn.seat!)} bound` : "refused"}`);
  }

  /** A frame from the room to one joiner. A `left`, or a refusal that
   *  leaves the connection with no seat, ends the link after it is sent. A
   *  state the same, byte for byte, as the last one this link was sent is
   *  not sent again: the room can broadcast twice for one action. */
  private deliver(id: string, peer: Peer, frame: string): void {
    if (peer.closed || this.peers.get(id) !== peer) return;
    const state = frame.startsWith('{"type":"state"');
    if (state && frame === peer.lastState) return;
    if (state) peer.lastState = frame;
    else if (!frame.startsWith('{"type":"chat"')) peer.lastState = null;
    try {
      this.link?.send(id, frame);
      nearbyLog("host", `out ${frameType(frame)} to ${id}`);
    } catch {
      this.refuse("send");
      this.end(id);
      return;
    }
    if (frame.startsWith('{"type":"resume"')) {
      peer.token = (parseObject(frame)?.token as string | undefined) ?? null;
    }
    if (frame.startsWith('{"type":"left"')) this.endSoon(id, peer);
    else if (frame.startsWith('{"type":"error"')) {
      const code = parseObject(frame)?.code;
      if (code === "room_full" || code === "room_not_found" || code === "stale_connection") this.endSoon(id, peer);
    }
  }
}
