// The host phone's side of a nearby table: one LocalConnection on the room's
// server per linked joiner, exactly as LocalSocket is one for the host's own
// page, so a joiner gets the frames a seat's writer emits and nothing else.
// Every byte from a joiner passes this boundary first: size, rate, the hello
// and its version, and the joiner allow-list (protocol.ts). Anything that
// fails is dropped or ends that link; nothing here throws into the room.
import type { Clock } from "../clock";
import { nearbyPeekJson, type LocalConnection, type LocalRoom, type LocalServer } from "../server";
import { NEARBY_COPY } from "./copy";
import { LIMITS, NEARBY_V, cleanHello, cleanJoinerMessage, parseObject, utf8Bytes } from "./protocol";
import type { HostLink, LinkState, NearbyTransport } from "./transport";

/** A link that has looked at the seats has this long to take one. */
export const PEEK_SECONDS = 120;

interface Peer {
  conn: LocalConnection | null;
  /** The seat token the room gave this link, from its resume frame. */
  token: string | null;
  /** Bumped at each hello deadline, so only the latest one fires. */
  deadline: number;
  /** Clock times of this second's messages, for the rate limit. */
  recent: number[];
  closed: boolean;
}

export interface NearbyHostEvents {
  state?(state: LinkState, detail?: string): void;
}

export class NearbyHost {
  private peers = new Map<string, Peer>();
  private link: HostLink | null = null;
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
    this.link = await transport.host(this.room.code, {
      peer: (peer, connected) => (connected ? this.onPeer(peer) : this.onGone(peer)),
      message: (peer, text) => this.onMessage(peer, text),
      state: (state, detail) => {
        // the host was away past the joiners' window: the table is over
        if (state === "ended") this.server.endNearbyRoomForAll(this.room);
        this.events.state?.(state, detail);
      },
    });
  }

  stop(): void {
    for (const id of [...this.peers.keys()]) this.end(id);
    this.link?.stop();
    this.link = null;
  }

  private refuse(reason: string): void {
    this.refused[reason] = (this.refused[reason] ?? 0) + 1;
  }

  private onPeer(id: string): void {
    if (this.peers.size >= LIMITS.peers || this.room.closed) {
      this.refuse("peers");
      this.link?.close(id);
      return;
    }
    const peer: Peer = { conn: null, token: null, deadline: 0, recent: [], closed: false };
    this.peers.set(id, peer);
    this.helloBy(id, peer, LIMITS.helloSeconds);
  }

  /** The link must be seated within `seconds`, or it ends. */
  private helloBy(id: string, peer: Peer, seconds: number): void {
    const mine = ++peer.deadline;
    this.clock.setTimeout(() => {
      if (this.peers.get(id) === peer && peer.conn === null && peer.deadline === mine) {
        this.refuse("hello_timeout");
        this.end(id);
      }
    }, seconds);
  }

  private onGone(id: string): void {
    const peer = this.peers.get(id);
    if (!peer) return;
    this.peers.delete(id);
    peer.closed = true;
    peer.conn?.close();
  }

  /** End one link: its seat waits for a resume, as after a dropped socket. */
  private end(id: string): void {
    this.onGone(id);
    this.link?.close(id);
  }

  private onMessage(id: string, text: string): void {
    const peer = this.peers.get(id);
    if (!peer || peer.closed) return;
    try {
      this.receive(id, peer, text);
    } catch {
      // a defect in a handler must not take the host down with it
      this.refuse("exception");
      this.end(id);
    }
  }

  private receive(id: string, peer: Peer, text: string): void {
    if (typeof text !== "string" || utf8Bytes(text) > LIMITS.frameBytes) {
      this.refuse("size");
      this.end(id);
      return;
    }
    const now = this.clock.now();
    peer.recent = peer.recent.filter((t) => now - t < 1);
    peer.recent.push(now);
    if (peer.recent.length > LIMITS.perSecond) {
      this.refuse("rate");
      this.end(id);
      return;
    }
    const msg = parseObject(text);
    if (msg === null) {
      this.refuse("json");
      this.end(id);
      return;
    }
    if (peer.conn === null) {
      this.hello(id, peer, msg);
      return;
    }
    const clean = cleanJoinerMessage(msg);
    if (clean === null) {
      // an unknown or malformed message is ignored, as the device ignores
      // the game server's own messages
      this.refuse("message");
      return;
    }
    peer.conn.receive(JSON.stringify(clean));
  }

  private hello(id: string, peer: Peer, msg: Record<string, unknown>): void {
    const hello = cleanHello(msg);
    if (hello === null) {
      this.refuse("hello");
      this.end(id);
      return;
    }
    if (hello.nearby_v !== NEARBY_V) {
      this.refuse("version");
      this.link?.send(id, JSON.stringify({ type: "error", code: "nearby_version", message: NEARBY_COPY.versionMismatch }));
      this.end(id);
      return;
    }
    if (hello.peek) {
      // the seat picker: the seats, and the link stays unseated until its pick
      this.link?.send(id, JSON.stringify(nearbyPeekJson(this.room)));
      this.helloBy(id, peer, PEEK_SECONDS);
      return;
    }
    if (hello.token) {
      // a joiner back with its token: any older link of its seat is closed,
      // so frames never reach that phone twice
      for (const [other, p] of this.peers) if (other !== id && p.token === hello.token) this.end(other);
    }
    peer.conn = this.server.connect((frame) => this.deliver(id, peer, frame));
    peer.conn.receive(JSON.stringify({ type: "table_join", code: this.room.code, name: hello.name, token: hello.token,
                                       seat: hello.seat ?? null }));
  }

  /** A frame from the room to one joiner. A `left`, or a refusal that
   *  leaves the connection with no seat, ends the link after it is sent. */
  private deliver(id: string, peer: Peer, frame: string): void {
    if (peer.closed || this.peers.get(id) !== peer) return;
    try {
      this.link?.send(id, frame);
    } catch {
      this.refuse("send");
      this.end(id);
      return;
    }
    if (frame.startsWith('{"type":"resume"')) peer.token = (parseObject(frame)?.token as string | undefined) ?? null;
    if (frame.startsWith('{"type":"left"')) this.end(id);
    else if (frame.startsWith('{"type":"error"')) {
      const code = parseObject(frame)?.code;
      if (code === "room_full" || code === "room_not_found" || code === "stale_connection") this.end(id);
    }
  }
}
