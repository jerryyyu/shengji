// One chaos game: a host phone and 1-3 joiner phones on the simulated radio
// (radio.ts), the real room (LocalServer), host boundary (NearbyHost),
// joiner socket (NearbySocket) and page-to-plugin bridge (native.ts), with a
// model of the joiner page's reconnect loop (ws.ts's Connection and
// codeJoin.ts's NearbyJoinStore for a seated joiner) and a player on every
// seat. Faults come from a schedule, so a failing game can be replayed and
// shrunk. The invariants are checked as the game runs.
import { VirtualClock } from "../../src/offline/server/clock";
import { LocalServer, type LocalRoom } from "../../src/offline/server/server";
import { LocalSocket } from "../../src/offline/server/socket";
import { NearbyHost } from "../../src/offline/server/nearby/host";
import { NearbySocket, setNearbyKeepalive } from "../../src/offline/server/nearby/socket";
import { pluginTransport } from "../../src/offline/server/nearby/native";
import type { NearbyTransport } from "../../src/offline/server/nearby/transport";
import { subscribeNearbyLog, nearbyLogLines, clearNearbyLog } from "../../src/nearbyLog";
import { SmartBot, viewFor } from "../../src/offline/bot";
import type { RoundState } from "../../src/offline/engine/round";
import { Radio, Rng, type Phone, type SimLink } from "./radio";
import { BACKOFF_FIRST_S, BACKOFF_MAX_S, CONNECT_S, LONG_LIVED_S, type PageModel } from "./pageModel";

type Frame = Record<string, unknown> & { type: string };

export type FaultKind = "wifi" | "radio" | "drop" | "halfOpen" | "stall" | "stallPhone" | "bg" | "listener" | "leave" | "allow" | "midjoin" | "dup";

export interface Fault {
  t: number;
  kind: FaultKind;
  /** Phone id: "H" or "J1".."J3". */
  who: string;
  dur: number;
  /** halfOpen: 1 = frames to the host lost; wifi: 1 = a new address. */
  arg: number;
}

export interface GameOpts {
  seed: number;
  bugs: string[];
  /** Explicit fault schedule (a replay); generated from the seed when absent. */
  schedule?: Fault[];
  /** Seconds of play with faults; then a quiet settle. */
  seconds: number;
  /** Seconds a joiner has to be back after the fault that last touched it. */
  bound: number;
  /** In-link duplicates (not something TCP does): safety invariants only. */
  hostile: boolean;
  verbose: boolean;
  /** The device test's faults too (stallPhone: a whole phone's frames held,
   *  host or joiner, two phones at once sometimes). Off, a seed makes the
   *  schedule it always made. */
  newFaults?: boolean;
  /** The joiner page's reconnect: "sim" (the simulator's own loop) or "ws"
   *  (ws.ts's connect timer and long-lived retry, pageModel.ts). */
  page?: PageModel;
}

export interface Violation {
  invariant: string;
  detail: string;
  t: number;
}

export interface GameResult {
  seed: number;
  violation: Violation | null;
  trace: string[];
  schedule: Fault[];
  stats: Record<string, number>;
  /** Seconds from each fault's clear to the joiner back, for the report. */
  recoveries: number[];
}

/** The joiner phones and when the session's people are on Wi-Fi. */
interface Setup {
  joiners: number;
  hostJoined: boolean;
  joinerJoined: boolean[];
  /** Which joiner (index) joins only once the game is on, if any. */
  late: number | null;
}

export function makeSetup(rng: Rng): Setup {
  const joiners = rng.int(1, 3);
  // a third of the sessions have no Wi-Fi network at all (peer-to-peer only)
  const noNet = rng.chance(0.3);
  // sometimes only the host has no Wi-Fi network (the joiners do)
  const hostJoined = !noNet && !rng.chance(0.1);
  const joinerJoined = Array.from({ length: joiners }, () => !noNet && rng.chance(0.85));
  const late = joiners >= 2 && rng.chance(0.3) ? joiners - 1 : null;
  return { joiners, hostJoined, joinerJoined, late };
}

export function makeSchedule(rng: Rng, setup: Setup, seconds: number, newFaults = false): Fault[] {
  const out: Fault[] = [];
  const joiners = Array.from({ length: setup.joiners }, (_, i) => `J${i + 1}`);
  const phones = ["H", ...joiners];
  let t = rng.range(20, 40);
  while (t < seconds - 20) {
    if (newFaults && rng.chance(0.2)) {
      // the device test's stall: one phone's frames, on every link, held
      const who = rng.pick(phones);
      const dur = rng.range(3, 12);
      out.push({ t, kind: "stallPhone", who, dur, arg: 0 });
      if (rng.chance(0.3)) {
        const other = rng.pick(phones.filter((p) => p !== who));
        out.push({ t: t + rng.range(0, dur), kind: "stallPhone", who: other, dur: rng.range(3, 12), arg: 0 });
      }
      t += rng.range(8, 45);
      continue;
    }
    const r = rng.next();
    const j = rng.pick(joiners);
    let f: Fault;
    if (r < 0.16) f = { t, kind: "wifi", who: rng.chance(0.25) ? "H" : j, dur: rng.range(2, 25), arg: rng.chance(0.5) ? 1 : 0 };
    else if (r < 0.24) f = { t, kind: "radio", who: j, dur: rng.range(2, 20), arg: 0 };
    else if (r < 0.38) f = { t, kind: "drop", who: j, dur: 0, arg: rng.int(0, 2) };
    else if (r < 0.48) f = { t, kind: "halfOpen", who: j, dur: 0, arg: rng.int(0, 1) };
    else if (r < 0.60) f = { t, kind: "stall", who: j, dur: rng.range(3, 12), arg: 0 };
    else if (r < 0.70) f = { t, kind: "bg", who: rng.chance(0.35) ? "H" : j, dur: rng.chance(0.08) ? rng.range(62, 80) : rng.range(2, 45), arg: 0 };
    else if (r < 0.76) f = { t, kind: "listener", who: "H", dur: 0, arg: 0 };
    else if (r < 0.86) f = { t, kind: "leave", who: j, dur: rng.range(3, 30), arg: 0 };
    else if (r < 0.93) f = { t, kind: "allow", who: "H", dur: rng.range(5, 40), arg: 0 };
    else f = { t, kind: "drop", who: j, dur: 0, arg: 0 };
    out.push(f);
    t += rng.range(8, 45);
  }
  if (setup.late !== null) out.push({ t: rng.range(40, Math.max(41, seconds / 2)), kind: "midjoin", who: `J${setup.late + 1}`, dur: 0, arg: 0 });
  return out.sort((a, b) => a.t - b.t);
}

interface Sent {
  text: string;
  key: string;
  seat: number;
  sock: number;
  at: number;
  state: "pending" | "applied" | "refused" | "moot" | "closed";
  /** The host has read it off a link. */
  arrived: boolean;
}

/** One phone's page and player. */
class Device {
  readonly id: string;
  readonly phone: Phone;
  readonly name: string;
  /** Faults that touch this phone now; the time the last one cleared. */
  activeFaults = 0;
  clearedAt = 0;
  /** The socket still read as open when this phone was first found not
   *  back: its link broke with no word to this end, which its ping finds. */
  openAtStart = false;
  /** Expected at the table (not left, not yet to join, table not over). */
  inPlay = false;
  /** Seat tokens this phone has been given. */
  readonly tokens = new Set<string>();
  readonly sent: Sent[] = [];
  readonly socketsAt: number[] = [];
  lastState: Frame | null = null;
  lastStateAt = 0;
  lastRoom: Frame | null = null;
  unhealthySince: number | null = null;
  constructor(id: string, phone: Phone, name: string) {
    this.id = id;
    this.phone = phone;
    this.name = name;
  }
}

/** The public part of a table frame, which every seat's copy shares. */
function summary(f: Frame | null): string {
  if (!f) return "none";
  if (f.type === "room") {
    const players = (f.players as { seat: number; name: string }[]).map((p) => `${p.seat}:${p.name}`).join(",");
    return `lobby|${players}`;
  }
  const trick = f.trick as { plays: unknown[] } | null;
  const last = f.last_trick as { plays: unknown[] } | null;
  return `${String(f.phase)}|${String(f.turn)}|${trick ? trick.plays.length : -1}|${last ? last.plays.length : -1}|${String(f.attacker_points)}|${(f.passed as number[]).join(",")}`;
}

/** Each round's number, by the round object. */
const roundNo = new WeakMap<RoundState, number>();
let roundsMade = 0;

/** A decision point in the live round, which a move is meant for. */
function pointOf(room: LocalRoom): string {
  const rnd = room.round;
  if (!rnd) return "none";
  let n = roundNo.get(rnd);
  if (n === undefined) roundNo.set(rnd, (n = ++roundsMade));
  const plays = rnd.history.reduce((k, tr) => k + tr.plays.length, 0) + (rnd.trick?.plays.length ?? 0);
  return `${n}|${rnd.phase}|${plays}`;
}

const sameCards = (a: string[], b: string[]) => [...a].sort().join(",") === [...b].sort().join(",");

/** The seat's move for a frame that matches the live round, as the fixtures'
 *  HumanDriver decides it; null when it owes none. */
function decide(bot: SmartBot, msg: Frame, rnd: RoundState, seat: number): Record<string, unknown> | null {
  const phase = msg.phase as string;
  const hand = msg.hand as { id: number; code: string }[];
  if (hand.length !== rnd.hands[seat].length || msg.phase !== rnd.phase || msg.turn !== rnd.turn) return null;
  const trick = msg.trick as { plays: unknown[] } | null;
  if ((trick ? trick.plays.length : 0) !== (rnd.trick ? rnd.trick.plays.length : 0)) return null;
  const ids = (codes: string[]) => {
    const pool = [...hand];
    return codes.map((code) => pool.splice(pool.findIndex((c) => c.code === code), 1)[0].id);
  };
  if (phase === "declare") {
    if ((msg.passed as number[]).includes(seat)) return null;
    const options = msg.declare_options as number[][];
    const cards = options.length ? bot.declare(viewFor(rnd, seat), true) : null;
    if (cards) {
      const byId = new Map(hand.map((c) => [c.id, c.code]));
      const opt = options.find((o) => sameCards(o.map((i) => byId.get(i)!), cards));
      if (opt) return { type: "declare", card_ids: opt };
    }
    return { type: "pass_declare" };
  }
  if (msg.turn !== seat) return null;
  if (phase === "bury") return { type: "bury", card_ids: ids(bot.bury(viewFor(rnd, seat))) };
  if (phase === "play") return { type: "play", card_ids: ids(bot.play(viewFor(rnd, seat))) };
  return null;
}

const PEEK = { type: "table_peek" };

export async function runGame(opts: GameOpts): Promise<GameResult> {
  const vc = new VirtualClock();
  const rng = new Rng(opts.seed);
  const setupRng = new Rng(opts.seed ^ 0x5eed);
  const driverRng = new Rng(opts.seed ^ 0xd21e);
  const bugs = new Set(opts.bugs);
  const trace: string[] = [];
  const stats: Record<string, number> = { faults: 0, links: 0, reconnects: 0, applied: 0, refused: 0, rounds: 0 };
  const recoveries: number[] = [];
  let violation: Violation | null = null;
  let current = "-";
  const log = (who: string, text: string) => {
    const line = `${vc.now().toFixed(3)} ${who} ${text}`;
    trace.push(line);
    if (trace.length > 4000) trace.splice(0, 1000);
    if (opts.verbose) console.log(line);
  };
  const fail = (invariant: string, detail: string) => {
    if (violation) return;
    violation = { invariant, detail, t: vc.now() };
    log("!!", `VIOLATION ${invariant}: ${detail}`);
  };

  // determinism: the room's tokens and codes come from the seed too
  const savedRandom = Math.random;
  const savedGetRandom = globalThis.crypto.getRandomValues.bind(globalThis.crypto);
  const cryptoRng = new Rng(opts.seed ^ 0xc0de);
  Math.random = () => cryptoRng.next();
  (globalThis.crypto as { getRandomValues: (a: Uint8Array) => Uint8Array }).getRandomValues = (a: Uint8Array) => {
    for (let i = 0; i < a.length; i++) a[i] = Math.floor(cryptoRng.next() * 256);
    return a;
  };
  clearNearbyLog();
  const offLog = subscribeNearbyLog(() => {
    const l = nearbyLogLines();
    const last = l[l.length - 1];
    if (last && !/^(out|in) (nearby_|state|room)|pong in|^keepalive/.test(last.text)) log(current, `js/${last.from}: ${last.text}`);
  });
  setNearbyKeepalive(!bugs.has("keepalive"));

  const radio = new Radio(vc, rng, { silentAfterIdle: [3, 5], bugs }, log);
  const setup = makeSetup(setupRng);
  const schedule = opts.schedule ?? makeSchedule(setupRng, setup, opts.seconds, opts.newFaults === true);

  /** A person's time to act: mostly quick, sometimes a long look. */
  const think = () => (driverRng.chance(0.25) ? driverRng.range(2, 12) : driverRng.range(0.5, 2));
  const H = radio.addPhone("H", setup.hostJoined);
  const hostDev = new Device("H", H, "Host");
  const devices: Device[] = [];
  for (let i = 0; i < setup.joiners; i++) {
    const p = radio.addPhone(`J${i + 1}`, setup.joinerJoined[i]);
    devices.push(new Device(p.id, p, `P${i + 1}`));
  }
  const all = [hostDev, ...devices];
  for (const d of all) {
    const post = d.phone.clock.post.bind(d.phone.clock);
    d.phone.clock.post = (fn) => post(() => {
      const was = current;
      current = d.id;
      try {
        fn();
      } finally {
        current = was;
      }
    });
  }
  log("sim", `seed ${opts.seed}: host ${setup.hostJoined ? "on Wi-Fi" : "no network"}, joiners ${devices.map((d, i) => `${d.id}:${setup.joinerJoined[i] ? "wifi" : "p2p"}`).join(" ")}${setup.late !== null ? `, J${setup.late + 1} joins late` : ""}; bugs [${[...bugs].join(",")}]`);

  // the host page: its room on its own clock, its seat on a LocalSocket
  const server = new LocalServer({ clock: H.clock, seed: () => opts.seed });
  const hostBot = new SmartBot();
  const hostSock = new LocalSocket(server);
  let room: LocalRoom | null = null;
  let nearbyHost: NearbyHost | null = null;
  let ended = false;
  let hostDecide: number | null = null;
  const hostAct = (msg: Record<string, unknown>) => hostSock.send(JSON.stringify(msg));
  hostSock.onmessage = (ev) => {
    const f = JSON.parse(ev.data as string) as Frame;
    if (f.type === "state") {
      hostDev.lastState = f;
      hostDev.lastStateAt = vc.now();
    }
    if (f.type === "room") hostDev.lastRoom = f;
    if (f.type !== "state") return;
    const gen = (hostDecide = (hostDecide ?? 0) + 1);
    H.clock.setTimeout(() => {
      if (gen !== hostDecide || !room?.round) return;
      const last = hostDev.lastState!;
      if (last.phase === "round_end") {
        if (!(last.ready as number[]).includes(last.you as number)) hostAct({ type: "next_round" });
        return;
      }
      const a = decide(hostBot, last, room.round, last.you as number);
      if (a) hostAct(a);
    }, think());
  };
  hostSock.onopen = () => hostSock.send(JSON.stringify({ type: "create_room", nearby: true, name: "Host" }));
  await vc.run(() => server.rooms.size > 0, 10_000);
  room = [...server.rooms.values()][0];
  const code = room.code;
  const hostTransport = pluginTransport(H.plugin, { owner: 0 });
  nearbyHost = new NearbyHost(server, room, {
    state: (s) => {
      if (s === "ended") {
        ended = true;
        log("H", "table ended (host away past its window)");
      }
    },
  });
  void nearbyHost.start(hostTransport).catch((e: unknown) => log("H", `host start failed: ${String(e)}`));

  // the host's boundary: which phone each message came from, and what the
  // room did with it
  H.plugin.onHostDeliver = (peer, text, run) => {
    const link = [...radio.history].reverse().find((l) => l.host === H && H.plugin.peerOf(l) === peer);
    const dev = link ? devices.find((d) => d.phone === link.joiner) : undefined;
    const r = room!;
    const before = r.actions.length;
    const point = pointOf(r);
    if (dev) {
      const s = dev.sent.find((x) => x.text === text && !x.arrived);
      if (s) s.arrived = true;
    }
    run();
    if (!dev) return;
    for (const a of r.actions.slice(before)) {
      if (a[0] !== "play" && a[0] !== "bury" && a[0] !== "declare" && a[0] !== "pass") continue;
      const seat = a[1] as number;
      // the latest move of this text: card ids repeat from round to round
      const s = [...dev.sent].reverse().find((x) => x.text === text);
      if (!s) {
        fail("attribution", `${dev.id}'s ${text.slice(0, 60)} applied a move it never sent`);
        continue;
      }
      if (s.state === "applied") fail("no double apply", `${dev.id}'s ${a[0]} for seat ${seat} applied twice`);
      if (s.key !== point) fail("no stale apply", `${dev.id}'s ${a[0]} meant for ${s.key} applied at ${point} (sent ${s.at.toFixed(2)} on socket ${s.sock})`);
      if (s.seat !== seat) fail("seat ownership", `${dev.id}'s move for seat ${s.seat} applied to seat ${seat}`);
      s.state = "applied";
      stats.applied += 1;
    }
  };

  // the joiner pages
  const wsPage = opts.page === "ws";
  class Page {
    readonly d: Device;
    readonly transport: NearbyTransport;
    sock: NearbySocket | null = null;
    sockNo = 0;
    status: "closed" | "connecting" | "open" = "closed";
    seated = false;
    token: string | null = null;
    /** The bound seat of the current socket, from its resume frame. */
    boundSeat: number | null = null;
    leaving = false;
    done = false;
    backoff = BACKOFF_FIRST_S;
    retry = 0;
    /** When the current socket opened (ws.ts's openedAt), for LONG_LIVED_S. */
    openedAt: number | null = null;
    misses = 0;
    decideGen = 0;
    readyOn = -1;
    bot = new SmartBot();
    unwatch: (() => void) | null = null;
    constructor(d: Device) {
      this.d = d;
      this.transport = pluginTransport(d.phone.plugin, { owner: 0 });
    }
    get clock() {
      return this.d.phone.clock;
    }
    look(): void {
      // a join by code replaces the page's socket, as Connection.useNearby's
      // cutSocket does: the old one closes with its handlers cut, so its
      // heartbeat cannot make links of its own
      this.retry += 1;
      const old = this.sock;
      this.sock = null;
      if (old) {
        old.onopen = null;
        old.onmessage = null;
        old.onclose = null;
        old.close();
      }
      this.done = false;
      this.leaving = false;
      this.seated = false;
      this.token = null;
      this.misses = 0;
      this.d.inPlay = true;
      if (!this.unwatch) {
        this.unwatch = this.transport.path?.((up) => {
          if (up && this.seated && this.status !== "open" && !this.leaving) {
            log(this.d.id, "page: network back, reconnect now");
            this.reconnectNow();
          }
        }) ?? null;
      }
      this.open();
    }
    private greet = (): Record<string, unknown> | null =>
      this.seated ? { type: "table_join", code, name: this.d.name, ...(this.token ? { token: this.token } : {}) } : null;
    open(): void {
      if (this.done) return;
      const no = ++this.sockNo;
      this.d.socketsAt.push(vc.now());
      stats.links += 1;
      this.status = "connecting";
      this.boundSeat = null;
      const sock = new NearbySocket(this.transport, code, (s) => this.onLinkState(no, s), this.clock, this.greet);
      this.sock = sock;
      this.openedAt = null;
      if (wsPage) {
        log(this.d.id, `page: attempt ${no}`);
        // ws.ts's connect timer: an attempt not open by now is cut, with its
        // handlers, and retried after the backoff
        this.clock.setTimeout(() => {
          if (this.sock !== sock || this.status !== "connecting") return;
          log(this.d.id, `page: attempt ${no} cut at ${CONNECT_S} s (still connecting)`);
          sock.onopen = null;
          sock.onmessage = null;
          sock.onclose = null;
          sock.close();
          this.sock = null;
          this.status = "closed";
          for (const s of this.d.sent) if (s.sock === no && s.state === "pending") s.state = "closed";
          this.retryLater(false);
        }, CONNECT_S);
      }
      sock.onopen = () => {
        if (this.sock !== sock) return;
        this.status = "open";
        this.openedAt = vc.now();
        this.backoff = BACKOFF_FIRST_S;
        this.misses = 0;
        if (!this.seated) sock.send(JSON.stringify({ ...PEEK, code }));
      };
      sock.onmessage = (ev) => {
        if (this.sock !== sock) return;
        this.onFrame(no, JSON.parse(ev.data as string) as Frame);
      };
      sock.onclose = () => {
        if (this.sock !== sock) return;
        this.status = "closed";
        this.sock = null;
        for (const s of this.d.sent) if (s.sock === no && s.state === "pending") s.state = "closed";
        if (this.leaving) {
          this.finishLeave();
          return;
        }
        if (this.done) return;
        this.retryLater(wsPage && this.openedAt !== null && vc.now() - this.openedAt > LONG_LIVED_S);
      };
    }
    /** The next attempt after the backoff (doubling to its cap), or at once. */
    private retryLater(now: boolean): void {
      const wait = now ? 0 : this.backoff;
      this.backoff = Math.min(this.backoff * 2, BACKOFF_MAX_S);
      const r = ++this.retry;
      this.clock.setTimeout(() => { if (r === this.retry && this.sock === null && !this.done) this.open(); }, wait);
    }
    reconnectNow(): void {
      this.retry += 1;
      const old = this.sock;
      this.sock = null;
      this.status = "closed";
      if (old) {
        old.onclose = null;
        old.close();
      }
      this.open();
    }
    onLinkState(no: number, s: string): void {
      if (no !== this.sockNo || this.seated) return;
      if (s === "notFound" || s === "failed") {
        // the store's one retry, then Try again after a moment
        this.misses += 1;
        if (this.misses >= 2) {
          log(this.d.id, "page: not found twice; the person taps Try again");
          this.misses = 0;
        }
      }
    }
    onFrame(no: number, f: Frame): void {
      const d = this.d;
      if (f.type === "resume") {
        this.token = f.token as string;
        d.tokens.add(this.token);
        const r = room!;
        const at = r.lobby ? r.lobby.findIndex((s) => s?.token === this.token) : r.seats.findIndex((s) => s.token === this.token);
        this.boundSeat = at >= 0 ? at : null;
        return;
      }
      if (f.type === "room_seats" && !this.seated) {
        if (f.full) {
          log(d.id, "page: table full");
          this.giveUp(true);
          return;
        }
        const taken = new Set((f.seats as { seat: number }[]).map((s) => s.seat));
        const open = [0, 1, 2, 3].filter((s) => !taken.has(s));
        const seat = open.length ? driverRng.pick(open) : null;
        this.clock.setTimeout(() => {
          if (this.sock && this.status === "open" && !this.seated) this.sock.send(JSON.stringify({ type: "table_join", code, name: d.name, seat }));
        }, driverRng.range(0.3, 1.2));
        return;
      }
      if (f.type === "error") {
        for (const s of d.sent) if (s.sock === no && s.state === "pending") s.state = "refused";
        stats.refused += 1;
        if (f.code === "room_full" && !this.seated) this.giveUp(true);
        return;
      }
      if (f.type === "left") {
        if (f.reason === "host_left") this.giveUp(false);
        return;
      }
      if (f.type !== "room" && f.type !== "state") return;
      this.seated = true;
      if (typeof f.you === "number" && this.boundSeat !== null && f.you !== this.boundSeat) {
        fail("no hidden cards", `${d.id}'s socket ${no} bound to seat ${this.boundSeat} got a frame for seat ${String(f.you)}`);
      }
      if (f.type === "room") {
        d.lastRoom = f;
        d.lastState = null;
        if (this.readyOn !== no) {
          this.readyOn = no;
          this.clock.setTimeout(() => { if (this.sock && this.status === "open" && room?.lobby) this.sock.send(JSON.stringify({ type: "table_start" })); }, driverRng.range(0.5, 2));
        }
        return;
      }
      d.lastState = f;
      d.lastStateAt = vc.now();
      this.checkHand(f);
      const seat = f.you as number;
      // a frame showing the decision a pending move was for has passed
      const r = room!;
      const point = pointOf(r);
      for (const s of d.sent) if (s.state === "pending" && s.key !== point) s.state = "moot";
      const gen = ++this.decideGen;
      this.clock.setTimeout(() => this.act(gen, no, seat), think());
    }
    checkHand(f: Frame): void {
      const r = room!;
      const rnd = r.round;
      if (!rnd || f.phase !== rnd.phase) return;
      const seat = f.you as number;
      const may: string[] = [...rnd.hands[seat]];
      for (const tr of [...rnd.history, ...(rnd.trick ? [rnd.trick] : [])]) for (const p of tr.plays) if (p.seat === seat) may.push(...p.cards);
      if (rnd.banker === seat) may.push(...rnd.kitty, ...rnd.buried);
      for (const c of f.hand as { code: string }[]) {
        const k = may.indexOf(c.code);
        if (k < 0) {
          fail("no hidden cards", `${this.d.id} (seat ${seat}) was shown ${c.code}, which seat ${seat} never held`);
          return;
        }
        may.splice(k, 1);
      }
    }
    act(gen: number, no: number, seat: number): void {
      if (gen !== this.decideGen || no !== this.sockNo || this.status !== "open" || !this.sock || this.leaving) return;
      const f = this.d.lastState;
      const r = room!;
      if (!f || !r.round) return;
      const me = (f.players as { seat: number; controller: string }[] | undefined)?.find((p) => p.seat === seat);
      if (me && me.controller !== "human" && r.seats[seat] && !r.seats[seat].isBot) this.send({ type: "im_back" }, seat, "none");
      if (f.phase === "round_end") {
        if (!(f.ready as number[]).includes(seat)) this.send({ type: "next_round" }, seat, "none");
        return;
      }
      const a = decide(this.bot, f, r.round, seat);
      if (!a) return;
      const point = pointOf(r);
      // one tap per decision on a link; a new link's fresh state is a new chance
      if (this.d.sent.some((s) => s.key === point && s.sock === no && s.seat === seat)) return;
      this.send(a, seat, point);
    }
    send(msg: Record<string, unknown>, seat: number, key: string): void {
      const text = NearbySocket.outbound(JSON.stringify(msg));
      if (!text || !this.sock) return;
      if (key !== "none") this.d.sent.push({ text, key, seat, sock: this.sockNo, at: vc.now(), state: "pending", arrived: false });
      this.sock.send(JSON.stringify(msg));
      if (opts.hostile && driverRng.chance(0.05)) {
        const link = this.d.phone.plugin.hostLink();
        if (link) radio.send(link, true, text);
      }
    }
    leave(): void {
      if (!this.seated || !this.sock || this.status !== "open") return;
      log(this.d.id, "page: Leave");
      this.leaving = true;
      this.d.inPlay = false;
      this.sock.send(JSON.stringify({ type: "table_leave" }));
      const sock = this.sock;
      this.clock.setTimeout(() => { if (this.sock === sock && this.leaving) this.finishLeave(); }, 3);
    }
    finishLeave(): void {
      this.leaving = false;
      this.done = true;
      this.seated = false;
      this.token = null;
      const s = this.sock;
      this.sock = null;
      this.status = "closed";
      if (s) {
        s.onclose = null;
        s.close();
      }
    }
    giveUp(full: boolean): void {
      log(this.d.id, `page: gives up (${full ? "table full" : "host left"})`);
      this.done = true;
      this.d.inPlay = false;
      const s = this.sock;
      this.sock = null;
      this.status = "closed";
      if (s) {
        s.onclose = null;
        s.close();
      }
    }
  }

  const pages = new Map<Device, Page>();
  for (const d of devices) pages.set(d, new Page(d));
  const firsts = devices.filter((_, i) => i !== setup.late);
  for (const [k, d] of firsts.entries()) vc.setTimeout(() => d.phone.clock.post(() => pages.get(d)!.look()), 1 + k * 1.5);

  // the host starts once its first joiners are seated (or after a while)
  const startBy = 60;
  // people talk in the lobby a while before the host starts
  const lobbyWait = driverRng.range(3, 30);
  let seatedAt: number | null = null;
  const tryStart = () => {
    const r = room!;
    if (!r.lobby) return;
    const seated = firsts.every((d) => pages.get(d)!.seated);
    if (seated && seatedAt === null) seatedAt = vc.now();
    if ((seatedAt !== null && vc.now() - seatedAt >= lobbyWait) || vc.now() > startBy) {
      log("H", "host: Start");
      hostAct({ type: "table_start" });
      if (vc.now() > startBy) hostAct({ type: "table_start_bots" });
      return;
    }
    vc.setTimeout(tryStart, 1);
  };
  vc.setTimeout(tryStart, 5);

  // faults
  // a fault that can leave a link one end never hears of: the joiner's
  // socket finds it by its ping (every 5 s) going unanswered (4 s, 8 s over
  // AWDL), then makes a new link
  const DETECT = 5 + 8 + 2;
  const touch = (d: Device, on: boolean, _quiet = false) => {
    if (on) {
      d.activeFaults += 1;
    } else {
      d.activeFaults -= 1;
      d.clearedAt = vc.now();
    }
  };
  const dev = (who: string) => all.find((d) => d.id === who)!;
  let lastFaultAt = 0;
  const begin = (d: Device, dur: number, end: () => void, quiet = false) => {
    touch(d, true, quiet);
    lastFaultAt = vc.now();
    vc.setTimeout(() => {
      end();
      touch(d, false);
      lastFaultAt = vc.now();
    }, dur);
  };
  const hostLink = (d: Device): SimLink | null => d.phone.plugin.hostLink();
  for (const f of schedule) {
    vc.setTimeout(() => {
      if (ended) return;
      const d = dev(f.who);
      if (!d) return;
      stats.faults += 1;
      lastFaultAt = vc.now();
      log("fault", `${f.kind} ${f.who}${f.dur ? ` for ${f.dur.toFixed(1)} s` : ""}${f.arg ? ` (${f.arg})` : ""}`);
      switch (f.kind) {
        case "wifi": {
          if (!d.phone.joined) return;
          radio.setNet(d.phone, { joined: false });
          begin(d, f.dur, () => radio.setNet(d.phone, { joined: true, newAddress: f.arg === 1 }), true);
          return;
        }
        case "radio": {
          const was = d.phone.joined;
          radio.setNet(d.phone, { radio: false, joined: false });
          begin(d, f.dur, () => radio.setNet(d.phone, { radio: true, joined: was, newAddress: false }), true);
          return;
        }
        case "drop": {
          const l = hostLink(d);
          if (!l) return;
          touch(d, true, f.arg === 2);
          // 0: both ends hear it; 1: only the joiner does; 2: only the host
          radio.breakLink(l, f.arg === 2, f.arg === 1);
          touch(d, false);
          return;
        }
        case "halfOpen": {
          const l = hostLink(d);
          if (!l) return;
          touch(d, true, true);
          radio.halfOpen(l, f.arg === 1);
          touch(d, false);
          return;
        }
        case "stall": {
          const l = hostLink(d);
          if (!l) return;
          radio.stall(l);
          begin(d, f.dur, () => radio.unstall(l), true);
          return;
        }
        case "stallPhone": {
          const p = d.phone.plugin;
          if (!p.stallStart()) return;
          begin(d, f.dur, () => p.stallEnd(), true);
          return;
        }
        case "bg": {
          const p = d.phone;
          p.clock.suspend();
          p.plugin.appActive = false;
          if (d === hostDev) p.plugin.hostLeft();
          // the system suspends the app a little later: its links and (on
          // the host) its listener go
          const cut = d === hostDev ? driverRng.range(5, 30) : driverRng.range(0, 10);
          let back = false;
          vc.setTimeout(() => {
            if (back) return;
            p.plugin.systemCutLinks();
            if (d === hostDev) p.plugin.listenerLost();
          }, cut);
          begin(d, f.dur, () => {
            back = true;
            p.plugin.appActive = true;
            if (d === hostDev) p.plugin.hostReturned();
            else p.plugin.joinResumed();
            p.clock.resume();
          }, d === hostDev);
          return;
        }
        case "listener": {
          touch(d, true);
          d.phone.plugin.listenerLost();
          touch(d, false);
          return;
        }
        case "leave": {
          const pg = pages.get(d);
          if (!pg || !pg.seated) return;
          d.phone.clock.post(() => pg.leave());
          touch(d, true);
          vc.setTimeout(() => {
            touch(d, false);
            d.phone.clock.post(() => { log(d.id, "page: rejoins by code"); pg.look(); });
          }, Math.max(4, f.dur));
          return;
        }
        case "allow": {
          if (room?.lobby) return;
          hostAct({ type: "table_allow_joiners", on: false });
          begin(hostDev, f.dur, () => hostAct({ type: "table_allow_joiners", on: true }));
          return;
        }
        case "midjoin": {
          const pg = pages.get(d);
          if (pg && !pg.d.inPlay) d.phone.clock.post(() => pg.look());
          touch(d, true);
          touch(d, false);
          return;
        }
        default:
          return;
      }
    }, f.t);
  }

  // the invariants that are checked over time
  const quiet = () => all.every((d) => d.activeFaults === 0);
  let roundsSeen = 0;
  let lastPhase = "";
  const check = () => {
    if (violation) return;
    const r = room!;
    const now = vc.now();
    if (r.round && r.round.phase !== lastPhase) {
      if (r.round.phase === "round_end") roundsSeen += 1;
      lastPhase = r.round.phase;
    }
    stats.rounds = roundsSeen;
    if (ended || r.closed) return;
    const hostOk = hostDev.activeFaults === 0 && !H.clock.suspended;
    for (const d of devices) {
      const pg = pages.get(d)!;
      // each phone at most one seat
      const held = r.seats.filter((s) => !s.isBot && s.connected && d.tokens.has(s.token)).length;
      if (held > 1) fail("one seat per phone", `${d.id} holds ${held} connected seats`);
      // every move sent is applied, refused, or its link ends
      for (const s of d.sent) {
        // (the page's JS runs to find a dead link: not while it is suspended)
        if (s.state === "pending" && now - Math.max(s.at, d.clearedAt) > 30 && d.activeFaults === 0 && pg.status === "open" && pg.sockNo === s.sock) {
          fail("every move answered", `${d.id}'s ${s.text.slice(0, 40)} (for ${s.key}) unanswered ${Math.round(now - s.at)} s on a link still open${s.arrived ? " (it reached the host)" : " (never reached the host)"}`);
        }
      }
      // back and playable within the bound once the faults that touched it clear
      const expect = d.inPlay && !pg.done && !pg.leaving && d.activeFaults === 0 && hostOk && pg.token !== null;
      const since = Math.max(d.clearedAt, hostDev.clearedAt);
      const seatIdx = pg.token === null ? -1 : (r.lobby ? r.lobby.findIndex((s) => s?.token === pg.token) : r.seats.findIndex((s) => s.token === pg.token));
      const seatOk = seatIdx >= 0 && (r.lobby ? r.lobby[seatIdx]!.connected : r.seats[seatIdx].connected);
      const fresh = r.lobby ? true : summary(d.lastState) === summary(hostDev.lastState) || now - hostDev.lastStateAt < 2.5;
      const healthy = pg.status === "open" && seatOk && fresh;
      if (expect && !healthy) {
        if (d.unhealthySince === null) {
          d.unhealthySince = now;
          d.openAtStart = pg.status === "open";
        }
        const from = Math.max(since, d.unhealthySince);
        const bound = opts.bound + (d.openAtStart ? DETECT : 0);
        if (now - from > bound) {
          fail("back within the bound", `${d.id} not back ${Math.round(now - from)} s after the last fault cleared (socket ${pg.status}, seat ${seatIdx >= 0 ? `${seatIdx} ${seatOk ? "connected" : "not connected"}` : "none"}, state ${fresh ? "current" : "behind"})`);
        }
      } else if (healthy && d.unhealthySince !== null) {
        if (d.unhealthySince >= since - 0.01 || since > 0) recoveries.push(now - Math.max(since, d.unhealthySince));
        d.unhealthySince = null;
      } else if (!expect) d.unhealthySince = null;
      // no reconnect loop: at most 3 new links a minute with no fault about
      const recent = d.socketsAt.filter((t) => now - t < 60).length;
      if (recent > 3 && now - lastFaultAt > 60 && quiet()) fail("no reconnect loop", `${d.id} made ${recent} links in the last minute with no fault`);
      // on Wi-Fi with the host on Wi-Fi, the link is not left on AWDL
      const l = d.phone.plugin.hostLink();
      if (l && l.iface === "awdl" && d.phone.joined && H.joined) {
        const age = now - Math.max(d.clearedAt, hostDev.clearedAt, linkBorn.get(l) ?? now);
        if (age > 45) fail("Wi-Fi link while on Wi-Fi", `${d.id}'s link ${l.id} has stayed on AWDL ${Math.round(age)} s with both phones on Wi-Fi`);
      }
    }
    // a seat is any one phone's
    for (let s = 0; s < 4; s++) {
      const owners = devices.filter((d) => {
        const pg = pages.get(d)!;
        return pg.status === "open" && pg.boundSeat === s && d.lastState !== null && now - d.lastStateAt < 2 && d.lastState.you === s;
      });
      if (owners.length > 1) fail("one phone per seat", `seat ${s} live on ${owners.map((d) => d.id).join(" and ")}`);
    }
  };
  const linkBorn = new Map<SimLink, number>();
  const watch = () => {
    for (const l of radio.history.slice(-8)) if (!linkBorn.has(l)) linkBorn.set(l, vc.now());
    check();
    if (!violation) vc.setTimeout(watch, 0.5);
  };
  vc.setTimeout(watch, 0.5);

  // the settle starts once the last fault has cleared
  const endAt = Math.max(opts.seconds, ...schedule.map((f) => f.t + f.dur)) + 45;
  try {
    await vc.run(() => violation !== null || vc.now() >= endAt, 5_000_000);
  } catch (e) {
    fail("simulator", String(e));
  }

  // the settle: every phone still at the table agrees with the host's view
  if (!violation && !ended && !room.closed) {
    for (const d of devices) {
      const pg = pages.get(d)!;
      if (!d.inPlay || pg.done || !room.round || d.activeFaults > 0) continue;
      if (room.lobby) continue;
      if (summary(d.lastState) !== summary(hostDev.lastState) && vc.now() - hostDev.lastStateAt > 3) {
        fail("same state after the settle", `${d.id} shows ${summary(d.lastState)}, the host ${summary(hostDev.lastState)}`);
      }
    }
  }

  for (const d of devices) {
    stats.reconnects += Math.max(0, d.socketsAt.length - 1);
    pages.get(d)!.unwatch?.();
  }
  stats.hostRefused = Object.values(nearbyHost.refused).reduce((a, b) => a + b, 0);
  offLog();
  Math.random = savedRandom;
  (globalThis.crypto as unknown as { getRandomValues: typeof savedGetRandom }).getRandomValues = savedGetRandom;
  setNearbyKeepalive(true);
  return { seed: opts.seed, violation, trace, schedule, stats, recoveries };
}
