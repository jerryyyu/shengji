// The nearby link, as the host room and the joiner's socket see it. It names
// no radio: the native plugin (native.ts here, NearbyPlugin.swift) is one
// implementation and FakeTransport, in memory, is the other, so the room and
// the client protocol are tested with no device.
import type { Clock } from "../clock";
import { LIMITS, utf8Bytes } from "./protocol";

/** What the link reports about itself, beyond its peers. */
/** `ended`: the host phone was away longer than the joiners' window, so
 *  its table is over (the plugin stops advertising it). */
/** `version`: the only tables found run another nearby version. */
export type LinkState = "ready" | "waiting" | "denied" | "wifiOff" | "notFound" | "failed" | "ended" | "version";

export interface HostHandlers {
  /** `device`: an opaque id for the phone at the other end (one per remote
   *  address, never the address), when the transport can tell. */
  peer(peer: string, connected: boolean, device?: string): void;
  message(peer: string, text: string): void;
  state(state: LinkState, detail?: string): void;
}

export interface HostLink {
  send(peer: string, text: string): void;
  close(peer: string): void;
  stop(): void;
}

export interface JoinHandlers {
  message(text: string): void;
  /** The link to the host is gone (out of range, host stopped, closed). */
  closed(): void;
  state(state: LinkState, detail?: string): void;
  /** A seat's resume: the plugin looks in short cycles (JoinPlan). */
  resume?: boolean;
}

export interface JoinLink {
  send(text: string): void;
  close(): void;
}

export interface NearbyTransport {
  /** Advertise a table for `code`; resolves once it is listening. */
  host(code: string, handlers: HostHandlers): Promise<HostLink>;
  /** Find the table for `code` and connect; rejects (after a `state`) when
   *  there is none or the link cannot be made. */
  join(code: string, handlers: JoinHandlers): Promise<JoinLink>;
  /** Calls `fn` with each change of the phone's network path (true: a
   *  usable path is back); returns the unsubscribe. */
  path?(fn: (up: boolean) => void): () => void;
}

export class NearbyError extends Error {
  readonly state: LinkState;
  constructor(state: LinkState, message: string = state) {
    super(message);
    this.state = state;
  }
}

interface FakeHost {
  code: string;
  handlers: HostHandlers;
  peers: Map<string, JoinHandlers>;
  stopped: boolean;
  /** In the background: not advertised, so a join finds nothing. */
  away: boolean;
}

/** An in-memory radio for tests: any number of hosts and joiners on one
 *  clock, with a per-frame delay, an oversize refusal like the native one,
 *  and switches for a dropped link, a vanished host and a denied permission. */
export class FakeTransport implements NearbyTransport {
  private hosts = new Map<string, FakeHost>();
  /** Joiner ends whose close has been delivered. */
  private gone = new WeakSet<JoinHandlers>();
  private seq = 0;
  private clock: Clock;
  /** Seconds each frame takes to arrive. */
  delay: number;
  /** The next host() or join() fails as a denied permission. */
  deny = false;
  /** Every frame that crossed, in order, for the tests' leak checks. */
  readonly wire: { from: string; to: string; text: string }[] = [];
  /** A joiner's frames to the host, by peer: lost on the way (the link
   *  stays up and the host's frames still arrive), or held back until
   *  `release`. */
  private inbound = new Map<string, "lose" | { held: (() => void)[] }>();

  /** The joiner phone's network: while down, a join finds nothing, or
   *  (`stall`) hangs on an endpoint of the old path and never settles. */
  private up = true;
  private downMode: "fail" | "stall" = "fail";
  private pathListeners = new Set<(up: boolean) => void>();

  constructor(clock: Clock, delay = 0) {
    this.clock = clock;
    this.delay = delay;
  }

  path(fn: (up: boolean) => void): () => void {
    this.pathListeners.add(fn);
    return () => { this.pathListeners.delete(fn); };
  }

  /** The joiner's network goes down (its links drop with it) or comes
   *  back, as the plugin's path monitor reports it. */
  network(up: boolean, code?: string, mode: "fail" | "stall" = "fail"): void {
    this.up = up;
    this.downMode = mode;
    if (!up && code !== undefined) for (const peer of this.peersOf(code)) this.drop(code, peer);
    for (const fn of [...this.pathListeners]) fn(up);
  }

  private later(fn: () => void): void {
    this.clock.setTimeout(fn, this.delay);
  }

  private checkSize(text: string): void {
    if (utf8Bytes(text) > LIMITS.frameBytes) throw new NearbyError("failed", "frame too large");
  }

  async host(code: string, handlers: HostHandlers): Promise<HostLink> {
    if (this.deny) {
      handlers.state("denied");
      throw new NearbyError("denied");
    }
    const h: FakeHost = { code, handlers, peers: new Map(), stopped: false, away: false };
    this.hosts.set(code, h);
    handlers.state("ready");
    return {
      send: (peer, text) => {
        this.checkSize(text);
        const p = h.peers.get(peer);
        if (!p || h.stopped) return;
        this.wire.push({ from: "host", to: peer, text });
        // frames sent before a close still arrive, ahead of the close
        this.later(() => { if (!this.gone.has(p)) p.message(text); });
      },
      close: (peer) => this.cut(h, peer),
      stop: () => this.stopHost(code),
    };
  }

  /** `device`: which phone joins, as the host sees it; each join is its
   *  own phone unless a test names one. */
  async join(code: string, handlers: JoinHandlers, device?: string): Promise<JoinLink> {
    if (this.deny) {
      handlers.state("denied");
      throw new NearbyError("denied");
    }
    if (!this.up && this.downMode === "stall") {
      handlers.state("waiting");
      return new Promise<JoinLink>(() => {});
    }
    if (!this.up) {
      handlers.state("wifiOff");
      throw new NearbyError("wifiOff");
    }
    const h = this.hosts.get(code);
    if (!h || h.stopped || h.away) {
      handlers.state("notFound");
      throw new NearbyError("notFound");
    }
    const peer = `p${++this.seq}`;
    const phone = device ?? `d${this.seq}`;
    h.peers.set(peer, handlers);
    this.later(() => { if (h.peers.get(peer) === handlers) h.handlers.peer(peer, true, phone); });
    return {
      send: (text) => {
        this.checkSize(text);
        if (h.peers.get(peer) !== handlers) return;
        this.wire.push({ from: peer, to: "host", text });
        // frames sent before a close still arrive, ahead of the close, as
        // the host's do
        const arrive = () => { if (!h.stopped) h.handlers.message(peer, text); };
        const mode = this.inbound.get(peer);
        if (mode === "lose") return;
        if (mode) mode.held.push(arrive);
        else this.later(arrive);
      },
      close: () => this.cut(h, peer),
    };
  }

  /** Raw text from a peer, as a modified joiner would send it, unchecked. */
  inject(code: string, peer: string, text: string): void {
    const h = this.hosts.get(code);
    if (h?.peers.has(peer)) h.handlers.message(peer, text);
  }

  /** From now on `peer`'s frames to the host are lost, one way only. */
  lose(peer: string): void {
    this.inbound.set(peer, "lose");
  }

  /** From now on `peer`'s frames to the host wait until `release`. */
  hold(peer: string): void {
    this.inbound.set(peer, { held: [] });
  }

  /** `peer`'s held frames arrive now, in order, and later ones as usual. */
  release(peer: string): void {
    const mode = this.inbound.get(peer);
    this.inbound.delete(peer);
    if (mode && mode !== "lose") for (const arrive of mode.held) this.later(arrive);
  }

  /** The peer ids currently linked to `code`'s host. */
  peersOf(code: string): string[] {
    return [...(this.hosts.get(code)?.peers.keys() ?? [])];
  }

  /** The link to `peer` drops, as when a phone walks out of range. */
  drop(code: string, peer: string): void {
    const h = this.hosts.get(code);
    if (h) this.cut(h, peer);
  }

  private cut(h: FakeHost, peer: string): void {
    const p = h.peers.get(peer);
    if (!p) return;
    h.peers.delete(peer);
    this.later(() => {
      this.gone.add(p);
      p.closed();
      if (!h.stopped) h.handlers.peer(peer, false);
    });
  }

  /** The host app goes to the background and the system ends its links:
   *  every joiner's link closes and the table is not found until `foreground`. */
  background(code: string): void {
    const h = this.hosts.get(code);
    if (!h) return;
    h.away = true;
    for (const peer of [...h.peers.keys()]) this.cut(h, peer);
    h.handlers.state("waiting", "background");
  }

  /** Back in the foreground within the window: advertised again with the
   *  same code, as the plugin re-advertises; after it, the table is over. */
  foreground(code: string, ended = false): void {
    const h = this.hosts.get(code);
    if (!h) return;
    if (ended) {
      h.handlers.state("ended");
      this.stopHost(code);
      return;
    }
    h.away = false;
    h.handlers.state("ready");
  }

  /** The host phone goes away: every joiner's link closes. */
  stopHost(code: string): void {
    const h = this.hosts.get(code);
    if (!h) return;
    for (const peer of [...h.peers.keys()]) this.cut(h, peer);
    h.stopped = true;
    this.hosts.delete(code);
  }
}
