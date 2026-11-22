// Test tables for nearby play: a host page on a LocalSocket, joiners on
// NearbySockets over a FakeTransport, all on one VirtualClock, each seat
// optionally played by the fixtures' HumanDriver. Used by the nearby tests
// only; nothing in the page imports it.
import type { BotLevel } from "../../../queue/messages";
import { type Clock, VirtualClock } from "../clock";
import { HumanDriver } from "../driver";
import type { RemoteBot } from "../pybot";
import { LocalServer, type LocalRoom } from "../server";
import { LocalSocket } from "../socket";
import { NearbyHost } from "./host";
import { NearbySocket } from "./socket";
import { FakeTransport, type HostHandlers, type NearbyTransport } from "./transport";

export type Frame = Record<string, unknown> & { type: string };

export interface Player {
  name: string;
  sock: LocalSocket | NearbySocket;
  frames: Frame[];
  token: string | null;
  driver: HumanDriver | null;
  /** Seat from the latest frame that named one. */
  seat: number | null;
  left: boolean;
}

/** The host phone's own clock over the table's (the simulator's
 *  DeviceClock): `post` runs the host page's work now, or once its JS is
 *  back from a freeze. */
export interface HostClock extends Clock {
  post(fn: () => void): void;
}

export class NearbyTable {
  readonly clock = new VirtualClock();
  readonly server: LocalServer;
  readonly fake: FakeTransport;
  host!: Player;
  readonly joiners: Player[] = [];
  nearbyHost: NearbyHost | null = null;
  room: LocalRoom | null = null;
  rounds: number;
  /** Seconds a driven player takes to answer a frame. */
  think = 0.3;

  /** The host page's clock: the table's, or `hostClock`'s, which can freeze. */
  readonly hostClock: HostClock | null;

  constructor(seed: number, rounds = 1, delay = 0, remote: RemoteBot | null = null,
              hostClock: ((vc: VirtualClock) => HostClock) | null = null) {
    this.hostClock = hostClock?.(this.clock) ?? null;
    this.server = new LocalServer({ clock: this.hostClock ?? this.clock, seed: () => seed, remote });
    this.fake = new FakeTransport(this.clock, delay);
    this.rounds = rounds;
  }

  get code(): string {
    return this.room!.code;
  }

  liveRound = () => this.room?.round ?? null;

  private wire(p: Player, drive: boolean): void {
    p.sock.onmessage = (ev) => {
      const msg = JSON.parse(ev.data as string) as Frame;
      p.frames.push(msg);
      if (msg.type === "resume") p.token = msg.token as string;
      if (typeof msg.you === "number") {
        p.seat = msg.you;
        if (drive && msg.type === "state" && (!p.driver || (p.driver as unknown as { seat: number }).seat !== msg.you)) {
          p.driver = new HumanDriver(this.rounds, this.liveRound, false, msg.you);
        }
      }
      if (msg.type === "left") p.left = true;
      // a person takes a moment to act, so the host's rate limit sees a
      // human pace rather than every seat answering at one instant
      if (p.driver) {
        for (const a of p.driver.react(msg)) {
          const sock = p.sock;
          (p === this.host ? this.hostClock ?? this.clock : this.clock).setTimeout(() => sock.send(JSON.stringify(a)), this.think);
        }
      }
    };
  }

  /** The host page creates a nearby table and starts advertising it. */
  async open(drive = false, name = "Host", botLevel?: BotLevel): Promise<void> {
    const sock = new LocalSocket(this.server);
    this.host = { name, sock, frames: [], token: null, driver: null, seat: null, left: false };
    this.wire(this.host, drive);
    sock.onopen = () => sock.send(JSON.stringify({ type: "create_room", nearby: true, name,
                                                         ...(botLevel ? { bot_level: botLevel } : {}) }));
    await this.clock.run(() => this.host.frames.some((f) => f.type === "room"), 10_000);
    this.room = [...this.server.rooms.values()][0];
    this.nearbyHost = new NearbyHost(this.server, this.room);
    await this.nearbyHost.start(this.hostClock ? this.hostTransport(this.hostClock) : this.fake);
  }

  /** The fake transport, with each link event to the host run in the host
   *  page's JS (held while it is frozen). */
  private hostTransport(hc: HostClock): NearbyTransport {
    const fake = this.fake;
    return {
      host: (code, h) => {
        const posted = Object.fromEntries(Object.entries(h).map(([k, fn]) =>
          [k, typeof fn === "function" ? (...a: unknown[]) => hc.post(() => (fn as (...x: unknown[]) => void)(...a)) : fn]));
        return fake.host(code, posted as unknown as HostHandlers);
      },
      join: fake.join.bind(fake),
    };
  }

  /** A joiner types the code and joins (or resumes with `token`). */
  async join(name: string, opts: { drive?: boolean; token?: string | null; player?: Player; device?: string; seat?: number } = {}): Promise<Player> {
    const sock = this.socket(opts.device);
    const p: Player = opts.player ?? { name, sock, frames: [], token: null, driver: null, seat: null, left: false };
    p.sock = sock;
    p.left = false;
    this.wire(p, opts.drive ?? false);
    const token = opts.token === undefined ? null : opts.token;
    const before = p.frames.length;
    sock.onopen = () => sock.send(JSON.stringify({ type: "table_join", code: this.code, name, token, expect: "room",
                                                    ...(opts.seat !== undefined ? { seat: opts.seat } : {}) }));
    if (!opts.player) this.joiners.push(p);
    await this.clock.run(() => p.frames.slice(before).some((f) => f.type === "room" || f.type === "state" || f.type === "error"), 50_000);
    return p;
  }

  /** A joiner's socket on this table's clock, from `device` when named
   *  (else a phone of its own); `greet` as the page's resume hello. */
  socket(device?: string, greet: (() => Record<string, unknown> | null) | null = null): NearbySocket {
    const transport = device === undefined ? this.fake : {
      host: this.fake.host.bind(this.fake),
      join: (code: string, handlers: Parameters<FakeTransport["join"]>[1]) => this.fake.join(code, handlers, device),
    };
    return new NearbySocket(transport, this.code, null, this.clock, greet);
  }

  /** A seated joiner's new link, as the page makes one after a drop: its
   *  hello is the resume by token, and it opens once the host has answered.
   *  Resolves when the socket has opened or closed. */
  async resume(p: Player, device?: string): Promise<NearbySocket> {
    const sock = this.socket(device, () => ({ type: "table_join", code: this.code, name: p.name, token: p.token }));
    p.sock = sock;
    p.left = false;
    this.wire(p, p.driver !== null);
    await this.clock.run(() => sock.readyState !== NearbySocket.CONNECTING, 50_000);
    return sock;
  }

  send(p: Player, msg: Record<string, unknown>): void {
    p.sock.send(JSON.stringify(msg));
  }

  async settle(until: () => boolean = () => false, max = 200_000): Promise<void> {
    await this.clock.run(until, max);
  }

  /** Run the clock exactly `seconds` forward. */
  async advance(seconds: number): Promise<void> {
    const until = this.clock.now() + seconds;
    // a timer at the end, so the clock stops there instead of jumping past
    this.clock.setTimeout(() => {}, seconds);
    await this.clock.run(() => this.clock.now() >= until, 2_000_000);
  }

  players(): Player[] {
    return [this.host, ...this.joiners];
  }

  lastState(p: Player): Frame | undefined {
    for (let i = p.frames.length - 1; i >= 0; i--) if (p.frames[i].type === "state") return p.frames[i];
    return undefined;
  }
}
