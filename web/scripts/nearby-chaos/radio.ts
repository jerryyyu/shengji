// The chaos simulator's radio: phones on one virtual clock, each with a
// Wi-Fi radio, an access-point network it may have joined (with an address
// that can change on each rejoin) and an app that can be in the background.
// SimPlugin is a TypeScript port of NearbyPlugin.swift's state machine (the
// listener, the browse, the tried set, parallel tries, the Wi-Fi-first look,
// the kept browse, the move off peer-to-peer) behind the same JS interface
// the Capacitor plugin has, so the page's real native.ts runs on top of it.
// On demand only: nothing in the app or in CI imports this.
import type { VirtualClock } from "../../src/offline/server/clock";
import type { NearbyPlugin } from "../../src/offline/server/nearby/native";
import { PhoneHold } from "./hold";

export class Rng {
  private s: number;
  constructor(seed: number) {
    this.s = seed >>> 0 || 1;
  }
  next(): number {
    // mulberry32
    let t = (this.s = (this.s + 0x6d2b79f5) >>> 0);
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  }
  range(a: number, b: number): number {
    return a + (b - a) * this.next();
  }
  int(a: number, b: number): number {
    return Math.floor(this.range(a, b + 1));
  }
  chance(p: number): boolean {
    return this.next() < p;
  }
  pick<T>(xs: readonly T[]): T {
    return xs[Math.floor(this.next() * xs.length)];
  }
}

/** One phone's clock: the shared virtual time, with the app's JS suspended
 *  while it is in the background (its timers and events wait, then run in
 *  order when it is back, as a WebView's do). */
export class DeviceClock {
  private vc: VirtualClock;
  suspended = false;
  private waiting: (() => void)[] = [];
  constructor(vc: VirtualClock) {
    this.vc = vc;
  }
  now(): number {
    return this.vc.now();
  }
  setTimeout(fn: () => void, seconds: number): void {
    this.vc.setTimeout(() => this.post(fn), seconds);
  }
  /** Run `fn` in this phone's JS now, or when it is back in the foreground. */
  post(fn: () => void): void {
    if (this.suspended) this.waiting.push(fn);
    else fn();
  }
  suspend(): void {
    this.suspended = true;
  }
  resume(): void {
    this.suspended = false;
    const w = this.waiting;
    this.waiting = [];
    for (const fn of w) this.vc.setTimeout(() => this.post(fn), 0);
  }
}

export type Iface = "wifi" | "awdl";

/** The radio's knobs; the planted bugs used to validate the simulator are
 *  switched here too. */
export interface RadioOpts {
  /** Seconds an idle AWDL link with no browse lasts before it goes silent. */
  silentAfterIdle: [number, number];
  /** Bugs re-planted to check that the simulator catches them. */
  bugs: Set<string>;
}

interface Dir {
  /** Clock time the latest frame this way arrives (frames keep their order). */
  lastAt: number;
  mode: "ok" | "lose" | "hold";
  held: (() => void)[];
}

/** One TCP + TLS + WebSocket connection, as both of its ends see it. */
export class SimLink {
  readonly id: number;
  readonly iface: Iface;
  readonly joiner: Phone;
  readonly host: Phone;
  /** The remote address the host sees, for its device ids. */
  readonly remote: string;
  dead = false;
  /** An AWDL link that dozed: nothing more crosses it either way. */
  silent = false;
  lastTraffic: number;
  toHost: Dir = { lastAt: 0, mode: "ok", held: [] };
  toJoiner: Dir = { lastAt: 0, mode: "ok", held: [] };
  idleLimit: number;
  /** Callbacks into each end's plugin. */
  onJoinerMessage: (text: string) => void = () => {};
  onHostMessage: (text: string) => void = () => {};
  onJoinerClosed: () => void = () => {};
  onHostClosed: () => void = () => {};
  joinerNotified = false;
  hostNotified = false;
  constructor(id: number, iface: Iface, joiner: Phone, host: Phone, now: number, idleLimit: number) {
    this.id = id;
    this.iface = iface;
    this.joiner = joiner;
    this.host = host;
    this.lastTraffic = now;
    this.idleLimit = idleLimit;
    this.remote = iface === "wifi" ? `${joiner.id}/wifi/${joiner.wifiAddr}` : `${joiner.id}/awdl`;
  }
}

export interface Service {
  name: string;
  salt: string;
  host: Phone;
}

interface Browser {
  phone: Phone;
  p2p: boolean;
  /** Service names this browser has reported. */
  seen: Set<string>;
  onResults: (results: BrowseResult[]) => void;
  cancelled: boolean;
  /** A browser that only looks over Wi-Fi for its host (the move off AWDL). */
  wifiOnly: boolean;
}

export interface BrowseResult {
  name: string;
  ifaces: Iface[];
  v: string;
  salt: string;
}

export class Phone {
  readonly id: string;
  radio = true;
  joined: boolean;
  wifiAddr = 0;
  clock: DeviceClock;
  plugin!: SimPlugin;
  constructor(id: string, clock: DeviceClock, joined: boolean) {
    this.id = id;
    this.clock = clock;
    this.joined = joined;
  }
}

export type TraceFn = (who: string, text: string) => void;

/** The air between the phones. */
export class Radio {
  readonly vc: VirtualClock;
  readonly rng: Rng;
  readonly opts: RadioOpts;
  readonly phones: Phone[] = [];
  readonly links = new Set<SimLink>();
  private services = new Map<string, Service>();
  private browsers = new Set<Browser>();
  private seq = 0;
  trace: TraceFn;
  /** Every link ever made, for the invariants (via, reconnect counts). */
  readonly history: SimLink[] = [];

  constructor(vc: VirtualClock, rng: Rng, opts: RadioOpts, trace: TraceFn) {
    this.vc = vc;
    this.rng = rng;
    this.opts = opts;
    this.trace = trace;
  }

  addPhone(id: string, joined = true): Phone {
    const p = new Phone(id, new DeviceClock(this.vc), joined);
    p.plugin = new SimPlugin(this, p);
    this.phones.push(p);
    return p;
  }

  at(seconds: number, fn: () => void): void {
    this.vc.setTimeout(fn, Math.max(0, seconds));
  }

  /** One frame's time over a link. */
  latency(link: SimLink): number {
    const r = this.rng;
    if (link.iface === "wifi") {
      if (r.chance(0.01)) return r.range(0.1, 0.4);
      return r.range(0.004, 0.03);
    }
    // AWDL: slower, and with long pauses while the joiner also serves a
    // Wi-Fi network (the radio hops channels)
    const busy = link.joiner.joined || link.host.joined;
    if (busy && r.chance(0.03)) return r.range(0.5, 2.0);
    if (r.chance(0.01)) return r.range(0.2, 0.8);
    return r.range(0.02, 0.09);
  }

  // services and browsing

  advertise(s: Service): void {
    this.services.set(s.name, s);
    this.trace(s.host.id, `radio: advertising ${s.name}`);
    for (const b of this.browsers) this.reportSoon(b, false);
  }

  unadvertise(name: string): void {
    this.services.delete(name);
  }

  /** What `b` would see now. */
  private resultsFor(b: Browser): BrowseResult[] {
    const out: BrowseResult[] = [];
    const me = b.phone;
    for (const s of this.services.values()) {
      const ifaces: Iface[] = [];
      if (me.radio && s.host.radio && me.joined && s.host.joined) ifaces.push("wifi");
      if (b.p2p && !b.wifiOnly && me.radio && s.host.radio) ifaces.push("awdl");
      if (ifaces.length) out.push({ name: s.name, ifaces, v: "2", salt: s.salt });
    }
    return out;
  }

  browse(phone: Phone, p2p: boolean, onResults: (r: BrowseResult[]) => void, wifiOnly = false): () => void {
    const b: Browser = { phone, p2p, seen: new Set(), onResults, cancelled: false, wifiOnly };
    this.browsers.add(b);
    this.reportSoon(b, true);
    return () => {
      b.cancelled = true;
      this.browsers.delete(b);
    };
  }

  /** Whether `phone` has a browse running now (the AWDL data path stays up
   *  only while it does). */
  browsing(phone: Phone): boolean {
    for (const b of this.browsers) if (b.phone === phone && !b.wifiOnly) return true;
    return false;
  }

  /** A fresh browse reports everything it sees; a running one reports only
   *  services it has never seen (a table that comes back over a path that
   *  changed is not reported again until a fresh browse). */
  private reportSoon(b: Browser, fresh: boolean): void {
    const wait = b.p2p && !b.phone.joined ? this.rng.range(0.3, 2.5) : this.rng.range(0.1, 1.0);
    this.at(wait, () => {
      if (b.cancelled) return;
      const results = this.resultsFor(b);
      const newOnes = results.filter((r) => !b.seen.has(r.name));
      if (!fresh && newOnes.length === 0) return;
      for (const r of results) b.seen.add(r.name);
      b.onResults(results);
    });
  }

  /** A browse that is running sees the path changes it would see in life:
   *  only a brand-new service. */
  pathChanged(): void {
    for (const b of this.browsers) this.reportSoon(b, false);
  }

  // links

  /** The joiner's connection attempt to service `name`: calls `ready` with
   *  the link once the handshake is done, or `failed`; a route that is gone
   *  just stalls (the plugin's handshake timeout ends it). */
  connect(joiner: Phone, name: string, p2p: boolean, ready: (l: SimLink) => void, failed: () => void): () => void {
    let cancelled = false;
    const s = this.services.get(name);
    const host = s?.host;
    let iface: Iface | null = null;
    if (host && joiner.radio && host.radio && joiner.joined && host.joined) iface = "wifi";
    else if (host && p2p && joiner.radio && host.radio) iface = "awdl";
    const cancel = () => { cancelled = true; };
    if (!s || !host || iface === null) {
      this.trace(joiner.id, `radio: connect ${name}: no route (stalls)`);
      return cancel;
    }
    const hs = iface === "wifi" ? this.rng.range(0.03, 0.2) : this.rng.chance(0.03) ? this.rng.range(2.5, 4.5) : this.rng.range(0.1, 1.2);
    this.at(hs, () => {
      if (cancelled) return;
      // the route must still be there at the end of the handshake
      const still = this.services.get(name) === s && joiner.radio && host.radio
        && (iface === "awdl" || (joiner.joined && host.joined));
      if (!still) {
        this.trace(joiner.id, `radio: connect ${name}: the route went during the handshake`);
        return;
      }
      if (!host.plugin.acceptable()) {
        this.trace(joiner.id, `radio: connect ${name}: refused by the host`);
        failed();
        return;
      }
      const link = new SimLink(++this.seq, iface!, joiner, host, this.vc.now(),
                               this.rng.range(this.opts.silentAfterIdle[0], this.opts.silentAfterIdle[1]));
      this.links.add(link);
      this.history.push(link);
      host.plugin.inbound(link);
      ready(link);
    });
    return cancel;
  }

  /** `from` sends one frame on `link`. */
  send(link: SimLink, fromJoiner: boolean, text: string): void {
    if (link.dead) return;
    const now = this.vc.now();
    const dir = fromJoiner ? link.toHost : link.toJoiner;
    if (link.iface === "awdl" && !link.silent && now - link.lastTraffic > link.idleLimit && !this.browsing(link.joiner)) {
      link.silent = true;
      this.trace(link.joiner.id, `radio: AWDL link ${link.id} went silent after ${(now - link.lastTraffic).toFixed(1)} s idle (no browse)`);
    }
    if (link.silent) return;
    if (dir.mode === "lose") return;
    link.lastTraffic = now;
    const deliver = () => {
      if (link.dead || link.silent) return;
      if (fromJoiner) link.onHostMessage(text);
      else link.onJoinerMessage(text);
    };
    if (dir.mode === "hold") {
      dir.held.push(deliver);
      return;
    }
    const at = Math.max(dir.lastAt, now + this.latency(link));
    dir.lastAt = at;
    this.vc.setTimeout(deliver, at - now);
  }

  /** One end closes the link: the other end hears it after a moment, and
   *  nothing in flight arrives. */
  close(link: SimLink, byJoiner: boolean): void {
    if (link.dead) return;
    link.dead = true;
    this.links.delete(link);
    const notifyOther = () => {
      if (byJoiner) this.notifyHost(link);
      else this.notifyJoiner(link);
    };
    // a closed AWDL or silent link may take a TCP timeout to be noticed
    if (link.silent) return;
    this.at(this.latency(link), notifyOther);
  }

  notifyJoiner(link: SimLink): void {
    if (link.joinerNotified) return;
    link.joinerNotified = true;
    link.onJoinerClosed();
  }

  notifyHost(link: SimLink): void {
    if (link.hostNotified) return;
    link.hostNotified = true;
    link.onHostClosed();
  }

  /** The network breaks `link`: each end hears of it (after `delay`) or,
   *  when `quiet`, never does (a half-open link both ends think is up). */
  breakLink(link: SimLink, quietJoiner: boolean, quietHost: boolean): void {
    if (link.dead) return;
    link.dead = true;
    this.links.delete(link);
    if (!quietJoiner) this.at(this.rng.range(0.05, 1.5), () => this.notifyJoiner(link));
    if (!quietHost) this.at(this.rng.range(0.05, 1.5), () => this.notifyHost(link));
  }

  /** The link stays up, but frames one way are lost from now on. */
  halfOpen(link: SimLink, toHost: boolean): void {
    (toHost ? link.toHost : link.toJoiner).mode = "lose";
  }

  stall(link: SimLink): void {
    link.toHost.mode = "hold";
    link.toJoiner.mode = "hold";
  }

  unstall(link: SimLink): void {
    for (const d of [link.toHost, link.toJoiner]) {
      if (d.mode !== "hold") continue;
      d.mode = "ok";
      const held = d.held;
      d.held = [];
      let t = 0;
      for (const fn of held) {
        t += 0.002;
        this.vc.setTimeout(fn, t);
      }
      d.lastAt = this.vc.now() + t;
    }
  }

  linksOf(p: Phone): SimLink[] {
    return [...this.links].filter((l) => l.joiner === p || l.host === p);
  }

  /** A phone's network changes; its links over the old path break. */
  setNet(p: Phone, change: { radio?: boolean; joined?: boolean; newAddress?: boolean }): void {
    const wasRadio = p.radio;
    const wasJoined = p.joined;
    if (change.radio !== undefined) p.radio = change.radio;
    if (change.joined !== undefined) p.joined = change.joined;
    if (p.joined && !wasJoined && change.newAddress) p.wifiAddr += 1;
    this.trace(p.id, `radio: net radio ${p.radio ? "on" : "off"}, Wi-Fi ${p.joined ? "joined" : "not joined"}${change.newAddress && p.joined && !wasJoined ? " (new address)" : ""}`);
    for (const l of this.linksOf(p)) {
      const lost = !p.radio || (l.iface === "wifi" && !p.joined);
      if (!lost) continue;
      // an interface going away: the phone itself mostly hears of it, the
      // other end does not (it finds out from the silence)
      const mine = l.joiner === p;
      const quietMe = this.rng.chance(0.4);
      this.breakLink(l, mine ? quietMe : true, mine ? true : quietMe);
    }
    if (p.radio !== wasRadio || p.joined !== wasJoined) {
      this.at(this.rng.range(0.05, 0.6), () => p.plugin.pathUpdate());
      this.pathChanged();
    }
  }
}

type Ev = Record<string, unknown>;
type EvFn = (ev: Ev) => void;

/** The plugin's constants, as in NearbyPlugin.swift. */
const JOIN_HANDSHAKE = 3;
const MAX_PARALLEL = 4;
const MAX_TRIES = 8;
const ALL_FAILED_GRACE = 1;
const HOST_WINDOW = 60;
const FIND_TIMEOUT = 12;
const RESUME_FIND_TIMEOUT = 4;
const WIFI_FIRST = 2;
const MAX_CONNECTED = 5;

interface PLink {
  peer: string;
  link: SimLink | null;
  ready: boolean;
  remote: string;
}

interface Attempt {
  cancel: () => void;
  done: boolean;
}

/** NearbyPlugin.swift's state machine, ported, on the simulated radio. */
export class SimPlugin implements NearbyPlugin {
  private radio: Radio;
  readonly phone: Phone;
  private listeners = new Map<string, Set<EvFn>>();
  private session = 0;
  private links = new Map<string, PLink>();
  // host side
  private hostCode = "";
  private hostSalt = "";
  private listenerName: string | null = null;
  private listenerReady = false;
  private needsReadvertise = false;
  backgroundedAt: number | null = null;
  appActive = true;
  private deviceIds = new Map<string, string>();
  private peerSeq = 0;
  // join side
  private joinCode = "";
  private resuming = false;
  private stopBrowse: (() => void) | null = null;
  private candidates: BrowseResult[] = [];
  private tried = new Set<string>();
  private tries = 0;
  private attempts: Attempt[] = [];
  private findDeadline = Infinity;
  private candidateArrivals = 0;
  private lastHostName: string | null = null;
  private lastHostSalt: string | null = null;
  private pathSatisfied: boolean | null = null;
  private wifiUp: boolean;
  private fellBack = false;
  private fellBackUnseen = false;
  hostOverP2P = false;
  private migrationDone = false;
  private stopWifiBrowse: (() => void) | null = null;
  /** Called with each message the host's page is handed, around the call. */
  onHostDeliver: ((peer: string, text: string, run: () => void) => void) | null = null;
  /** The device test's stall (debugChaos "stall"): every frame of this
   *  phone, on every link and on links made during it, waits for its end. */
  readonly hold = new PhoneHold<PLink>();
  private linkOf = (peer: string): PLink | null => this.links.get(peer) ?? null;

  /** Starts the phone's stall; false when one runs. */
  stallStart(): boolean {
    if (this.hold.stalling) return false;
    this.hold.stalling = true;
    this.log("CHAOS stall sends and receives");
    return true;
  }

  stallEnd(): void {
    if (!this.hold.stalling) return;
    const r = this.hold.flush();
    this.log(`CHAOS stall over: ${r.held} held, ${r.dropped} dropped (link gone)`);
  }

  constructor(radio: Radio, phone: Phone) {
    this.radio = radio;
    this.phone = phone;
    this.wifiUp = phone.joined;
    this.pathSatisfied = phone.joined;
  }

  private get lookP2P(): boolean {
    return !this.wifiUp || this.fellBack;
  }

  private get lookTime(): number {
    if (this.radio.opts.bugs.has("tried")) return FIND_TIMEOUT;
    return this.resuming ? RESUME_FIND_TIMEOUT : FIND_TIMEOUT;
  }

  private log(text: string): void {
    this.radio.trace(this.phone.id, `native: ${text}`);
  }

  private emit(event: string, ev: Ev): void {
    const fns = this.listeners.get(event);
    if (!fns || fns.size === 0) return;
    // the bridge hands the event to the page's JS a moment later
    this.radio.at(0.001, () => this.phone.clock.post(() => { for (const fn of [...fns]) fn(ev); }));
  }

  // the JS interface

  async capabilities() {
    return { reviewed: false, debug: true, nearbyV: 2, serviceType: "_shengji-nearby._tcp" };
  }
  async openSettings() {
    return undefined;
  }

  addListener(event: string, fn: EvFn): Promise<{ remove(): void }> {
    if (!this.listeners.has(event)) this.listeners.set(event, new Set());
    this.listeners.get(event)!.add(fn);
    return Promise.resolve({ remove: () => { this.listeners.get(event)?.delete(fn); } });
  }

  async host(opts: { code: string }): Promise<unknown> {
    this.reset();
    this.hostCode = opts.code;
    this.hostSalt = `salt${this.radio.rng.int(0, 1e9)}`;
    return new Promise<void>((resolve) => {
      this.startListener(() => resolve());
    });
  }

  async join(opts: { code: string; resume?: boolean }): Promise<unknown> {
    this.reset();
    this.joinCode = opts.code;
    this.resuming = opts.resume === true;
    this.fellBack = false;
    this.fellBackUnseen = false;
    this.log(`join (${this.resuming ? "resume" : "first look"})`);
    this.startBrowse();
    this.fallBackToPeerToPeerSoon();
    return undefined;
  }

  send(opts: { peer: string; text: string }): Promise<unknown> {
    return new Promise((resolve, reject) => {
      const go = () => {
        const l = this.links.get(opts.peer);
        if (!l || !l.ready || !l.link) return reject(new Error("no such peer"));
        this.radio.send(l.link, opts.peer === "host", opts.text);
        resolve(undefined);
      };
      if (this.hold.hold(opts.peer, this.linkOf, go, () => reject(new Error("no such peer")))) return;
      go();
    });
  }

  async close(opts: { peer: string }): Promise<unknown> {
    this.drop(opts.peer);
    return undefined;
  }

  async stop(): Promise<unknown> {
    this.reset();
    return undefined;
  }

  // host

  private get hosting(): boolean {
    return this.hostCode !== "";
  }

  /** Whether an inbound handshake may finish here now. */
  acceptable(): boolean {
    if (!this.hosting || !this.listenerReady) return false;
    const connected = [...this.links.values()].filter((l) => l.ready).length;
    return connected < MAX_CONNECTED;
  }

  private startListener(onReady?: () => void): void {
    const session = this.session;
    if (this.listenerName) this.radio.unadvertise(this.listenerName);
    const name = `svc${this.radio.rng.int(0, 1e8)}`;
    this.listenerName = name;
    this.listenerReady = false;
    this.needsReadvertise = false;
    this.log("listener start");
    this.radio.at(this.radio.rng.range(0.05, 0.4), () => {
      if (this.session !== session || this.listenerName !== name) return;
      this.listenerReady = true;
      this.radio.advertise({ name, salt: this.hostSalt, host: this.phone });
      this.log("listener ready");
      onReady?.();
      this.emit("state", { state: "ready" });
    });
  }

  /** The system stopped the listener (a fault, or the app's background). */
  listenerLost(): void {
    if (!this.hosting) return;
    this.log("listener lost");
    if (this.listenerName) this.radio.unadvertise(this.listenerName);
    this.listenerName = null;
    this.listenerReady = false;
    this.needsReadvertise = true;
    this.emit("state", { state: "waiting", detail: "background" });
    if (!this.appActive || this.backgroundedAt !== null) return;
    const session = this.session;
    this.radio.at(1, () => {
      if (this.session === session && this.hosting && this.appActive && this.needsReadvertise) this.hostReturned();
    });
  }

  hostLeft(): void {
    if (!this.hosting) return;
    this.backgroundedAt = this.radio.vc.now();
  }

  hostReturned(): void {
    if (!this.hosting) return;
    const away = this.backgroundedAt;
    this.backgroundedAt = null;
    if (away !== null && this.radio.vc.now() - away > HOST_WINDOW) {
      this.log("away past the window: table ended");
      this.reset();
      this.emit("state", { state: "ended" });
      return;
    }
    if (this.listenerName !== null && !this.needsReadvertise) return;
    this.startListener();
  }

  inbound(link: SimLink): void {
    let peer = `p${++this.peerSeq}`;
    while (this.links.has(peer)) peer = `p${++this.peerSeq}`;
    const l: PLink = { peer, link, ready: true, remote: link.remote };
    this.links.set(peer, l);
    const session = this.session;
    link.onHostMessage = (text) => {
      if (this.session !== session || this.links.get(peer) !== l) return;
      const fns = this.listeners.get("message");
      if (!fns) return;
      const ev = { peer, text };
      const deliver = () => this.radio.at(0.001, () => this.phone.clock.post(() => {
        const run = () => { for (const fn of [...fns]) fn(ev); };
        if (this.onHostDeliver) this.onHostDeliver(peer, text, run);
        else run();
      }));
      if (!this.hold.hold(peer, this.linkOf, deliver, () => {})) deliver();
    };
    link.onHostClosed = () => {
      if (this.session !== session || this.links.get(peer) !== l) return;
      this.drop(peer, true);
    };
    this.log(`inbound ${peer} up via ${link.iface}`);
    this.emit("peer", { peer, state: "connected", device: this.deviceId(link.remote) });
  }

  private deviceId(remote: string): string {
    let id = this.deviceIds.get(remote);
    if (!id) {
      id = `dev${this.deviceIds.size + 1}`;
      this.deviceIds.set(remote, id);
    }
    return id;
  }

  /** The peer the host knows `link` by, if any. */
  peerOf(link: SimLink): string | null {
    for (const [peer, l] of this.links) if (l.link === link) return peer;
    return null;
  }

  // join

  private startBrowse(): void {
    this.findDeadline = this.radio.vc.now() + this.lookTime;
    const session = this.session;
    if (!this.phone.radio) {
      this.radio.at(0.05, () => { if (this.session === session) this.emit("state", { state: "wifiOff" }); });
    }
    this.stopBrowse?.();
    const p2p = this.lookP2P;
    let stop: (() => void) | null = null;
    stop = this.radio.browse(this.phone, p2p, (results) => {
      if (this.session !== session || this.stopBrowse !== stop) return;
      this.log(`browse: ${results.length} result(s) [${results.map((r) => r.ifaces.join("+")).join(",")}]`);
      for (const r of results) {
        if (this.tried.has(r.name) || this.candidates.some((c) => c.name === r.name)) continue;
        this.candidates.push(r);
        this.candidateArrivals += 1;
      }
      this.tryNext();
    });
    this.stopBrowse = stop;
    this.log(`browse: peer-to-peer ${p2p ? "allowed" : "off (Wi-Fi up)"}`);
    const deadline = this.findDeadline;
    this.radio.at(this.lookTime, () => {
      if (this.session === session && this.findDeadline === deadline) this.checkNotFound();
    });
  }

  private cancelBrowse(): void {
    this.stopBrowse?.();
    this.stopBrowse = null;
  }

  private fallBackToPeerToPeerSoon(): void {
    if (this.lookP2P) return;
    const session = this.session;
    this.radio.at(WIFI_FIRST, () => {
      if (this.session !== session || this.fellBack || this.links.has("host") || this.attempts.length || !this.joinCode) return;
      this.log("no table over Wi-Fi in 2 s: allowing peer-to-peer");
      this.fellBack = true;
      this.fellBackUnseen = this.candidateArrivals === 0;
      this.lookAgainOnNewPath();
    });
  }

  private lookAgainOnNewPath(): void {
    if (!this.joinCode || this.links.has("host")) return;
    this.log("look again on the new path");
    for (const a of this.attempts) a.cancel();
    this.attempts = [];
    this.cancelBrowse();
    this.candidates = [];
    if (!this.radio.opts.bugs.has("tried")) this.tried = new Set();
    this.tries = 0;
    this.candidateArrivals = 0;
    this.startBrowse();
  }

  /** The path monitor's report, after the phone's network changed. */
  pathUpdate(): void {
    const satisfied = this.phone.joined && this.phone.radio;
    const wifi = satisfied;
    if (satisfied === this.pathSatisfied && wifi === this.wifiUp) return;
    const regained = satisfied && this.pathSatisfied === false;
    this.pathSatisfied = satisfied;
    this.wifiUp = wifi;
    this.log(`path ${satisfied ? "satisfied" : "unsatisfied"} Wi-Fi joined ${wifi}${regained ? " (regained)" : ""}`);
    if (this.radio.opts.bugs.has("tried")) {
      // the look before the path watch: no path event for the page and no
      // fresh look on the new path (the tried set and the browse are kept)
      this.watchForWifiHost();
      return;
    }
    this.emit("path", { satisfied });
    if (regained) this.lookAgainOnNewPath();
    this.watchForWifiHost();
  }

  private tryNext(): void {
    if (this.links.has("host")) return;
    const prefer = this.lastHostName;
    if (prefer) this.candidates = [...this.candidates.filter((c) => c.name !== prefer), ...this.candidates.filter((c) => c.name === prefer)];
    while (this.attempts.length < MAX_PARALLEL && this.tries < MAX_TRIES && this.candidates.length) {
      const r = this.candidates.pop()!;
      this.tried.add(r.name);
      this.tries += 1;
      this.tryTable(r);
    }
    if (this.attempts.length === 0) this.checkNotFound();
  }

  private tryTable(r: BrowseResult): void {
    const session = this.session;
    const a: Attempt = { cancel: () => {}, done: false };
    this.attempts.push(a);
    const tryNo = this.tries;
    const finish = () => {
      if (a.done) return;
      a.done = true;
      a.cancel();
      if (this.session !== session) return;
      const i = this.attempts.indexOf(a);
      if (i >= 0) {
        this.attempts.splice(i, 1);
        this.tryNext();
      }
    };
    a.cancel = this.radio.connect(this.phone, r.name, this.lookP2P, (link) => {
      if (a.done || this.session !== session || this.links.has("host") || !this.attempts.includes(a)) {
        this.radio.close(link, true);
        return;
      }
      a.done = true;
      this.attempts.splice(this.attempts.indexOf(a), 1);
      for (const other of this.attempts) { other.done = true; other.cancel(); }
      this.attempts = [];
      const l: PLink = { peer: "host", link, ready: true, remote: "" };
      this.links.set("host", l);
      this.lastHostName = r.name;
      this.lastHostSalt = r.salt;
      this.hostOverP2P = link.iface === "awdl";
      // Migration.linkUp: the move stays spent only when this look tried
      // Wi-Fi first and fell back with the table in sight there (the loop it
      // guards against); a look made with no Wi-Fi network never tried it
      const noWifiTry = !this.fellBack && !this.radio.opts.bugs.has("migrate-stale");
      if (!this.hostOverP2P || noWifiTry || (this.fellBackUnseen && !this.radio.opts.bugs.has("migrate-once"))) this.migrationDone = false;
      this.log(`host link ${link.id} up via ${link.iface} (try ${tryNo})`);
      const keep = this.hostOverP2P && !this.wifiUp && !this.radio.opts.bugs.has("keepalive");
      if (keep) this.log("browse kept: peer-to-peer link with no Wi-Fi network");
      else this.cancelBrowse();
      link.onJoinerMessage = (text) => {
        if (this.session !== session || this.links.get("host") !== l) return;
        const deliver = () => this.emit("message", { peer: "host", text });
        if (!this.hold.hold("host", this.linkOf, deliver, () => {})) deliver();
      };
      link.onJoinerClosed = () => {
        if (this.session !== session || this.links.get("host") !== l) return;
        this.drop("host", true);
      };
      this.emit("peer", { peer: "host", state: "connected", via: this.hostOverP2P ? "p2p" : "wifi" });
      this.watchForWifiHost();
    }, finish);
    // the handshake's timeout
    this.radio.at(JOIN_HANDSHAKE, () => { if (!a.done) finish(); });
  }

  private watchForWifiHost(): void {
    const l = this.links.get("host");
    if (!l || !this.hostOverP2P || !this.wifiUp || this.stopWifiBrowse || this.migrationDone) return;
    const session = this.session;
    const name = this.lastHostName;
    const salt = this.lastHostSalt;
    this.log("host link is peer-to-peer while Wi-Fi is up: looking for the host over Wi-Fi");
    let stop: (() => void) | null = null;
    stop = this.radio.browse(this.phone, false, (results) => {
      if (this.session !== session || this.stopWifiBrowse !== stop) return;
      // Migration.sameTable: the salt names the table across re-advertising
      const same = (r: BrowseResult) => (salt !== null && !this.radio.opts.bugs.has("name") ? r.salt === salt : name === null || r.name === name);
      const seen = results.some((r) => same(r) && r.ifaces.includes("wifi"));
      if (!seen || !this.hostOverP2P || !this.wifiUp || this.migrationDone) return;
      this.migrationDone = true;
      this.stopWifiBrowse?.();
      this.stopWifiBrowse = null;
      this.log("moving the host link off peer-to-peer");
      this.drop("host");
    }, true);
    this.stopWifiBrowse = stop;
    this.radio.at(20, () => {
      if (this.stopWifiBrowse !== stop) return;
      this.stopWifiBrowse?.();
      this.stopWifiBrowse = null;
      if (this.radio.opts.bugs.has("migrate-once")) return;
      // Migration.lookAgainSeconds: look again while the link stays on AWDL
      this.radio.at(10, () => {
        if (this.session === session && this.links.get("host") === l) this.watchForWifiHost();
      });
    });
  }

  private checkNotFound(): void {
    if (this.links.has("host") || this.attempts.length || !this.stopBrowse) return;
    if (!this.appActive) return;
    const now = this.radio.vc.now();
    if (this.tries >= MAX_TRIES || (now >= this.findDeadline && this.candidates.length === 0)) {
      this.emitNotFound();
      return;
    }
    if (this.allTriedFailed()) {
      const session = this.session;
      const arrivals = this.candidateArrivals;
      const tries = this.tries;
      this.radio.at(ALL_FAILED_GRACE, () => {
        if (this.session === session && this.candidateArrivals === arrivals && this.tries === tries && this.allTriedFailed()) this.emitNotFound();
      });
    }
  }

  private allTriedFailed(): boolean {
    return this.tries > 0 && this.candidates.length === 0 && this.attempts.length === 0 && !this.links.has("host") && this.stopBrowse !== null;
  }

  private emitNotFound(): void {
    this.cancelBrowse();
    this.log("not found");
    this.emit("state", { state: "notFound" });
  }

  /** Back in the app during a join: the look's time starts over. */
  joinResumed(): void {
    if (!this.joinCode || !this.stopBrowse || this.links.has("host")) return;
    this.findDeadline = this.radio.vc.now() + this.lookTime;
    this.emit("state", { state: "waiting", detail: "active" });
    const session = this.session;
    this.radio.at(this.lookTime, () => { if (this.session === session) this.checkNotFound(); });
    this.tryNext();
  }

  // links

  /** `heard`: the other end or the network ended it (not this phone). */
  private drop(peer: string, heard = false): void {
    const l = this.links.get(peer);
    if (!l) return;
    this.links.delete(peer);
    this.log(`drop ${peer}`);
    if (l.link && !heard) this.radio.close(l.link, peer === "host");
    if (peer === "host") {
      this.stopWifiBrowse?.();
      this.stopWifiBrowse = null;
    }
    if (l.ready) this.emit("peer", { peer, state: "disconnected" });
  }

  /** The system ends every link of this phone at once (its app was
   *  suspended): this end knows, the other does not. */
  systemCutLinks(): void {
    for (const l of [...this.links.values()]) {
      if (l.link) this.radio.breakLink(l.link, l.peer !== "host", l.peer === "host");
    }
  }

  /** The joiner's link to the host, if up. */
  hostLink(): SimLink | null {
    return this.links.get("host")?.link ?? null;
  }

  private reset(): void {
    this.session += 1;
    if (this.listenerName) this.radio.unadvertise(this.listenerName);
    this.listenerName = null;
    this.listenerReady = false;
    this.cancelBrowse();
    for (const a of this.attempts) { a.done = true; a.cancel(); }
    this.attempts = [];
    for (const [peer, l] of this.links) {
      if (l.link) this.radio.close(l.link, peer === "host");
    }
    this.links.clear();
    this.candidates = [];
    this.tried = new Set();
    this.tries = 0;
    this.deviceIds.clear();
    this.joinCode = "";
    this.resuming = false;
    this.fellBack = false;
    this.fellBackUnseen = false;
    this.hostOverP2P = false;
    this.stopWifiBrowse?.();
    this.stopWifiBrowse = null;
    this.findDeadline = Infinity;
    this.candidateArrivals = 0;
    this.hostCode = "";
    this.needsReadvertise = false;
    this.backgroundedAt = null;
  }
}
