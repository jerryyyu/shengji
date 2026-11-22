// The whole-app soak's chaos picks and its page-side faults. A phone runs
// about one fault a minute (ChaosPacer): faults keep 40-60 s apart, a round's
// end starts 2 min of calm, and once a gap is over the next fault comes with
// p = 0.3 at a phase trigger its frames or log reach (a deal card, the
// declare window, its own bury, the last trick, a round's end, just after its
// own move, the lobby, Start, a join's handshake, a Leave, a game's end) or
// from the background timer 0-20 s later. Kinds are weighted by the phone's
// part at the table. The native kinds run in the
// plugin's debugChaos (NearbyPlugin.swift, a device-test or Beta build
// only); the page kinds run here:
//   - jsfreeze: the page's main thread busy for 2-15 s (30-50 s one time in
//     twenty), as a lock or a trip to the background stops its timers;
//   - loss: the next 1-5 frames of one type, in one direction, lost at the
//     page's bridge to the plugin;
//   - oneway: every frame in one direction lost for 4-20 s, the link up;
//   - reload: the page reloads, the soak resumes and the driver rejoins;
//   - leave: the driver's Leave, then a rejoin by code.
// The bridge faults wrap the Capacitor bridge's nativePromise and fromNative,
// which only a build with the soak's switches loads.
import { frameType } from "./nearbyLog";

type Frame = Record<string, unknown> & { type: string };
type Rand = () => number;

export type ChaosRole = "host" | "joiner";
export type NativeKind = "cancel" | "stall" | "blackhole" | "path" | "listener" | "wifi" | "storm" | "outage60" | "bgfake";
export type PageKind = "jsfreeze" | "loss" | "oneway" | "reload" | "leave";
/** hostend: the plugin's bgfake with an away past its host window, which
 *  ends the host's table for everyone, as designed; drawn only when its
 *  weight is set. */
export type ChaosKind = NativeKind | PageKind | "hostend";

export const PAGE_KINDS: ReadonlySet<ChaosKind> = new Set<ChaosKind>(["jsfreeze", "loss", "oneway", "reload", "leave"]);

/** NearbyPlugin.swift's hostWindow: a host back after more than this ends
 *  its table. */
export const HOST_WINDOW_S = 60;
/** The longest a fault keeps the host away or silent: well inside the host
 *  window, so the soak never ends its own table by chance. */
export const HOST_ABSENCE_MAX_S = HOST_WINDOW_S - 10;
/** The kinds that make the host look absent for their seconds. */
export const HOST_ABSENCE_KINDS: ReadonlySet<ChaosKind> = new Set<ChaosKind>(["bgfake", "outage60", "jsfreeze", "blackhole", "stall", "oneway"]);

/** Each role's kinds and weights: the host leans on storm, jsfreeze and
 *  bgfake; a joiner on loss, oneway, reload and leave. The host's end
 *  (hostend) is off: a soak that tests it sets its weight. */
export const CHAOS_WEIGHTS: Record<ChaosRole, Partial<Record<ChaosKind, number>>> = {
  host: { cancel: 1, stall: 1, blackhole: 1, listener: 1, storm: 2, jsfreeze: 2, bgfake: 2, outage60: 0.5, loss: 0.5, oneway: 0.5, hostend: 0 },
  joiner: { cancel: 1, stall: 1, blackhole: 1, path: 1, wifi: 1, loss: 2, oneway: 2, reload: 1.5, leave: 1.5, jsfreeze: 1, outage60: 0.5 },
};

export interface ChaosPick {
  kind: ChaosKind;
  /** How long it lasts (stall, blackhole, wifi, outage60, jsfreeze, oneway)
   *  or the away time it fakes (bgfake). */
  seconds: number;
  /** loss: frames lost; their type ("" any) and direction. */
  count?: number;
  frame?: string;
  dir?: "in" | "out";
}

/** The frame types a loss picks from. */
export const LOSS_FRAMES = ["state", "room", "ping", "pong", "play", "declare", "resume", "chat", ""] as const;

/** One fault for `role`, by its weights. On the host, every absence kind
 *  ends within HOST_ABSENCE_MAX_S. */
export function chaosPick(role: ChaosRole, rand: Rand = Math.random, weights = CHAOS_WEIGHTS[role]): ChaosPick {
  const kinds = Object.entries(weights).filter(([, w]) => (w ?? 0) > 0) as [ChaosKind, number][];
  const total = kinds.reduce((a, [, w]) => a + w, 0);
  let x = rand() * total;
  let kind = kinds[kinds.length - 1][0];
  for (const [k, w] of kinds) {
    if (x < w) {
      kind = k;
      break;
    }
    x -= w;
  }
  switch (kind) {
    case "wifi": return { kind, seconds: 20 + rand() * 70 };
    case "blackhole": return { kind, seconds: 4 + rand() * 16 };
    // on the host, a long outage inside the host window; on a joiner, past its own 65 s
    case "outage60": return { kind, seconds: role === "host" ? HOST_ABSENCE_MAX_S - 10 + rand() * 10 : 55 + rand() * 20 };
    case "jsfreeze": return { kind, seconds: rand() < 0.05 ? 30 + rand() * 20 : 2 + rand() * 13 };
    case "bgfake": return { kind, seconds: 5 + rand() * (HOST_ABSENCE_MAX_S - 5) };
    case "hostend": return { kind, seconds: HOST_WINDOW_S + 1 + rand() * 9 };
    case "oneway": return { kind, seconds: 4 + rand() * 16, dir: rand() < 0.5 ? "in" : "out" };
    case "loss": return {
      kind, seconds: 0, count: 1 + Math.floor(rand() * 5),
      frame: LOSS_FRAMES[Math.min(LOSS_FRAMES.length - 1, Math.floor(rand() * LOSS_FRAMES.length))], dir: rand() < 0.5 ? "in" : "out",
    };
    default: return { kind, seconds: 3 + rand() * 9 };
  }
}

/** The soak's one-line name of a pick, for the log. */
export function describePick(p: ChaosPick): string {
  if (p.kind === "loss") return `loss ${p.dir} ${p.frame || "any"} x${p.count}`;
  if (p.kind === "oneway") return `oneway ${p.dir} ${p.seconds.toFixed(1)} s`;
  if (p.kind === "bgfake") return `bgfake away ${p.seconds.toFixed(0)} s`;
  if (p.kind === "hostend") return `hostend: bgfake away ${p.seconds.toFixed(0)} s`;
  if (p.kind === "cancel" || p.kind === "path" || p.kind === "listener" || p.kind === "storm" || p.kind === "reload" || p.kind === "leave") return p.kind;
  return `${p.kind} ${p.seconds.toFixed(1)} s`;
}

/** The phases a fault can be aimed at. */
export const TRIGGER_PHASES = [
  "deal_card", "declare_open", "own_bury", "last_trick", "round_end", "after_move",
  "lobby", "start", "join_handshake", "leave", "game_over",
] as const;
export type TriggerPhase = (typeof TRIGGER_PHASES)[number];

/** The chance a trigger fires a fault. */
export const TRIGGER_P = 0.3;

/** The least time between two faults; each gap adds up to CHAOS_JITTER_MS. */
export const CHAOS_GAP_MS = 40_000;
export const CHAOS_JITTER_MS = 20_000;
/** The background timer comes up to this long after a gap is over, so a
 *  phase trigger gets the first chance at it. */
export const BACKGROUND_LAG_MS = 20_000;
/** The calm after a round's end: the next round's deal and first tricks
 *  play out with no fault. */
export const ROUND_CALM_MS = 120_000;

/** When the soak's next fault may run: one fault per gap, whether a phase
 *  trigger or the background timer takes it. A pacer starts in a gap, so a
 *  soak resumed after a reload does not fault at once. */
export class ChaosPacer {
  private next: number;
  private now: () => number;
  private rand: Rand;
  constructor(now: () => number, rand: Rand = Math.random) {
    this.now = now;
    this.rand = rand;
    this.next = now() + this.gap();
  }

  private gap(): number {
    return CHAOS_GAP_MS + this.rand() * CHAOS_JITTER_MS;
  }

  private take(): boolean {
    const t = this.now();
    if (t < this.next) return false;
    this.next = t + this.gap();
    return true;
  }

  /** A phase trigger reached: whether it runs a fault (p = TRIGGER_P, once
   *  the gap is over). */
  aimed(): boolean {
    return this.rand() < TRIGGER_P && this.take();
  }

  /** The background timer fired: whether it runs a fault. */
  background(): boolean {
    return this.take();
  }

  /** How long the background timer waits before it asks again. */
  backgroundDelay(): number {
    return Math.max(0, this.next - this.now()) + this.rand() * BACKGROUND_LAG_MS;
  }

  /** A round ended: no fault for ROUND_CALM_MS. */
  roundEnded(): void {
    this.next = Math.max(this.next, this.now() + ROUND_CALM_MS);
  }
}

const handLen = (f: Frame | null): number => ((f?.hand as unknown[] | undefined) ?? []).length;

/** The phase triggers frame `f` reaches after `prev` (this seat's frame
 *  before it; null at the first): `dealCard` is this round's deal card N
 *  (the frame where the hand first holds N cards). */
export function frameTriggers(prev: Frame | null, f: Frame, dealCard: number): TriggerPhase[] {
  const out: TriggerPhase[] = [];
  if (f.type === "room") {
    if (prev?.type !== "room") out.push("lobby");
    return out;
  }
  if (f.type !== "state") return out;
  const phase = f.phase as string;
  const was = prev?.type === "state" ? (prev.phase as string) : null;
  if (prev?.type === "room" && (phase === "deal" || phase === "declare")) out.push("start");
  if (phase === "deal" && handLen(f) >= dealCard && (was !== "deal" || handLen(prev) < dealCard)) out.push("deal_card");
  if (phase === "declare" && was !== "declare") out.push("declare_open");
  const ownBury = (x: Frame | null) => x?.type === "state" && x.phase === "bury" && x.turn === x.you;
  if (ownBury(f) && !ownBury(prev)) out.push("own_bury");
  if (phase === "play" && handLen(f) === 1 && (was !== "play" || handLen(prev) !== 1)) out.push("last_trick");
  if (phase === "round_end" && was !== "round_end") {
    out.push("round_end");
    const r = f.round_result as { game_over?: boolean; point_scored?: boolean } | null;
    if (r?.game_over || r?.point_scored) out.push("game_over");
  }
  return out;
}

/** The phase triggers a log line reaches: this phone's own move going out
 *  (the fault comes 0-300 ms later), a join's or a resume's handshake, and
 *  the driver's Leave. */
export function lineTriggers(l: { from: string; text: string }): TriggerPhase[] {
  if (l.from === "socket" && /^out (play|bury|declare|pass_declare)$/.test(l.text)) return ["after_move"];
  if (l.from === "join" && (l.text.startsWith("join sent") || l.text === "attempt (resume)")) return ["join_handshake"];
  if (l.from === "soak" && l.text.startsWith("flow: leave")) return ["leave"];
  return [];
}

/** Busy-waits the page's main thread for `ms` (a phone locked or in the
 *  background stops the page the same way): nothing else on the page runs
 *  until it returns. Capped at 50 s. */
export function busyWait(ms: number, now: () => number = () => performance.now()): number {
  const end = now() + Math.min(Math.max(0, ms), 50_000);
  let spins = 0;
  while (now() < end) spins += 1;
  return spins;
}

/** The page's bridge to the plugin, as far as the faults use it. */
export interface Bridge {
  nativePromise?: (plugin: string, method: string, options?: unknown) => Promise<unknown>;
  fromNative?: (result: { pluginId?: string; methodName?: string; data?: { peer?: unknown; text?: unknown } }) => void;
}

interface Rule { dir: "in" | "out"; frame: string; left: number; until: number }

/** Frame loss at the page's bridge to the plugin, in one direction: a frame
 *  the page sends reads as sent, a frame the plugin delivers never reaches
 *  the page. The link itself stays up. */
export class BridgeFaults {
  private rules: Rule[] = [];
  lost = { in: 0, out: 0 };
  private installed = false;
  private plugin: string;
  private now: () => number;
  constructor(plugin = "ShengjiNearby", now: () => number = () => Date.now()) {
    this.plugin = plugin;
    this.now = now;
  }

  /** Wraps the bridge; false when it lacks either call. */
  install(b: Bridge | undefined): boolean {
    if (this.installed) return true;
    if (!b || typeof b.nativePromise !== "function" || typeof b.fromNative !== "function") return false;
    const send = b.nativePromise.bind(b);
    const recv = b.fromNative.bind(b);
    b.nativePromise = (plugin, method, options) => {
      const text = (options as { text?: unknown } | undefined)?.text;
      if (plugin === this.plugin && method === "send" && typeof text === "string" && this.drop("out", text)) return Promise.resolve(undefined);
      return send(plugin, method, options);
    };
    b.fromNative = (result) => {
      const d = result?.data;
      if (result?.methodName === "addListener" && d && typeof d.peer === "string" && typeof d.text === "string" && this.drop("in", d.text)) return;
      recv(result);
    };
    this.installed = true;
    return true;
  }

  /** The next `count` frames of `frame` ("" any) going `dir` are lost. */
  loss(dir: "in" | "out", frame: string, count: number): void {
    this.rules.push({ dir, frame, left: count, until: Infinity });
  }

  /** Every frame going `dir` is lost for `ms`. */
  oneway(dir: "in" | "out", ms: number): void {
    this.rules.push({ dir, frame: "", left: Infinity, until: this.now() + ms });
  }

  /** Whether a frame is lost now; counts it. */
  drop(dir: "in" | "out", text: string): boolean {
    const t = this.now();
    this.rules = this.rules.filter((r) => r.left > 0 && r.until > t);
    const type = frameType(text);
    const r = this.rules.find((x) => x.dir === dir && (x.frame === "" || x.frame === type));
    if (!r) return false;
    r.left -= 1;
    this.lost[dir] += 1;
    return true;
  }

  /** Whether a one-way outage still runs. */
  active(): boolean {
    const t = this.now();
    return this.rules.some((r) => r.until > t && r.until !== Infinity);
  }
}
