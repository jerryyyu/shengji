// Test tables for nearby play: a host page on a LocalSocket, joiners on
// NearbySockets over a FakeTransport, all on one VirtualClock, each seat
// optionally played by the fixtures' HumanDriver. Used by the nearby tests
// only; nothing in the page imports it.
import { VirtualClock } from "../clock";
import { HumanDriver } from "../driver";
import { LocalServer, type LocalRoom } from "../server";
import { LocalSocket } from "../socket";
import { NearbyHost } from "./host";
import { NearbySocket } from "./socket";
import { FakeTransport } from "./transport";

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

  constructor(seed: number, rounds = 1, delay = 0) {
    this.server = new LocalServer({ clock: this.clock, seed: () => seed });
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
          this.clock.setTimeout(() => sock.send(JSON.stringify(a)), this.think);
        }
      }
    };
  }

  /** The host page creates a nearby table and starts advertising it. */
  async open(drive = false, name = "Host"): Promise<void> {
    const sock = new LocalSocket(this.server);
    this.host = { name, sock, frames: [], token: null, driver: null, seat: null, left: false };
    this.wire(this.host, drive);
    sock.onopen = () => sock.send(JSON.stringify({ type: "create_room", nearby: true, name }));
    await this.clock.run(() => this.host.frames.some((f) => f.type === "room"), 10_000);
    this.room = [...this.server.rooms.values()][0];
    this.nearbyHost = new NearbyHost(this.server, this.room);
    await this.nearbyHost.start(this.fake);
  }

  /** A joiner types the code and joins (or resumes with `token`). */
  async join(name: string, opts: { drive?: boolean; token?: string | null; player?: Player } = {}): Promise<Player> {
    const sock = new NearbySocket(this.fake, this.code);
    const p: Player = opts.player ?? { name, sock, frames: [], token: null, driver: null, seat: null, left: false };
    p.sock = sock;
    p.left = false;
    this.wire(p, opts.drive ?? false);
    const token = opts.token === undefined ? null : opts.token;
    const before = p.frames.length;
    sock.onopen = () => sock.send(JSON.stringify({ type: "table_join", code: this.code, name, token, expect: "room" }));
    if (!opts.player) this.joiners.push(p);
    await this.clock.run(() => p.frames.slice(before).some((f) => f.type === "room" || f.type === "state" || f.type === "error"), 50_000);
    return p;
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
