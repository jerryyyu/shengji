// One chaos game: a host phone and 1-3 joiner phones on the simulated radio
// (radio.ts), the real room (LocalServer), host boundary (NearbyHost),
// joiner socket (NearbySocket) and page-to-plugin bridge (native.ts), with a
// model of the joiner page's reconnect loop (ws.ts's Connection and
// codeJoin.ts's NearbyJoinStore for a seated joiner) and a player on every
// seat. Faults come from a schedule, so a failing game can be replayed and
// shrunk. The invariants are checked as the game runs.
import { VirtualClock } from "../../src/offline/server/clock";
import { LocalServer, type LocalRoom, type Seat } from "../../src/offline/server/server";
import { LocalSocket } from "../../src/offline/server/socket";
import { NearbyHost } from "../../src/offline/server/nearby/host";
import { NearbySocket, SEAT_GONE, setNearbyKeepalive } from "../../src/offline/server/nearby/socket";
import { pluginTransport } from "../../src/offline/server/nearby/native";
import type { NearbyTransport } from "../../src/offline/server/nearby/transport";
import { subscribeNearbyLog, nearbyLogLines, clearNearbyLog } from "../../src/nearbyLog";
import { SmartBot, viewFor } from "../../src/offline/bot";
import type { RoundState } from "../../src/offline/engine/round";
import { Radio, Rng, type Phone, type SimLink } from "./radio";
import { HOST_WINDOW_S, JOIN_TIMEOUT_S, KeptToken, LONG_LIVED_S, NEARBY_RETRY_S, type PageModel } from "./pageModel";
import { frameTriggers, TRIGGER_PHASES, type TriggerPhase } from "../../src/nearbySoakChaos";

type Frame = Record<string, unknown> & { type: string };

export type FaultKind = "wifi" | "radio" | "drop" | "halfOpen" | "stall" | "stallPhone" | "bg" | "listener" | "leave" | "allow" | "midjoin" | "dup"
  | "storm" | "jsFreeze" | "loss" | "joinReplyLost" | "leaveOffline" | "kill" | "botSlow";

/** The whole-app faults (--whole-app):
 *  - storm: every ready link of the host broken at once, both ends told;
 *  - jsFreeze: one phone's JS stopped `dur` s (its links up), then its
 *    timers dealt in among its events at random;
 *  - loss: the next `arg % 10` frames of LOSS_TYPES[floor(arg / 10) % 10]
 *    on a joiner's host link lost, toward the host when arg >= 100;
 *  - joinReplyLost: the host's next resume frame to a joiner lost;
 *  - leaveOffline: a joiner's Leave with its link down (the radio off `dur` s);
 *  - kill: a joiner's app killed, and relaunched `dur` s later with its
 *    kept seat token;
 *  - botSlow: for `dur` s, the host's JS blocked 0-6 s on each bot turn. */
export const LOSS_TYPES = ["state", "resume", "room", "ping", "pong", "play", "declare", "nearby_hello", "pass_declare", ""] as const;

export interface Fault {
  t: number;
  kind: FaultKind;
  /** Phone id: "H" or "J1".."J3". */
  who: string;
  dur: number;
  /** halfOpen: 1 = frames to the host lost; wifi: 1 = a new address. */
  arg: number;
  /** Phase-targeted: the fault runs at the first `phase` after `t`, `offset`
   *  s later (nearbySoakChaos.ts TRIGGER_PHASES). */
  phase?: TriggerPhase;
  offset?: number;
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
   *  (ws.ts's nearby retry waits and long-lived retry, pageModel.ts). */
  page?: PageModel;
  /** The known gaps the app has yet to close, checked as they happen:
   *  "report" counts each in the stats (gap ...) and never fails a game,
   *  "strict" fails it; off (the default) skips them. S3: a reconnect under
   *  3 s adds no chat line. S4: a move pending at a rebuild is applied or
   *  sent again within 1 s of the resume. */
  gaps?: "off" | "report" | "strict";
  /** With "strict": fail only on the gap whose name contains this. */
  gapOnly?: string;
  /** The whole app: the joiner pages' personas (slow, double-tap,
   *  stale-tap, leaver, declarer; the latecomer is the setup's), their
   *  host-left window, the whole-app faults and invariants. */
  wholeApp?: boolean;
  /** Each fault aimed at a phase (TRIGGER_PHASES), run at its first
   *  occurrence after the fault's time. */
  phaseTargeted?: boolean;
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
  /** Seconds from the last frame a joiner heard before an outage to its
   *  being back: the freeze the person sees, fault time included. */
  freezes: number[];
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

/** One whole-app fault at `t`. */
function wholeAppFault(rng: Rng, t: number, phones: string[], joiners: string[]): Fault {
  const r = rng.next();
  const j = rng.pick(joiners);
  if (r < 0.14) return { t, kind: "storm", who: "H", dur: 0, arg: 0 };
  if (r < 0.32) return { t, kind: "jsFreeze", who: rng.pick(phones), dur: rng.chance(0.05) ? rng.range(30, 50) : rng.range(2, 15), arg: 0 };
  if (r < 0.50) return { t, kind: "loss", who: j, dur: 0, arg: rng.int(1, 5) + 10 * rng.int(0, LOSS_TYPES.length - 1) + (rng.chance(0.5) ? 100 : 0) };
  if (r < 0.60) return { t, kind: "joinReplyLost", who: j, dur: 0, arg: 0 };
  if (r < 0.72) return { t, kind: "leaveOffline", who: j, dur: rng.range(3, 30), arg: 0 };
  if (r < 0.86) return { t, kind: "kill", who: j, dur: rng.range(2, 30), arg: 0 };
  return { t, kind: "botSlow", who: "H", dur: rng.range(20, 60), arg: 0 };
}

export function makeSchedule(rng: Rng, setup: Setup, seconds: number, newFaults = false, wholeApp = false, phaseTargeted = false): Fault[] {
  const out: Fault[] = [];
  const joiners = Array.from({ length: setup.joiners }, (_, i) => `J${i + 1}`);
  const phones = ["H", ...joiners];
  let t = rng.range(20, 40);
  while (t < seconds - 20) {
    if (wholeApp && rng.chance(0.4)) {
      out.push(wholeAppFault(rng, t, phones, joiners));
      t += rng.range(8, 45);
      continue;
    }
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
  if (phaseTargeted) {
    // each fault waits for a phase; the lobby and the game's start come
    // early, so faults aimed there are armed from the first second
    for (const f of out) {
      f.phase = rng.pick([...TRIGGER_PHASES]);
      f.offset = f.phase === "after_move" ? rng.range(0, 0.3) : rng.range(0, 2);
      if (f.phase === "lobby" || f.phase === "start" || f.phase === "join_handshake") f.t = rng.range(0, 5);
    }
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
  /** The last frame of any kind (a pong included) this phone heard from the
   *  host, at its plugin. */
  lastFrameAt = 0;
  /** That time when the current outage began. */
  frozenFrom = 0;
  unhealthySince: number | null = null;
  /** When a loss fault last armed on this phone's link. */
  lossAt = -1e9;
  /** Trips to the background under way. */
  bg = 0;
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

/** A simulated joiner's persona (--whole-app). */
type Persona = "pacer" | "slow" | "doubleTap" | "staleTap" | "leaver";

const frameTypeOf = (text: string): string => /^\{"type":"([a-z_]+)"/.exec(text)?.[1] ?? "?";

export async function runGame(opts: GameOpts): Promise<GameResult> {
  const vc = new VirtualClock();
  const rng = new Rng(opts.seed);
  const setupRng = new Rng(opts.seed ^ 0x5eed);
  const driverRng = new Rng(opts.seed ^ 0xd21e);
  const bugs = new Set(opts.bugs);
  const trace: string[] = [];
  const stats: Record<string, number> = { faults: 0, links: 0, reconnects: 0, applied: 0, refused: 0, rounds: 0 };
  const recoveries: number[] = [];
  const freezes: number[] = [];
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
  const gapMode = opts.gaps ?? "off";
  const gap = (invariant: string, detail: string) => {
    stats[`gap ${invariant}`] = (stats[`gap ${invariant}`] ?? 0) + 1;
    log("gap", `${invariant}: ${detail}`);
    if (gapMode === "strict" && (!opts.gapOnly || invariant.includes(opts.gapOnly))) fail(invariant, detail);
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
  const wholeApp = opts.wholeApp === true;
  const schedule = opts.schedule ?? makeSchedule(setupRng, setup, opts.seconds, opts.newFaults === true, wholeApp, opts.phaseTargeted === true);
  const appRng = new Rng(opts.seed ^ 0xa11a);

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
  radio.onLoss = (l) => {
    const d = devices.find((x) => x.phone === l.joiner);
    if (d) d.lossAt = vc.now();
  };
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
  if (gapMode !== "off") {
    // S3: the room's chat lines, and each seat's outage as the room sees it
    const chatAt: { t: number; text: string }[] = [];
    const chatSystem = server.chatSystem.bind(server);
    server.chatSystem = (r, text) => {
      chatAt.push({ t: vc.now(), text });
      chatSystem(r, text);
    };
    const downAt = new Map<Seat, number>();
    const seen = new Set<Seat>();
    const detach = server.detach.bind(server);
    server.detach = (seat, r, gen) => {
      if ((gen === null || gen === seat.gen) && !downAt.has(seat)) downAt.set(seat, vc.now());
      detach(seat, r, gen);
    };
    const attach = server.attach.bind(server);
    server.attach = (r, seat, writer) => {
      const now = vc.now();
      const from = downAt.get(seat) ?? now;
      downAt.delete(seat);
      const again = seen.has(seat);
      seen.add(seat);
      const gen = attach(r, seat, writer);
      if (again && now - from < 3) {
        vc.setTimeout(() => {
          const lines = chatAt.filter((c) => c.t >= from && c.t <= now + 1 && c.text.includes(seat.name));
          if (lines.length) gap("quick reconnect adds no chat", `${seat.name} back in ${(now - from).toFixed(1)} s; chat: ${lines.map((c) => `"${c.text}"`).join(", ")}`);
        }, 1);
      }
      return gen;
    };
  }
  const hostBot = new SmartBot();
  const hostSock = new LocalSocket(server);
  let room: LocalRoom | null = null;
  let nearbyHost: NearbyHost | null = null;
  let ended = false;
  let endedAt: number | null = null;
  /** When the host's table was over for its joiners: its end, or 60 s
   *  (the plugin's host window) into an away that outlasts it. */
  const hostGoneAt = (): number | null => {
    if (endedAt !== null) return endedAt;
    const away = H.plugin.backgroundedAt;
    return away !== null && vc.now() - away > 60 ? away + 60 : null;
  };
  let hostDecide: number | null = null;
  const hostAct = (msg: Record<string, unknown>) => hostSock.send(JSON.stringify(msg));
  // phase-targeted faults wait here for their phase (nearbySoakChaos.ts's
  // triggers, read off the host's own frames and the host's boundary)
  const armed: Fault[] = [];
  let runFault: (f: Fault) => void = () => {};
  const phaseRng = new Rng(opts.seed ^ 0xfa5e);
  let dealCard = phaseRng.int(1, 25);
  let prevHostFrame: Frame | null = null;
  const emitPhase = (ph: TriggerPhase) => {
    stats[`phase ${ph} seen`] = (stats[`phase ${ph} seen`] ?? 0) + 1;
    for (let i = armed.length - 1; i >= 0; i--) {
      const f = armed[i];
      if (f.phase !== ph) continue;
      armed.splice(i, 1);
      vc.setTimeout(() => {
        stats[`phase ${ph}`] = (stats[`phase ${ph}`] ?? 0) + 1;
        runFault(f);
      }, f.offset ?? 0);
    }
  };
  hostSock.onmessage = (ev) => {
    const f = JSON.parse(ev.data as string) as Frame;
    if (f.type === "room" || f.type === "state") {
      const was = prevHostFrame;
      prevHostFrame = f;
      for (const ph of frameTriggers(was, f, dealCard)) emitPhase(ph);
      // the lobby lasts: each lobby frame is the lobby; a bury is the
      // banker's, whoever it is
      if (f.type === "room" && was?.type === "room") emitPhase("lobby");
      if (f.type === "state" && f.phase === "bury" && (was?.type !== "state" || was.phase !== "bury") && f.turn !== f.you) emitPhase("own_bury");
      if (f.type === "state" && f.phase === "round_end" && was?.type === "state" && was.phase !== "round_end") dealCard = phaseRng.int(1, 25);
    }
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
        endedAt = vc.now();
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
    if (text.startsWith('{"type":"nearby_hello"') && !text.includes('"peek":true')) emitPhase("join_handshake");
    run();
    if (r.actions.length > before && dev) emitPhase("after_move");
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
      // a call made while dealing stands in the declare window too: one point
      const calling = (k: string) => k.replace(/\|(deal|declare)\|0$/, "|calling|0");
      const samePoint = s.key === point || (wholeApp && a[0] === "declare" && calling(s.key) === calling(point));
      if (!samePoint) fail("no stale apply", `${dev.id}'s ${a[0]} meant for ${s.key} applied at ${point} (sent ${s.at.toFixed(2)} on socket ${s.sock})`);
      if (s.seat !== seat) fail("seat ownership", `${dev.id}'s move for seat ${s.seat} applied to seat ${seat}`);
      s.state = "applied";
      stats.applied += 1;
    }
  };

  // the joiner pages
  const wsPage = opts.page === "ws";
  /** The "sim" page's own backoff: from SIM_BACKOFF_FIRST_S, doubling to SIM_BACKOFF_MAX_S. */
  const SIM_BACKOFF_FIRST_S = 0.5;
  const SIM_BACKOFF_MAX_S = 2;
  const pendingChecked = new Set<Sent>();
  /** Each token's seat index, from its resumes. */
  const tokenSeat = new Map<string, number>();
  /** Each Leave in play: its seat must have the bot's cover soon after. */
  const leaves: { d: Device; token: string; at: number; offline: boolean; back: number }[] = [];
  /** The tokens of seats left with the link down. */
  const offlineLeft = new Set<string>();
  const offlineLeftSeen = new Set<Device>();
  class Page {
    readonly d: Device;
    readonly transport: NearbyTransport;
    sock: NearbySocket | null = null;
    sockNo = 0;
    status: "closed" | "connecting" | "open" = "closed";
    seated = false;
    token: string | null = null;
    /** The seat token kept on the phone by the table's code (pageModel.ts). */
    readonly kept = new KeptToken();
    /** nearbyJoin.ts claiming: that claim is out on its own link, the
     *  resume by the kept token as its hello. */
    claiming = false;
    /** Bumped at each claim and its end, so only the latest timer acts. */
    claimRun = 0;
    /** The bound seat of the current socket, from its resume frame. */
    boundSeat: number | null = null;
    leaving = false;
    done = false;
    backoff = SIM_BACKOFF_FIRST_S;
    /** ws.ts's nearbyTries: retries since the last open, into NEARBY_RETRY_S. */
    tries = 0;
    retry = 0;
    /** When the current socket opened (ws.ts's openedAt), for LONG_LIVED_S. */
    openedAt: number | null = null;
    misses = 0;
    decideGen = 0;
    readyOn = -1;
    bot = new SmartBot();
    unwatch: (() => void) | null = null;
    /** The whole app's persona for this page (pacer without --whole-app). */
    persona: Persona = "pacer";
    /** The host-left window's run (nearbyJoin.ts HOST_WINDOW_MS). */
    goneRun = 0;
    /** The window runs from the first drop, not from each retry's. */
    goneArmed = false;
    /** Killed: no page until its relaunch. */
    killed = false;
    /** The last move this page sent and its decision point, for a stale tap. */
    lastMove: Sent | null = null;
    /** Per socket: the last state's phase rank and cards left, the gens seen. */
    prog: { no: number; rank: number; left: number; phase: string } | null = null;
    lastGen = -1;
    constructor(d: Device) {
      this.d = d;
      this.transport = pluginTransport(d.phone.plugin, { owner: 0 });
      if (wholeApp) {
        const r = appRng.next();
        this.persona = r < 0.15 ? "slow" : r < 0.3 ? "doubleTap" : r < 0.4 ? "staleTap" : r < 0.5 ? "leaver" : "pacer";
        stats[`persona ${this.persona}`] = (stats[`persona ${this.persona}`] ?? 0) + 1;
      }
    }
    /** This page's time to act. A slow player takes 55-59 s, past the 60 s
     *  move clock one time in five. */
    think(): number {
      if (this.persona === "slow") return appRng.chance(0.2) ? appRng.range(60, 66) : appRng.range(55, 59);
      return think();
    }
    /** The host-left window: a seated page with no open link for 65 s shows
     *  the end screen (nearbyJoin.ts). */
    private armGone(): void {
      if (!wholeApp || !this.seated || this.done || this.goneArmed) return;
      this.goneArmed = true;
      const run = ++this.goneRun;
      // nearbyJoin.ts afterAwake: 65 one-second ticks of the page's own
      // time, so a tick held while its JS is stopped counts once
      let left = HOST_WINDOW_S;
      const tick = () => {
        if (run !== this.goneRun) return;
        if (--left > 0) {
          this.clock.setTimeout(tick, 1);
          return;
        }
        this.goneArmed = false;
        if (this.status === "open" || this.done || !this.seated) return;
        log(this.d.id, "page: host left (65 s with no link)");
        this.giveUp(false);
      };
      this.clock.setTimeout(tick, 1);
    }
    get clock() {
      return this.d.phone.clock;
    }
    look(): void {
      // a join by code replaces the page's socket, as Connection.useNearby's
      // cutSocket does: the old one closes with its handlers cut, so its
      // heartbeat cannot make links of its own
      this.retry += 1;
      this.tries = 0;
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
      this.kept.look();
      this.claiming = false;
      this.claimRun += 1;
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
    // nearbyJoin.ts greeting(): the seat's resume while seated, or the full
    // table's claim by the kept token
    private greet = (): Record<string, unknown> | null =>
      this.claiming && !this.seated && this.kept.token
        ? { type: "table_join", code, name: this.d.name, token: this.kept.token, seat: null }
        : this.seated ? { type: "table_join", code, name: this.d.name, ...(this.token ? { token: this.token } : {}) } : null;
    open(): void {
      if (this.done) return;
      const no = ++this.sockNo;
      this.d.socketsAt.push(vc.now());
      stats.links += 1;
      this.status = "connecting";
      this.boundSeat = null;
      const sock = new NearbySocket(this.transport, code, (s, detail) => this.onLinkState(no, s, detail), this.clock, this.greet);
      this.sock = sock;
      this.openedAt = null;
      // ws.ts sets no connect timer on a nearby link: the attempt lasts
      // until the socket itself opens or closes it
      if (wsPage) log(this.d.id, `page: attempt ${no}`);
      sock.onopen = () => {
        if (this.sock !== sock) return;
        this.status = "open";
        this.goneRun += 1;
        this.goneArmed = false;
        this.openedAt = vc.now();
        this.backoff = SIM_BACKOFF_FIRST_S;
        this.tries = 0;
        this.misses = 0;
        if (gapMode !== "off" && this.seated) this.checkPending(no);
        if (!this.seated && !this.claiming) sock.send(JSON.stringify({ ...PEEK, code }));
      };
      sock.onmessage = (ev) => {
        if (this.sock !== sock) return;
        const text = ev.data as string;
        stats.maxFrame = Math.max(stats.maxFrame ?? 0, text.length);
        if (wholeApp && text.length > 16 * 1024) fail("frame at most 16 KB", `${this.d.id} got a ${frameTypeOf(text)} of ${text.length} B`);
        this.onFrame(no, JSON.parse(text) as Frame);
      };
      sock.onclose = () => {
        if (this.sock !== sock) return;
        this.status = "closed";
        this.sock = null;
        for (const s of this.d.sent) if (s.sock === no && s.state === "pending") s.state = "closed";
        // nearbyJoin.ts onStatus: a claim's link that drops unanswered puts
        // the page back to looking; its next link looks at the seats again
        if (this.claiming && !this.seated) {
          this.claiming = false;
          this.claimRun += 1;
        }
        this.armGone();
        if (this.leaving) {
          this.finishLeave();
          return;
        }
        if (this.done) return;
        this.retryLater(wsPage && this.openedAt !== null && vc.now() - this.openedAt > LONG_LIVED_S);
      };
    }
    /** The next attempt after the page model's wait, or at once. */
    private retryLater(now: boolean): void {
      let wait: number;
      if (wsPage) {
        wait = now ? 0 : NEARBY_RETRY_S[Math.min(this.tries, NEARBY_RETRY_S.length - 1)];
        this.tries += 1;
      } else {
        wait = now ? 0 : this.backoff;
        this.backoff = Math.min(this.backoff * 2, SIM_BACKOFF_MAX_S);
      }
      if (wsPage) log(this.d.id, `page: retry in ${Math.round(wait * 1000)} ms`);
      const r = ++this.retry;
      this.clock.setTimeout(() => { if (r === this.retry && this.sock === null && !this.done) this.open(); }, wait);
    }
    /** S4: each move whose link went while it was pending, for the decision
     *  still open at this resume, is applied or sent again within 1 s. */
    private checkPending(no: number): void {
      const d = this.d;
      const point = pointOf(room!);
      const owed = d.sent.filter((s) => s.state === "closed" && s.key === point && s.sock < no && !pendingChecked.has(s));
      if (owed.length === 0) return;
      for (const s of owed) pendingChecked.add(s);
      vc.setTimeout(() => {
        for (const s of owed) {
          const again = d.sent.some((x) => x !== s && x.key === s.key && x.seat === s.seat && x.sock > s.sock);
          if (s.state !== "applied" && !again) gap(s.text.includes('"declare"') ? "declare re-sent after a rebuild (L1)" : "pending move re-sent after a rebuild", `${d.id}'s ${s.text.slice(0, 40)} (for ${s.key}) pending when socket ${s.sock} went: neither applied nor sent again 1 s after socket ${no} opened`);
        }
      }, 1);
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
    onLinkState(no: number, s: string, detail?: string): void {
      if (no !== this.sockNo) return;
      // nearbyJoin.ts onLink: the host refused the claim's resume, so the
      // table does not hold that seat
      if (this.claiming && !this.seated && detail === SEAT_GONE) {
        this.claimEnd(true);
        return;
      }
      if (this.seated) {
        // nearbyJoin.ts onLink: a refused resume (the table no longer knows
        // the token) forgets it, and the code's join starts over with the
        // seats; a Leave waiting for a link has nothing left to leave
        if (detail === SEAT_GONE) {
          if (this.leaving) this.finishLeave();
          else {
            log(this.d.id, "page: resume refused: the seat is gone; the seats again");
            this.kept.forget();
            this.goneRun += 1;
            this.goneArmed = false;
            this.look();
          }
        }
        return;
      }
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
        const same = this.token === f.token;
        this.token = f.token as string;
        this.kept.resume(this.token, this.leaving);
        d.tokens.add(this.token);
        const r = room!;
        const at = r.lobby ? r.lobby.findIndex((s) => s?.token === this.token) : r.seats.findIndex((s) => s.token === this.token);
        this.boundSeat = at >= 0 ? at : null;
        if (wholeApp) {
          const gen = typeof f.gen === "number" ? f.gen : -1;
          if (same && gen >= 0 && gen <= this.lastGen) fail("gen monotonic", `${d.id}'s resume on socket ${no} has gen ${gen} after gen ${this.lastGen}`);
          if (!same) this.lastGen = -1;
          this.lastGen = Math.max(this.lastGen, gen);
          const was = tokenSeat.get(this.token);
          if (was !== undefined && at >= 0 && was !== at && !r.lobby) fail("a resume keeps the seat", `${d.id}'s token was seat ${was}, its resume on socket ${no} bound seat ${at}`);
          if (at >= 0) tokenSeat.set(this.token, at);
          this.prog = null;
          vc.setTimeout(() => this.trickAfterResume(no), 2);
        }
        return;
      }
      if (f.type === "room_seats" && !this.seated) {
        if (f.full) {
          if (this.kept.fullPeek() === "claim") {
            this.claim();
            return;
          }
          log(d.id, "page: table full");
          this.giveUp(true);
          return;
        }
        const taken = new Set((f.seats as { seat: number }[]).map((s) => s.seat));
        const open = [0, 1, 2, 3].filter((s) => !taken.has(s));
        const seat = open.length ? driverRng.pick(open) : null;
        // nearbyJoin.ts join(): the panel's Join carries the token kept for
        // this table, so a seat answered on a link that went before its
        // state, or one still held when the page joins by code again, is
        // taken back, not held beside a second one
        this.clock.setTimeout(() => {
          const kept = this.kept.token;
          if (this.sock && this.status === "open" && !this.seated) {
            this.sock.send(JSON.stringify({ type: "table_join", code, name: d.name, seat, ...(kept ? { token: kept } : {}) }));
          }
        }, driverRng.range(0.3, 1.2));
        return;
      }
      if (f.type === "error" && this.claiming && !this.seated) {
        this.claimEnd(true);
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
      if (f.type === "state") this.kept.state((f.round_result as { game_over?: boolean } | null | undefined)?.game_over === true);
      if (this.claiming) {
        this.claiming = false;
        this.claimRun += 1;
      }
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
      if (wholeApp) this.checkProgress(no, f);
      const seat = f.you as number;
      // a frame showing the decision a pending move was for has passed
      const r = room!;
      const point = pointOf(r);
      for (const s of d.sent) if (s.state === "pending" && s.key !== point) s.state = "moot";
      const gen = ++this.decideGen;
      this.clock.setTimeout(() => this.act(gen, no, seat), wholeApp ? this.think() : think());
      if (!wholeApp) return;
      // a stale tap: the move already applied, tapped again on this frame
      const lm = this.lastMove;
      if (this.persona === "staleTap" && lm && lm.state === "applied" && lm.sock === no && lm.seat === seat && /"(play|bury)"/.test(lm.text) && appRng.chance(0.2)) {
        this.clock.setTimeout(() => {
          if (this.sock && this.status === "open" && this.sockNo === no) {
            log(d.id, "page: stale tap");
            stats["stale taps"] = (stats["stale taps"] ?? 0) + 1;
            this.sock.send(lm.text);
          }
        }, appRng.range(0.05, 0.5));
      }
      // a leaver leaves now and then, and comes back by code 3-90 s later
      if (this.persona === "leaver" && appRng.chance(0.004)) {
        this.clock.setTimeout(() => {
          if (!this.seated || this.status !== "open" || this.leaving) return;
          this.leave();
          const back = appRng.range(3, 90);
          vc.setTimeout(() => d.phone.clock.post(() => { if (!this.killed) { log(d.id, "page: rejoins by code (leaver)"); this.look(); } }), back);
        }, appRng.range(0.2, 3));
      }
    }
    /** Per socket, the state never goes back: a round's phases only move on
     *  (round_end to the next deal), and the cards left only fall in play. */
    private checkProgress(no: number, f: Frame): void {
      const RANK: Record<string, number> = { deal: 0, declare: 1, bury: 2, play: 3, round_end: 4 };
      const rank = RANK[f.phase as string] ?? -1;
      const left = ((f.players as { cards_left?: number }[]) ?? []).reduce((a, p) => a + (p.cards_left ?? 0), 0);
      const p = this.prog;
      this.prog = { no, rank, left, phase: f.phase as string };
      if (!p || p.no !== no || rank < 0 || p.rank < 0) return;
      if (rank < p.rank && p.phase !== "round_end") fail("state never goes back", `${this.d.id}'s socket ${no} went from ${p.phase} to ${String(f.phase)}`);
      if (rank === p.rank && f.phase === "play" && left > p.left) fail("state never goes back", `${this.d.id}'s socket ${no} cards left ${p.left} -> ${left} in play`);
    }
    /** 2 s after a resume, the joiner's table is the host's (unless the host's
     *  moved on in the last 2 s, or a fault still runs). */
    private trickAfterResume(no: number): void {
      const d = this.d;
      if (violation || ended || no !== this.sockNo || this.status !== "open" || !room?.round || d.activeFaults > 0 || hostDev.activeFaults > 0) return;
      if (d.phone.clock.suspended || H.clock.suspended || vc.now() - hostDev.lastStateAt < 2) return;
      if (summary(d.lastState) !== summary(hostDev.lastState)) fail("the trick matches 2 s after a resume", `${d.id} shows ${summary(d.lastState)}, the host ${summary(hostDev.lastState)}`);
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
      let a = decide(this.bot, f, r.round, seat);
      // a declarer calls while the cards are dealt, too
      if (!a && wholeApp && f.phase === "deal" && ((f.declare_options as unknown[]) ?? []).length && appRng.chance(0.3)) {
        const cards = this.bot.declare(viewFor(r.round, seat), false);
        const hand = f.hand as { id: number; code: string }[];
        const byId = new Map(hand.map((c) => [c.id, c.code]));
        const opt = cards ? (f.declare_options as number[][]).find((o) => sameCards(o.map((i) => byId.get(i)!), cards)) : undefined;
        if (opt) a = { type: "declare", card_ids: opt };
      }
      if (!a) return;
      const point = pointOf(r);
      // one tap per decision on a link; a new link's fresh state is a new chance
      if (this.d.sent.some((s) => s.key === point && s.sock === no && s.seat === seat)) return;
      this.send(a, seat, point);
      if (a.type === "declare") stats["declares sent"] = (stats["declares sent"] ?? 0) + 1;
      this.lastMove = this.d.sent[this.d.sent.length - 1] ?? null;
      if (this.persona === "doubleTap" && appRng.chance(0.5)) {
        const text = JSON.stringify(a);
        this.clock.setTimeout(() => {
          if (this.sock && this.sockNo === no) {
            stats["double taps"] = (stats["double taps"] ?? 0) + 1;
            this.sock.send(text);
          }
        }, appRng.range(0, 0.05));
      }
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
    leave(): boolean {
      if (!this.seated || !this.sock || this.status !== "open") return false;
      log(this.d.id, "page: Leave");
      emitPhase("leave");
      this.leaving = true;
      this.d.inPlay = false;
      this.kept.forget();
      if (wholeApp && this.token && room && !room.lobby) leaves.push({ d: this.d, token: this.token, at: vc.now(), offline: false, back: vc.now() });
      this.sock.send(JSON.stringify({ type: "table_leave" }));
      const sock = this.sock;
      this.clock.setTimeout(() => { if (this.sock === sock && this.leaving) this.finishLeave(); }, 3);
      return true;
    }
    /** Leave with the link down: the page is off the table at once; the
     *  socket's own sending decides whether the host ever hears. */
    leaveOffline(back: number): void {
      if (!this.seated || this.done) return;
      log(this.d.id, `page: Leave with the link down (network back in ${back.toFixed(1)} s)`);
      emitPhase("leave");
      this.leaving = true;
      this.d.inPlay = false;
      this.kept.forget();
      if (this.token) offlineLeft.add(this.token);
      if (this.token && room && !room.lobby) leaves.push({ d: this.d, token: this.token, at: vc.now(), offline: true, back: vc.now() + back });
      this.sock?.send(JSON.stringify({ type: "table_leave" }));
      this.clock.setTimeout(() => { if (this.leaving) this.finishLeave(); }, 3);
    }
    /** The app is killed: its page and links are gone at once. */
    kill(): void {
      log(this.d.id, "page: app killed");
      this.killed = true;
      this.goneRun += 1;
      this.goneArmed = false;
      const s = this.sock;
      this.sock = null;
      this.status = "closed";
      if (s) {
        s.onopen = null;
        s.onmessage = null;
        s.onclose = null;
      }
      void this.d.phone.plugin.stop();
    }
    /** The relaunch: a seated page resumes by its kept token. */
    relaunch(): void {
      if (!this.killed) return;
      this.killed = false;
      log(this.d.id, `page: relaunched (${this.seated && this.token ? "kept token" : "no seat"})`);
      if (this.done) return;
      if (!this.seated) {
        this.look();
        return;
      }
      this.retry += 1;
      this.open();
    }
    finishLeave(): void {
      this.leaving = false;
      this.done = true;
      this.seated = false;
      this.token = null;
      this.kept.forget();
      const s = this.sock;
      this.sock = null;
      this.status = "closed";
      if (s) {
        s.onclose = null;
        s.close();
      }
    }
    /** nearbyJoin.ts claim(): every seat is taken and this phone keeps a
     *  token for the table, so one resume by it goes out on a new link. */
    claim(): void {
      log(this.d.id, "page: table full: resume sent by the kept token");
      this.claiming = true;
      const run = ++this.claimRun;
      this.clock.setTimeout(() => { if (run === this.claimRun && this.claiming && !this.seated) this.claimEnd(false); }, JOIN_TIMEOUT_S);
      const old = this.sock;
      this.sock = null;
      if (old) {
        old.onopen = null;
        old.onmessage = null;
        old.onclose = null;
        old.close();
      }
      this.retry += 1;
      this.open();
    }
    /** nearbyJoin.ts claimEnd(): the claim did not seat the phone, which is
     *  the full outcome. Only a refusal forgets the token; a claim nobody
     *  answered keeps it. */
    claimEnd(refused: boolean): void {
      log(this.d.id, `page: resume by the kept token ${refused ? "refused" : "unanswered"}`);
      this.claiming = false;
      this.claimRun += 1;
      this.kept.claimEnd(refused);
      this.giveUp(true);
    }
    giveUp(full: boolean): void {
      log(this.d.id, `page: gives up (${full ? "table full" : "host left"})`);
      if (!full && wholeApp) {
        vc.setTimeout(() => {
          const ownAway = this.d.activeFaults > 0 || vc.now() - this.d.clearedAt < 66;
          if (!ended && !room?.closed && hostGoneAt() === null && ownAway) gap("host-left only after the host's own 65 s away (joiner's away counted)", `${this.d.id} showed the host left after its own time away, the host still at its table`);
          else if (!ended && !room?.closed && hostGoneAt() === null) fail("no host-left while the host is alive", `${this.d.id} showed the host left with the host still at its table`);
        }, 1);
      }
      this.done = true;
      this.d.inPlay = false;
      // the host's end forgets the table; a full table keeps its token
      if (!full) this.kept.forget();
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
  for (const d of devices) void d.phone.plugin.addListener("message", () => { d.lastFrameAt = vc.now(); });
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
  runFault = (f: Fault) => {
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
          d.bg += 1;
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
            d.bg -= 1;
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
          touch(d, true);
          if (wholeApp) {
            // the rejoin comes after the Leave itself (a frozen page leaves late), never for a
            // Leave that did not happen
            d.phone.clock.post(() => {
              const left = pg.leave();
              vc.setTimeout(() => {
                touch(d, false);
                if (left && !pg.killed) d.phone.clock.post(() => { log(d.id, "page: rejoins by code"); pg.look(); });
              }, Math.max(4, f.dur));
            });
            return;
          }
          d.phone.clock.post(() => pg.leave());
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
        case "storm": {
          const ls = radio.linksOf(H).filter((l) => l.host === H);
          if (!ls.length) return;
          const hit = devices.filter((x) => ls.some((l) => l.joiner === x.phone));
          for (const x of hit) touch(x, true);
          for (const l of ls) radio.breakLink(l, false, false);
          for (const x of hit) touch(x, false);
          return;
        }
        case "jsFreeze": {
          const c = d.phone.clock;
          if (c.suspended) return;
          c.suspend();
          // a trip to the background that began during the freeze keeps the page stopped
          begin(d, f.dur, () => { if (d.bg === 0) c.resume(appRng); }, d === hostDev);
          return;
        }
        case "loss": {
          const l = hostLink(d);
          if (!l) return;
          l.losses.push({ toHost: f.arg >= 100, frame: LOSS_TYPES[Math.floor(f.arg / 10) % 10], left: f.arg % 10 });
          d.lossAt = vc.now();
          touch(d, true);
          touch(d, false);
          return;
        }
        case "joinReplyLost": {
          // the host's answer to the hello on the joiner's next link is lost
          const l = hostLink(d);
          if (!l) return;
          touch(d, true);
          radio.breakLink(l, false, false);
          const arm = () => {
            const n = hostLink(d);
            if (n && n !== l) {
              n.losses.push({ toHost: false, frame: "resume", left: 1 });
              d.lossAt = vc.now();
            }
            else if (vc.now() - armAt < 30) vc.setTimeout(arm, 0.02);
          };
          const armAt = vc.now();
          vc.setTimeout(arm, 0.02);
          touch(d, false);
          return;
        }
        case "leaveOffline": {
          const pg = pages.get(d);
          if (!pg || !pg.seated || pg.done) return;
          const was = d.phone.joined;
          radio.setNet(d.phone, { radio: false, joined: false });
          d.phone.clock.post(() => pg.leaveOffline(f.dur));
          begin(d, f.dur, () => {
            radio.setNet(d.phone, { radio: true, joined: was, newAddress: false });
            vc.setTimeout(() => d.phone.clock.post(() => { if (!pg.killed) { log(d.id, "page: rejoins by code"); pg.look(); } }), 5);
          }, true);
          return;
        }
        case "kill": {
          const pg = pages.get(d);
          if (!pg || pg.killed || pg.done) return;
          d.phone.clock.post(() => pg.kill());
          const wasIn = d.inPlay;
          d.inPlay = false;
          begin(d, f.dur, () => {
            d.inPlay = wasIn && !pg.done;
            d.phone.clock.post(() => pg.relaunch());
          }, true);
          return;
        }
        case "botSlow": {
          // each bot turn in the window blocks the host's JS 0-6 s
          const until = vc.now() + f.dur;
          let seen = "";
          const look = () => {
            if (vc.now() >= until || ended) return;
            const r = room!;
            const actor = r.round?.turn;
            const key = pointOf(r);
            if (r.round && actor !== null && actor !== undefined && r.seats[actor]?.isBot && key !== seen && !H.clock.suspended) {
              seen = key;
              H.clock.suspend();
              stats["bot blocks"] = (stats["bot blocks"] ?? 0) + 1;
              vc.setTimeout(() => H.clock.resume(), appRng.range(0, 6));
            }
            vc.setTimeout(look, 0.25);
          };
          begin(hostDev, f.dur, () => {}, true);
          look();
          return;
        }
        default:
          return;
      }
  };
  for (const f of schedule) {
    vc.setTimeout(() => {
      if (f.phase) armed.push(f);
      else runFault(f);
    }, f.t);
  }


  // the whole app's invariants, each check (every 0.5 s)
  const held = new Map<Seat, { idx: number; at: number }>();
  const wasConnected = new Map<Seat, boolean>();
  const strikes = new Map<Seat, number>();
  let lobbySnap: { held: boolean; ready: boolean; human: boolean }[] | null = null;
  let turnKey = "";
  let turnFor = 0;
  let lastCheck = 0;
  let declWin: { key: string; time: Map<Device, number>; acted: Set<Device> } | null = null;
  const ghostSince = new Map<Seat, number>();
  const holderOf = (token: string): Device | undefined => devices.find((x) => x.tokens.has(token));
  const wholeAppChecks = (r: LocalRoom, now: number) => {
    const dt = now - lastCheck;
    lastCheck = now;
    // the host ended: every joiner still at the table shows it within 70 s
    const goneAt = hostGoneAt();
    if (goneAt !== null) {
      for (const d of devices) {
        const pg = pages.get(d)!;
        if (d.inPlay && pg.seated && !pg.done && !pg.killed && now - goneAt > 70) fail("host-left within 70 s", `${d.id} still at the table ${Math.round(now - goneAt)} s after the host's table was over`);
      }
      if (ended) return;
    }
    if (r.closed) return;
    const hostAwake = !H.clock.suspended && hostDev.activeFaults === 0;
    // L6: no lobby start while a seated joiner's seat is held, unless all tapped Start
    if (r.lobby) {
      lobbySnap = r.lobby.map((sd, i) => ({ held: !!sd && !sd.isBot && !sd.connected, ready: r.lobbyReady.has(i), human: !!sd && !sd.isBot }));
    } else if (lobbySnap) {
      const snap = lobbySnap;
      lobbySnap = null;
      const holds = snap.map((x, i) => (x.held && !x.ready ? i : -1)).filter((i) => i >= 0);
      if (holds.length && !snap.every((x) => !x.human || x.ready)) gap("no lobby start during a hold (L6)", `the game started with seat ${holds.join(",")} held and not ready`);
    }
    if (!r.round) return;
    const rnd = r.round;
    for (const [i, sd] of r.seats.entries()) {
      // a held seat is not given to anyone else within 60 s
      const was = wasConnected.get(sd);
      if (was === true && !sd.connected && !sd.isBot && !sd.leftByChoice) held.set(sd, { idx: i, at: now });
      if (sd.connected || sd.leftByChoice) held.delete(sd);
      wasConnected.set(sd, sd.connected);
      // L3: no timeout strike while the seat's link is down or the host is away
      const n = strikes.get(sd) ?? sd.timeoutsInRound;
      if (sd.timeoutsInRound > n && !sd.isBot) {
        const holder = holderOf(sd.token);
        const pg = holder ? pages.get(holder) : undefined;
        const down = !!pg && (pg.status !== "open" || holder!.activeFaults > 0 || holder!.phone.clock.suspended);
        if (down || !hostAwake) gap("no timeout strike while the link is down (L3)", `seat ${i} (${sd.name}) struck with ${down ? "its link down" : "the host away"}`);
      }
      strikes.set(sd, sd.timeoutsInRound);
      // L5: no seat shown connected that no phone holds
      const holder = holderOf(sd.token);
      const pg = holder ? pages.get(holder) : undefined;
      const ghost = !sd.isBot && sd.connected && !!pg && (pg.done || pg.killed) && !pg.leaving;
      if (ghost) {
        const since = ghostSince.get(sd) ?? now;
        ghostSince.set(sd, since);
        if (now - since > 15) {
          gap("no ghost seat (L5)", `seat ${i} (${sd.name}) connected ${Math.round(now - since)} s after its phone ${pg!.killed ? "was killed" : "left the table"}`);
          ghostSince.set(sd, now + 1e9);
        }
      } else ghostSince.delete(sd);
    }
    for (const [sd, h] of held) {
      const cur = r.seats[h.idx];
      if (now - h.at > 60) held.delete(sd);
      else if (cur !== sd && !cur.isBot) fail("a held seat is kept 60 s", `seat ${h.idx} given to ${cur.name} ${Math.round(now - h.at)} s after its link went`);
    }
    // L3: no human turn pending over 75 s of the host's time
    const actor = rnd.turn;
    const key = `${pointOf(r)}|${String(actor)}`;
    if (key !== turnKey) {
      turnKey = key;
      turnFor = 0;
    } else if (!H.clock.suspended) turnFor += dt;
    if ((rnd.phase === "play" || rnd.phase === "bury") && actor !== null && actor !== undefined && !r.seats[actor].isBot && turnFor > 75) {
      gap("no human turn over 75 s (L3)", `seat ${actor} (${r.seats[actor].name}) to move for ${Math.round(turnFor)} s`);
      turnFor = -1e9;
    }
    // every connected person has 5 s of the declare window to call in
    if (rnd.phase === "declare") {
      const k = pointOf(r);
      if (!declWin || declWin.key !== k) declWin = { key: k, time: new Map(), acted: new Set() };
      for (const d of devices) {
        const pg = pages.get(d)!;
        const idx = pg.token ? r.seats.findIndex((x) => x.token === pg.token) : -1;
        if (idx < 0 || !r.seats[idx].connected) continue;
        if (rnd.passed.includes(idx) || (rnd.declaration && rnd.declaration.seat === idx)) declWin.acted.add(d);
        if (pg.status === "open" && !d.phone.clock.suspended && d.activeFaults === 0 && hostAwake) declWin.time.set(d, (declWin.time.get(d) ?? 0) + dt);
        else if (!declWin.time.has(d)) declWin.time.set(d, 0);
      }
    } else if (declWin) {
      for (const [d, t] of declWin.time) {
        if (t < 5 && !declWin.acted.has(d)) gap("5 s of declare time (L1)", `${d.id} had ${t.toFixed(1)} s of the declare window it could reach`);
      }
      declWin = null;
    }
    // a Leave gives the seat a bot within 5 s (of the network's return, for a Leave offline)
    for (let i = leaves.length - 1; i >= 0; i--) {
      const l = leaves[i];
      const due = (l.offline ? l.back : l.at) + 5;
      if (now < due) continue;
      leaves.splice(i, 1);
      const sd = r.seats.find((x) => x.token === l.token);
      if (!sd || sd.isBot || sd.leftByChoice || !sd.connected) {
        if (sd && !sd.isBot && !sd.leftByChoice && !sd.connected && l.offline) gap("Leave offline gives the seat a bot in 5 s (L2)", `${l.d.id}'s seat ${sd.name} held, not covered, 5 s after its network came back`);
        continue;
      }
      if (l.d.activeFaults > 0 || hostDev.activeFaults > 0 || l.d.clearedAt > l.at - 1 || hostDev.clearedAt > l.at - 1 || H.clock.suspended) continue;
      if (l.offline) gap("Leave offline gives the seat a bot in 5 s (L2)", `${l.d.id}'s seat ${sd.name} still connected 5 s after its network came back`);
      else fail("a Leave gives the seat a bot in 5 s", `${l.d.id}'s seat ${sd.name} still connected ${Math.round(now - l.at)} s after its Leave`);
    }
  };

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
    if (wholeApp) wholeAppChecks(r, now);
    if (violation) return;
    if (ended || r.closed) return;
    const hostOk = hostDev.activeFaults === 0 && !H.clock.suspended;
    for (const d of devices) {
      const pg = pages.get(d)!;
      // each phone at most one seat
      const mine = r.seats.filter((s) => !s.isBot && s.connected && d.tokens.has(s.token));
      const held = mine.length;
      // a seat left with the link down that the host never heard of is the Leave offline's gap
      if (held > 1 && mine.some((s) => offlineLeft.has(s.token))) {
        if (!offlineLeftSeen.has(d)) gap("Leave offline gives the seat a bot in 5 s (L2)", `${d.id} holds ${held} connected seats: one left with the link down`);
        offlineLeftSeen.add(d);
      } else if (held > 1) fail("one seat per phone", `${d.id} holds ${held} connected seats`);
      // every move sent is applied, refused, or its link ends
      for (const s of d.sent) {
        // (the page's JS runs to find a dead link: not while it is suspended)
        if (s.state === "pending" && now - Math.max(s.at, d.clearedAt) > 30 && d.activeFaults === 0 && pg.status === "open" && pg.sockNo === s.sock && wholeApp && now - d.lossAt < 120) {
          gap("a lost frame on a live link is made good (loss)", `${d.id}'s ${s.text.slice(0, 40)} unanswered ${Math.round(now - s.at)} s after a loss on its open link`);
          s.state = "moot";
        } else if (s.state === "pending" && now - Math.max(s.at, d.clearedAt) > 30 && d.activeFaults === 0 && pg.status === "open" && pg.sockNo === s.sock) {
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
          d.frozenFrom = d.lastFrameAt;
          d.openAtStart = pg.status === "open";
        }
        const from = Math.max(since, d.unhealthySince);
        const bound = opts.bound + (d.openAtStart ? DETECT : 0);
        if (now - from > bound && wholeApp && now - d.lossAt < 90) {
          gap("a lost frame on a live link is made good (loss)", `${d.id} behind ${Math.round(now - from)} s after frames were lost on its open link`);
          d.unhealthySince = now;
        } else if (now - from > bound) {
          fail("back within the bound", `${d.id} not back ${Math.round(now - from)} s after the last fault cleared (socket ${pg.status}, seat ${seatIdx >= 0 ? `${seatIdx} ${seatOk ? "connected" : "not connected"}` : "none"}, state ${fresh ? "current" : "behind"})`);
        }
      } else if (healthy && d.unhealthySince !== null) {
        if (d.unhealthySince >= since - 0.01 || since > 0) {
          recoveries.push(now - Math.max(since, d.unhealthySince));
          freezes.push(now - d.frozenFrom);
        }
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
    // a phase-targeted fault runs at its phase, often well after its t: a
    // fault still armed now never runs, and the settle comes 45 s after the
    // last fault that did run has cleared
    armed.length = 0;
    const settled = () => all.every((d) => d.activeFaults === 0 && vc.now() - d.clearedAt >= 45);
    if (opts.phaseTargeted) await vc.run(() => violation !== null || settled(), 5_000_000);
  } catch (e) {
    fail("simulator", String(e));
  }

  // the settle: every phone still at the table agrees with the host's view
  if (!violation && !ended && !room.closed) {
    for (const d of devices) {
      const pg = pages.get(d)!;
      if (!d.inPlay || pg.done || !room.round || d.activeFaults > 0) continue;
      if (room.lobby) continue;
      if (summary(d.lastState) !== summary(hostDev.lastState) && vc.now() - hostDev.lastStateAt > 3 && wholeApp && vc.now() - d.lossAt < 120) {
        gap("a lost frame on a live link is made good (loss)", `${d.id} shows ${summary(d.lastState)} at the settle, the host ${summary(hostDev.lastState)}, after frames were lost`);
      } else if (summary(d.lastState) !== summary(hostDev.lastState) && vc.now() - hostDev.lastStateAt > 3) {
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
  return { seed: opts.seed, violation, trace, schedule, stats, recoveries, freezes };
}
