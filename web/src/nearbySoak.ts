// The nearby device test's overnight soak, over the whole app. Autoplay is
// the driver (nearbySoakDriver.ts): this phone walks the table's whole life
// on its own as one persona (nearbySoakPersonas.ts) through the app's own
// entry points: a join by code, the lobby, Start, the deal with declares,
// bury and play (SmartBot on what the seat can see), each round's end, Leave
// and a rejoin, the ⋯ menu. Chaos runs about one fault a minute, aimed at a
// phase trigger or from a background timer, with 30 s of calm after a
// round's end that finds no gap running (nearbySoakChaos.ts
// ChaosPacer): native kinds in the
// plugin's debugChaos, page kinds (a frozen main thread, frame loss at the
// bridge, a reload, a Leave) here. A soak summary and its coverage table
// (nearbySoakCoverage.ts) go to the log every 10 minutes and when either
// stops. The switches and the table's code are kept in localStorage, so a
// reload resumes the soak (nearbyDebug.tsx). Loaded only by the debug ⋯
// rows of a build made for the device test or the Beta; the plugin's
// debugChaos exists only in those builds.
import type { Card, TrumpSuit } from "./offline/engine/cards";
import type { RoundState } from "./offline/engine/round";
import { SmartBot, type BotView, type PublicTrick } from "./offline/bot";
import { nearbyPluginProxy } from "./native";
import { nearbyLog, nearbyLogLines, readNearbyLogFile, subscribeNearbyLog, type LogLine } from "./nearbyLog";
import { nearbyHost } from "./nearbySession";
import { forgetSeatToken, nearbyJoin } from "./nearbyJoin";
import { conn, getSavedName } from "./ws";
import { offlineGame } from "./components/offlineGame";
import {
  BridgeFaults, busyWait, ChaosPacer, chaosPick, describePick, frameTriggers, lineTriggers, PAGE_KINDS,
  type Bridge, type ChaosPick, type ChaosRole, type TriggerPhase,
} from "./nearbySoakChaos";
import { Coverage } from "./nearbySoakCoverage";
import { SoakDriver, type JoinPort } from "./nearbySoakDriver";
import { pickPersonas, type PersonaMix } from "./nearbySoakPersonas";

export { chaosPick, CHAOS_WEIGHTS, type ChaosKind, type ChaosRole } from "./nearbySoakChaos";

type Frame = Record<string, unknown> & { type: string };
interface HandCard {
  id: number;
  code: string;
}
type TrickJson = { leader: number; plays: { seat: number; cards: string[] }[] } | null;

/** What the seat has seen this round, beyond the latest frame. */
export interface SeatMemory {
  /** Completed tricks, oldest first, from the frames' last tricks. */
  history: PublicTrick[];
  lastTrickKey: string;
  /** The cards this seat buried, as the banker. */
  buried: Card[];
  handSize: number;
}

export function freshMemory(): SeatMemory {
  return { history: [], lastTrickKey: "", buried: [], handSize: 0 };
}

const copyTrick = (t: NonNullable<TrickJson>): PublicTrick => ({
  leader: t.leader,
  plays: t.plays.map((p) => ({ seat: p.seat, cards: [...p.cards] })),
});

/** Folds a state frame into the seat's memory: a new round clears it, and a
 *  last trick it has not seen joins the history. */
export function remember(mem: SeatMemory, f: Frame): void {
  const hand = (f.hand as HandCard[] | undefined) ?? [];
  if (f.phase === "deal" && hand.length < mem.handSize) Object.assign(mem, freshMemory());
  mem.handSize = hand.length;
  const last = f.last_trick as TrickJson;
  if (last) {
    const key = JSON.stringify(last.plays);
    if (key !== mem.lastTrickKey) {
      mem.lastTrickKey = key;
      mem.history.push(copyTrick(last));
    }
  }
}

/** The bot's view from what this seat can see in `f`; null before trump is
 *  fixed (a view needs the trump rank). */
export function viewFromFrame(f: Frame, mem: SeatMemory): BotView | null {
  const trump = f.trump as { suit: string | null; rank: string } | null;
  if (!trump) return null;
  const seat = f.you as number;
  const decl = f.current_declaration as { seat: number; cards: string[] } | null;
  const trick = f.trick as TrickJson;
  return {
    seat,
    hand: (f.hand as HandCard[]).map((c) => c.code),
    phase: f.phase as RoundState["phase"],
    trumpRank: trump.rank,
    trumpSuit: (trump.suit === "NT" ? null : trump.suit) as TrumpSuit,
    declaration: decl ? { seat: decl.seat, cards: [...decl.cards], strength: 1 } : null,
    banker: (f.banker as number | null) ?? null,
    ownBuried: f.banker === seat ? [...mem.buried] : [],
    history: mem.history.map((t) => ({ leader: t.leader, plays: t.plays.map((p) => ({ seat: p.seat, cards: [...p.cards] })) })),
    trick: trick ? copyTrick(trick) : null,
  };
}

function idsFor(hand: HandCard[], codes: string[]): number[] | null {
  const pool = [...hand];
  const out: number[] = [];
  for (const code of codes) {
    const k = pool.findIndex((c) => c.code === code);
    if (k < 0) return null;
    out.push(pool.splice(k, 1)[0].id);
  }
  return out;
}

/** The seat's next message for state frame `f`, or null when it owes none:
 *  Start in the lobby is the caller's; here a pass in the declare window, a
 *  bury, a play, and next round at a round's end. */
export function autoplayMove(f: Frame, mem: SeatMemory, bot: SmartBot = new SmartBot()): Record<string, unknown> | null {
  if (f.type !== "state") return null;
  const seat = f.you as number;
  const phase = f.phase as string;
  if (phase === "round_end") {
    const result = f.round_result as { game_over?: boolean } | null;
    if (result?.game_over) return null;
    return (f.ready as number[]).includes(seat) ? null : { type: "next_round" };
  }
  if (phase === "declare") return (f.passed as number[]).includes(seat) ? null : { type: "pass_declare" };
  if (f.turn !== seat) return null;
  const hand = f.hand as HandCard[];
  const view = viewFromFrame(f, mem);
  if (!view) return null;
  if (phase === "bury") {
    const cards = bot.bury(view);
    const ids = idsFor(hand, cards);
    if (!ids) return null;
    mem.buried = [...cards];
    return { type: "bury", card_ids: ids };
  }
  if (phase === "play") {
    const ids = idsFor(hand, bot.play(view));
    return ids ? { type: "play", card_ids: ids } : null;
  }
  return null;
}

type LinkKind = "wifi" | "p2p";

/** Under this share of link time on peer-to-peer, the split warns: the soak
 *  is not testing peer-to-peer enough. */
export const P2P_FLOOR = 0.3;

/** The soak's split by connection kind, from the plugin's log lines: link-ups
 *  over Wi-Fi and peer-to-peer, the link time on each, and each STUCK put on
 *  the kind of the link last made. A link is peer-to-peer when its line says
 *  so or its interface is awdl or llw. */
export class LinkSplit {
  ups: Record<LinkKind, number> = { wifi: 0, p2p: 0 };
  stuck: Record<LinkKind, number> = { wifi: 0, p2p: 0 };
  ms: Record<LinkKind, number> = { wifi: 0, p2p: 0 };
  movedOff = 0;
  private live = new Map<string, { kind: LinkKind; since: number }>();
  private current: LinkKind | null = null;

  /** The kind of the link last made, or null before any. */
  currentKind(): LinkKind | null {
    return this.current;
  }

  static kind(iface: string, says: boolean): LinkKind {
    return says || /^(awdl|llw)/.test(iface) ? "p2p" : "wifi";
  }

  see(l: Pick<LogLine, "t" | "from" | "text">): void {
    const host = /^host link up via (\S+) \([^)]*\)( peer-to-peer)?$/.exec(l.text);
    const inbound = /^inbound (\S+) up via (\S+)( peer-to-peer)?$/.exec(l.text);
    if (l.from === "native" && host) this.up("host", LinkSplit.kind(host[1], !!host[2]), l.t);
    else if (l.from === "native" && inbound) this.up(inbound[1], LinkSplit.kind(inbound[2], !!inbound[3]), l.t);
    else if (l.from === "native" && l.text === "moving the host link off peer-to-peer") { this.movedOff += 1; this.end("host", l.t); }
    else if (l.from === "native" && l.text.startsWith("drop ")) this.end(l.text.slice(5).split(" ")[0], l.t);
    else if (l.from === "host" && /^link \S+ gone/.test(l.text)) this.end(l.text.split(" ")[1], l.t);
    if (l.text.includes("STUCK") && this.current) this.stuck[this.current] += 1;
  }

  private up(id: string, kind: LinkKind, t: number): void {
    this.end(id, t);
    this.live.set(id, { kind, since: t });
    this.ups[kind] += 1;
    this.current = kind;
  }

  private end(id: string, t: number): void {
    const l = this.live.get(id);
    if (!l) return;
    this.ms[l.kind] += Math.max(0, t - l.since);
    this.live.delete(id);
  }

  /** `links wifi 12 / p2p 7, p2p time 41%, STUCK wifi 0 / p2p 1, moved off p2p 2`, with the
   *  links still up counted to `t`. */
  summary(t: number): string {
    const ms = { ...this.ms };
    for (const l of this.live.values()) ms[l.kind] += Math.max(0, t - l.since);
    const all = ms.wifi + ms.p2p;
    const share = all > 0 ? `${Math.round((100 * ms.p2p) / all)}%` : "-";
    const low = all > 0 && ms.p2p < P2P_FLOOR * all ? ` (under ${Math.round(P2P_FLOOR * 100)}%)` : "";
    return `links wifi ${this.ups.wifi} / p2p ${this.ups.p2p}, p2p time ${share}${all > 0 ? ` ${Math.round(ms.p2p / 1000)} s${low}` : ""}, ` +
      `STUCK wifi ${this.stuck.wifi} / p2p ${this.stuck.p2p}, moved off p2p ${this.movedOff}`;
  }
}

type Line = Pick<LogLine, "t" | "from" | "text">;
const SOCKET_MOVES = /^out (play|bury|declare|pass_declare)$/;
const sec = (ms: number): string => (ms / 1000).toFixed(1);
const spreadS = (xs: number[]): string =>
  xs.length ? `n=${xs.length} p50 ${sec(pct(xs, 0.5))} p95 ${sec(pct(xs, 0.95))} max ${sec(Math.max(...xs))} s` : "n=0";

/** The soak's link health, from this phone's log lines and its table
 *  frames (all times page milliseconds):
 *  - an outage runs from a joiner's link going (its drop, a STUCK, or a
 *    resume attempt) to "resume: accepted"; its freeze is from the last
 *    frame heard before it to then, its recovery from the clear of the
 *    fault that ran on this phone (a stall's or blackhole's end, a
 *    one-shot fault's own line, when the outage began within 5 s of it) to
 *    then;
 *  - per outage, the resume attempts made and the hellos sent with no
 *    answer on their link;
 *  - a move is ignored when its link goes before its answer, and re-sent
 *    when the same kind goes out within 5 s of the resume after it;
 *  - each STUCK by its fault: a stall running, a stall ended within 1 s, a
 *    blackhole running or ended within 1 s, or none;
 *  - stalls and blackholes over 4 s with no STUCK from their start to 1 s
 *    after their end;
 *  - the bytes of each chat_history (one per resume), state frames repeated
 *    exactly, and the frames' bytes per second while dealing (deal, declare,
 *    bury) and in play;
 *  - migration: from the move off peer-to-peer to the next Wi-Fi link up;
 *  - the log's upload bytes, and chaos picks the plugin said do not apply. */
export class SoakMetrics {
  freezes: number[] = [];
  recoveries: number[] = [];
  attempts: number[] = [];
  abandonedHellos = 0;
  ignored = 0;
  resent = 0;
  hostIgnored = 0;
  stuck = { stall: 0, after: 0, blackhole: 0, none: 0 };
  quiet = { stall: 0, stalls: 0, blackhole: 0, blackholes: 0 };
  chatHistory: number[] = [];
  dupStates = 0;
  bytes = { dealing: 0, play: 0 };
  ms = { dealing: 0, play: 0 };
  migrations: number[] = [];
  uploaded = 0;
  notApplied = 0;
  private lastHeard: number | null = null;
  private outage: { from: number; at: number; attempts: number; hellos: number } | null = null;
  private cleared: number | null = null;
  private moveOut: string | null = null;
  private owed: { kind: string; by: number } | null = null;
  private resend: string | null = null;
  private fault: { kind: "stall" | "blackhole"; from: number; long: boolean; stuck: boolean } | null = null;
  private ended: { kind: "stall" | "blackhole"; at: number; long: boolean; stuck: boolean } | null = null;
  private lastState = "";
  private phase: { kind: "dealing" | "play" | null; since: number } = { kind: null, since: 0 };
  private movingSince: number | null = null;

  see(l: Line): void {
    const { t, from, text } = l;
    if (from === "socket" && (/^in [a-z_]+/.test(text) || text.startsWith("pong in "))) {
      if (this.outage === null) this.lastHeard = t;
      const m = /, (\d+) ms after the move$/.exec(text);
      if (m) this.moveOut = null;
    }
    if (from === "socket") {
      const out = SOCKET_MOVES.exec(text);
      if (out) {
        if (this.owed && out[1] === this.owed.kind && t <= this.owed.by) this.resent += 1;
        this.owed = null;
        this.moveOut = out[1];
      }
    }
    if ((from === "native" && text === "drop host") || text.startsWith("STUCK") || (from === "join" && text === "attempt (resume)")) this.down(t);
    if (from === "join" && text === "attempt (resume)" && this.outage) this.outage.attempts += 1;
    if (from === "socket" && /^resume: link up in \d+ ms; hello sent/.test(text) && this.outage) this.outage.hellos += 1;
    if (from === "socket" && text.startsWith("resume: accepted")) this.back(t);
    if (text.startsWith("STUCK")) this.stuckAt(t);
    if (from === "host" && text.startsWith("IGNORED ")) this.hostIgnored += 1;
    if (from === "native") this.chaos(t, text);
    if (from === "native" && text === "moving the host link off peer-to-peer") this.movingSince = t;
    if (from === "native" && this.movingSince !== null && /^host link up via (\S+)/.test(text)) {
      if (LinkSplit.kind(/^host link up via (\S+)/.exec(text)![1], text.endsWith("peer-to-peer")) === "wifi") this.migrations.push(t - this.movingSince);
      this.movingSince = null;
    }
    const up = /^upload (\d+) B ok/.exec(text);
    if (from === "log" && up) this.uploaded += Number(up[1]);
  }

  private down(t: number): void {
    if (this.outage !== null) return;
    // a fault's clear long before this outage did not cause it
    if (this.cleared !== null && t - this.cleared > 5000) this.cleared = null;
    this.outage = { from: this.lastHeard ?? t, at: t, attempts: 0, hellos: 0 };
    if (this.moveOut !== null) {
      this.ignored += 1;
      this.resend = this.moveOut;
      this.moveOut = null;
    }
  }

  private back(t: number): void {
    const o = this.outage;
    if (o === null) return;
    this.outage = null;
    this.freezes.push(t - o.from);
    this.attempts.push(o.attempts);
    this.abandonedHellos += Math.max(0, o.hellos - 1);
    if (this.cleared !== null) this.recoveries.push(t - this.cleared);
    this.cleared = null;
    this.lastHeard = t;
    if (this.resend !== null) this.owed = { kind: this.resend, by: t + 5000 };
    this.resend = null;
  }

  private stuckAt(t: number): void {
    if (this.fault) {
      this.fault.stuck = true;
      this.stuck[this.fault.kind] += 1;
    } else if (this.ended && t - this.ended.at <= 1000) {
      this.ended.stuck = true;
      this.stuck[this.ended.kind === "stall" ? "after" : "blackhole"] += 1;
    } else this.stuck.none += 1;
  }

  private chaos(t: number, text: string): void {
    const start = /^CHAOS (stall|blackhole)[: ].* for ([\d.]+) s$/.exec(text);
    if (start) {
      this.settle();
      this.fault = { kind: start[1] as "stall" | "blackhole", from: t, long: Number(start[2]) > 4, stuck: false };
      return;
    }
    if (/^CHAOS (stall|blackhole) over/.test(text) && this.fault) {
      this.ended = { kind: this.fault.kind, at: t, long: this.fault.long, stuck: this.fault.stuck };
      this.fault = null;
      this.cleared = t;
      return;
    }
    if (/^CHAOS (cancel|path|listener)/.test(text) || text.startsWith("CHAOS wifi fake over")) this.cleared = t;
  }

  /** A fault's quiet tally once its 1 s after has passed (or a new one starts). */
  private settle(): void {
    const e = this.ended;
    if (!e) return;
    this.ended = null;
    if (!e.long) return;
    if (e.kind === "stall") {
      this.quiet.stalls += 1;
      if (!e.stuck) this.quiet.stall += 1;
    } else {
      this.quiet.blackholes += 1;
      if (!e.stuck) this.quiet.blackhole += 1;
    }
  }

  /** One table frame this phone's page was handed, at `t`. */
  frame(m: Frame, t: number): void {
    const text = JSON.stringify(m);
    if (m.type === "chat_history") this.chatHistory.push(text.length);
    if (m.type === "state") {
      if (text === this.lastState) this.dupStates += 1;
      this.lastState = text;
      const kind = m.phase === "play" ? "play" : m.phase === "deal" || m.phase === "declare" || m.phase === "bury" ? "dealing" : null;
      this.time(t);
      this.phase = { kind, since: t };
    }
    if (this.phase.kind) this.bytes[this.phase.kind] += text.length;
  }

  private time(t: number): void {
    if (this.phase.kind) this.ms[this.phase.kind] += Math.max(0, t - this.phase.since);
    this.phase.since = t;
  }

  summary(t: number, minutes: number): string {
    if (this.ended && t - this.ended.at > 1000) this.settle();
    this.time(t);
    const rate = (k: "dealing" | "play") => (this.ms[k] > 0 ? Math.round(this.bytes[k] / (this.ms[k] / 1000)) : 0);
    const kb = (b: number) => `${(b / 1024).toFixed(1)} KB`;
    const per10 = minutes > 0 ? (this.uploaded / minutes) * 10 : 0;
    return `freeze ${spreadS(this.freezes)}, recovery ${spreadS(this.recoveries)}, ` +
      `attempts/outage max ${Math.max(0, ...this.attempts)} (hellos abandoned ${this.abandonedHellos}), ` +
      `moves ignored ${this.ignored} re-sent ${this.resent} (host ignored ${this.hostIgnored}), ` +
      `STUCK in stall ${this.stuck.stall} / stall ended <1 s ${this.stuck.after} / blackhole ${this.stuck.blackhole} / no fault ${this.stuck.none}, ` +
      `no STUCK in stalls >4 s ${this.quiet.stall}/${this.quiet.stalls} blackholes >4 s ${this.quiet.blackhole}/${this.quiet.blackholes}, ` +
      `chat_history n=${this.chatHistory.length} max ${kb(Math.max(0, ...this.chatHistory))}, dup states ${this.dupStates}, ` +
      `B/s dealing ${rate("dealing")} play ${rate("play")}, migration ${spreadS(this.migrations)}, ` +
      `upload ${kb(per10)}/10 min, chaos not applied ${this.notApplied}`;
  }
}

function pct(xs: number[], q: number): number {
  if (!xs.length) return 0;
  const s = [...xs].sort((a, b) => a - b);
  return s[Math.min(s.length - 1, Math.floor(q * s.length))];
}


let links = new LinkSplit();
let metrics = new SoakMetrics();
let coverage = new Coverage();
const pageMs = (): number => (typeof performance !== "undefined" ? performance.now() : Date.now());

let autoplayOn = false;
let chaosOn = false;
const listeners = new Set<() => void>();
const changed = () => listeners.forEach((l) => l());

export function subscribeSoak(fn: () => void): () => void {
  listeners.add(fn);
  return () => { listeners.delete(fn); };
}

export function soakState(): { autoplay: boolean; chaos: boolean } {
  return { autoplay: autoplayOn, chaos: chaosOn };
}

// what the soak keeps across a reload: its switches, the table's code, the
// persona mix, whether a reload is the soak's own, and when the calm or gap
// a round's end found ends (epoch ms), so a reload inside it keeps the rest
const KEEP_KEY = "shengji.nearbySoak.v1";
interface Kept {
  autoplay: boolean; chaos: boolean; code: string | null; mix?: PersonaMix; reload?: boolean; hosted?: boolean;
  calmUntil?: number;
}

export function keptSoak(): Kept | null {
  try {
    const raw = localStorage.getItem(KEEP_KEY);
    return raw ? (JSON.parse(raw) as Kept) : null;
  } catch {
    return null;
  }
}

function keep(next: Partial<Kept>): void {
  try {
    const was = keptSoak() ?? { autoplay: false, chaos: false, code: null };
    localStorage.setItem(KEEP_KEY, JSON.stringify({ ...was, ...next }));
  } catch { /* this page only */ }
}

// the soak's counts, from the frames and the log
const stats = {
  started: 0, rounds: 0, games: 0, faults: 0, reconnects: 0, stuck: 0, refused: 0,
  moves: [] as number[], warnings: [] as string[],
};
const summaries: string[] = [];
let summaryTimer: number | null = null;
let healthTimer: number | null = null;
let lagTimer: number | null = null;
let offLog: (() => void) | null = null;
let offFrames: (() => void) | null = null;
let offStatus: (() => void) | null = null;
let offJoin: (() => void) | null = null;
let offHost: (() => void) | null = null;

function resetStats(): void {
  Object.assign(stats, { started: Date.now(), rounds: 0, games: 0, faults: 0, reconnects: 0, stuck: 0, refused: 0, moves: [], warnings: [] });
  links = new LinkSplit();
  metrics = new SoakMetrics();
  coverage = new Coverage();
}

/** One line: what the soak has done since it started. */
export function soakSummary(): string {
  const mins = Math.round((Date.now() - stats.started) / 60_000);
  const warn = stats.warnings.length ? ` WARN ${stats.warnings.length}: ${[...new Set(stats.warnings)].slice(0, 3).join("; ")}` : " warnings 0";
  return `SOAK ${mins} min: games ${stats.games}, rounds ${stats.rounds}, faults ${stats.faults}, reconnects ${stats.reconnects}, ` +
    `STUCK ${stats.stuck}, refused ${stats.refused}, move->state worst ${Math.max(0, ...stats.moves)} ms p95 ${pct(stats.moves, 0.95)} ms (n=${stats.moves.length}), ` +
    `${links.summary(Math.round(pageMs()))}, ${metrics.summary(Math.round(pageMs()), (Date.now() - stats.started) / 60_000)};${warn}`;
}

/** The coverage table's lines, as of now. */
export function soakCoverage(): string[] {
  return coverage.table();
}

function writeSummary(): void {
  const line = soakSummary();
  summaries.push([line, ...coverage.table()].join("\n"));
  nearbyLog("soak", line);
  for (const l of coverage.table()) nearbyLog("soak", l);
}

/** Every summary so far and the current one, for the clipboard. */
export function soakSummaryText(): string {
  return [...summaries, soakSummary(), ...coverage.table()].join("\n");
}

/** Each new log line, as it is written (the log calls its listeners once
 *  per line). */
function readLog(): void {
  const lines = nearbyLogLines();
  const l = lines[lines.length - 1];
  if (!l) return;
  coverage.see(l);
  for (const t of lineTriggers(l)) trigger(t, t === "after_move" ? Math.random() * 300 : 0);
  if (l.from === "soak") return;
  links.see(l);
  metrics.see(l);
  if (l.text.includes("STUCK")) stats.stuck += 1;
  if (l.text.startsWith("resume: accepted")) stats.reconnects += 1;
  if (l.text.startsWith("REFUSED")) stats.refused += 1;
  if (l.text.startsWith("CHAOS ") && !/^CHAOS (stall over|wifi fake over|blackhole over|bgfake over)/.test(l.text)) stats.faults += 1;
  const m = /, (\d+) ms after the move$/.exec(l.text);
  if (m) stats.moves.push(Number(m[1]));
}

// the seat's own frames: the driver's moves and the soak's checks
const bot = new SmartBot();
let mem = freshMemory();
let lastYou: number | null = null;
let lastPhase = "";
let lastFrame: Frame | null = null;
let dealCard = 1 + Math.floor(Math.random() * 25);
let driver: SoakDriver | null = null;

function onFrame(m: Frame): void {
  const text = JSON.stringify(m);
  metrics.frame(m, Math.round(pageMs()));
  coverage.frame(m, Math.round(pageMs()), text.length);
  if (typeof m.room === "string" && (m.type === "room" || m.type === "state")) keep({ code: m.room });
  if (m.type === "left") {
    lastYou = null;
    lastFrame = null;
    driver?.frame(m);
    return;
  }
  if (m.type === "error") {
    stats.refused += 1;
    return;
  }
  if (m.type !== "room" && m.type !== "state") return;
  const reached = frameTriggers(lastFrame, m, dealCard);
  for (const t of reached) trigger(t, 0);
  // the round's end may take its own fault first, then the calm begins and
  // a fault still waiting on its delay is dropped
  if (reached.includes("round_end") && chaosOn) {
    cancelAimed();
    keep({ calmUntil: pacer.roundEnded() });
  }
  if (m.type === "state") {
    const you = m.you as number;
    if (lastYou !== null && you !== lastYou) stats.warnings.push(`seat changed ${lastYou}->${you} without a Leave`);
    lastYou = you;
    const hand = (m.hand as HandCard[]) ?? [];
    if (new Set(hand.map((c) => c.id)).size !== hand.length) stats.warnings.push("hand mismatch: a card id twice");
    if ((m.phase === "play" || m.phase === "bury") && hand.length > mem.handSize && mem.handSize > 0 && m.phase === lastPhase) {
      stats.warnings.push(`hand mismatch: ${mem.handSize} -> ${hand.length} cards mid-round`);
    }
    if (m.phase === "round_end" && lastPhase !== "round_end") {
      stats.rounds += 1;
      dealCard = 1 + Math.floor(Math.random() * 25);
      const r = m.round_result as { game_over?: boolean; point_scored?: boolean } | null;
      if (r?.game_over || r?.point_scored) stats.games += 1;
    }
    lastPhase = m.phase as string;
    remember(mem, m);
  }
  lastFrame = m;
  if (autoplayOn) driver?.frame(m);
}

/** This phone's part at the table: the host while its nearby switch is on. */
const chaosRole = (): ChaosRole => (nearbyHost.view.phase === "off" ? "joiner" : "host");

/** The join store, as the driver sees it. */
const joinPort: JoinPort = {
  view: () => nearbyJoin.view,
  seated: () => nearbyJoin.seated,
  hostLeft: () => nearbyJoin.hostLeft,
  open: (code, name) => nearbyJoin.open(code, name),
  pick: (seat) => nearbyJoin.pick(seat),
  join: () => nearbyJoin.join(),
  again: () => nearbyJoin.again(),
  cancel: () => nearbyJoin.cancel(),
  leave: () => nearbyJoin.leave(),
  forgetToken: (code) => forgetSeatToken(code),
};

const wait = (ms: number) => new Promise<void>((r) => window.setTimeout(r, ms));

/** The menu walker's visit: the ⋯ button, then How to play (and back) or a
 *  setting switched and switched back, or just a look; by the buttons'
 *  own taps, as a person's. */
export async function walkMenu(doc: Document = document, rand: () => number = Math.random): Promise<string> {
  const more = doc.querySelector<HTMLElement>(".hud-more-btn");
  if (!more) return "no ⋯ button";
  more.click();
  await wait(300 + rand() * 1200);
  const rows = [...doc.querySelectorAll<HTMLElement>(".hud-menu-row")];
  const howto = rows.find((r) => r.classList.contains("howto-row"));
  const sound = rows.find((r) => r.classList.contains("sound-row"));
  const r = rand();
  if (r < 0.4 && howto) {
    howto.click();
    await wait(1000 + rand() * 3000);
    const { closeHowto } = await import("./howto/route");
    closeHowto();
    return "how to play";
  }
  if (r < 0.7 && sound) {
    sound.click();
    await wait(300 + rand() * 700);
    sound.click();
    await wait(200);
    if (doc.querySelector(".hud-more-btn[aria-expanded=\"true\"]")) more.click();
    return "setting";
  }
  more.click();
  return "look";
}

function startDriver(): void {
  if (driver) return;
  const p = keptSoak();
  driver = new SoakDriver(pickPersonas(Math.random, { role: chaosRole(), mix: p?.mix }), {
    send: (msg) => conn.send(msg as never),
    open: () => conn.status === "open",
    role: chaosRole,
    join: joinPort,
    code: () => keptSoak()?.code ?? nearbyJoin.view?.code ?? null,
    host: () => {
      // the offline table (in place; a page on the game server swaps its
      // socket first), then its Nearby switch with the table's Bots
      offlineGame.startFromPlay();
      nearbyHost.turnOn(getSavedName().trim() || "Soak", offlineGame.botLevel);
    },
    wasHost: () => keptSoak()?.hosted === true,
    keepWasHost: (on) => keep({ hosted: on }),
    forgetCode: () => keep({ code: null }),
    name: () => getSavedName().trim() || "Soak",
    menu: () => walkMenu(),
    bot,
    rand: Math.random,
    now: Date.now,
    setTimeout: (fn, ms) => window.setTimeout(fn, ms),
    clearTimeout: (id) => window.clearTimeout(id),
    log: (text) => nearbyLog("soak", text),
  });
  driver.start();
  if (lastFrame) driver.frame(lastFrame);
}

function stopDriver(): void {
  driver?.stop();
  driver = null;
}

// Chaos: about one fault a minute, on phase triggers or the background timer
interface ChaosPlugin {
  debugChaos(opts: { kind: string; seconds?: number }): Promise<{ done?: boolean }>;
  debugHealth?(): Promise<{ thermal?: string; lowPower?: boolean; memMb?: number }>;
}
let chaosTimer: number | null = null;
let pacer = new ChaosPacer(() => Date.now());
/** Bumped on each Chaos switch, so a delayed fault from an earlier run of
 *  chaos never runs in a later one. */
let chaosSession = 0;
let aimedTimer: number | null = null;
const bridge = new BridgeFaults();

/** A delayed fault is admitted when it fires, against the pacer and the
 *  chaos run it was aimed in; one at a time. */
function trigger(t: TriggerPhase, delayMs: number): void {
  if (!chaosOn) return;
  const run = () => runChaos(chaosPick(chaosRole()), t);
  if (delayMs <= 0) {
    if (pacer.aimed()) run();
    return;
  }
  if (aimedTimer !== null) return;
  const session = chaosSession;
  aimedTimer = window.setTimeout(() => {
    aimedTimer = null;
    if (chaosOn && session === chaosSession && pacer.aimed()) run();
  }, delayMs);
}

function cancelAimed(): void {
  if (aimedTimer !== null) window.clearTimeout(aimedTimer);
  aimedTimer = null;
}

function linkKind(): string {
  return links.currentKind() ?? "none";
}

/** Runs one fault and logs it with the phase, role and link kind it met. */
export function runChaos(pick: ChaosPick, by: TriggerPhase | "bg"): void {
  const role = chaosRole();
  const phase = driver?.phase ?? (lastFrame?.type === "state" ? String(lastFrame.phase) : lastFrame?.type === "room" ? "lobby" : "idle");
  nearbyLog("soak", `chaos: ${describePick(pick)} (phase ${phase}, role ${role}, link ${linkKind()}, by ${by})`);
  if (PAGE_KINDS.has(pick.kind)) return pageChaos(pick, role);
  const p = nearbyPluginProxy() as Partial<ChaosPlugin> | null;
  if (!p || typeof p.debugChaos !== "function") return;
  const kind = pick.kind === "outage60" ? "blackhole" : pick.kind === "hostend" ? "bgfake" : pick.kind;
  void p.debugChaos({ kind, seconds: pick.seconds }).then((r) => {
    if (r?.done === false) {
      metrics.notApplied += 1;
      nearbyLog("soak", `chaos: ${pick.kind} does not apply here`);
    }
  }, (e: unknown) => nearbyLog("soak", `chaos: ${pick.kind} failed: ${String(e)}`));
}

type UploadModule = Pick<typeof import("./nearbyLogUpload"), "nearbyLogUploadOn" | "uploadNearbyLogNow">;

/** The soak's reload: the log's unsent bytes go first (the import and the
 *  upload together at most `capMs`), so
 *  a page reloaded more often than the upload's tick still uploads. */
export async function uploadThenReload(
  reload: () => void = () => location.reload(),
  load: () => Promise<UploadModule> = () => import("./nearbyLogUpload"),
  capMs = 5000,
): Promise<void> {
  let timer: ReturnType<typeof setTimeout> | null = null;
  const deadline = new Promise<void>((r) => { timer = setTimeout(r, capMs); });
  // the deadline covers the module's import as well as the upload
  let late = false;
  const send = (async () => {
    const m = await load();
    // an import that lands after the deadline starts no upload
    if (!late && m.nearbyLogUploadOn()) await m.uploadNearbyLogNow();
  })().catch(() => { /* the reload goes regardless */ });
  await Promise.race([send, deadline]);
  late = true;
  if (timer !== null) clearTimeout(timer);
  reload();
}

function pageChaos(pick: ChaosPick, role: ChaosRole): void {
  switch (pick.kind) {
    case "jsfreeze": {
      // after this line is out: the log's listeners run first
      window.setTimeout(() => {
        const t0 = pageMs();
        busyWait(pick.seconds * 1000);
        nearbyLog("soak", `chaos: jsfreeze over after ${((pageMs() - t0) / 1000).toFixed(1)} s`);
      }, 50);
      return;
    }
    case "loss":
    case "oneway": {
      const w = window as unknown as { Capacitor?: Bridge };
      if (!bridge.install(w.Capacitor)) {
        metrics.notApplied += 1;
        nearbyLog("soak", `chaos: ${pick.kind} does not apply here (no bridge)`);
        return;
      }
      if (pick.kind === "loss") bridge.loss(pick.dir!, pick.frame ?? "", pick.count ?? 1);
      else {
        bridge.oneway(pick.dir!, pick.seconds * 1000);
        const before = { ...bridge.lost };
        window.setTimeout(() => nearbyLog("soak", `chaos: oneway over: ${bridge.lost[pick.dir!] - before[pick.dir!]} lost`), pick.seconds * 1000);
      }
      return;
    }
    case "reload": {
      if (role !== "joiner") return;
      keep({ autoplay: autoplayOn, chaos: chaosOn, reload: true });
      writeSummary();
      window.setTimeout(() => { void uploadThenReload(); }, 500);
      return;
    }
    case "leave": {
      if (role !== "joiner" || !nearbyJoin.seated) return;
      driver?.forceLeave("chaos");
      return;
    }
    default:
      return;
  }
}

function armChaos(): void {
  if (!chaosOn) return;
  chaosTimer = window.setTimeout(() => {
    chaosTimer = null;
    if (pacer.background()) runChaos(chaosPick(chaosRole()), "bg");
    armChaos();
  }, pacer.backgroundDelay());
}

/** The page's health while the soak runs: its event loop's lag (a 500 ms
 *  timer's lateness), and each minute the phone's thermal state, Low Power
 *  and memory (the plugin's debugHealth) and the log upload's backlog. */
function startHealth(): void {
  let due = pageMs() + 500;
  lagTimer = window.setInterval(() => {
    const now = pageMs();
    coverage.lag(Math.max(0, now - due));
    due = now + 500;
  }, 500);
  healthTimer = window.setInterval(() => {
    const p = nearbyPluginProxy() as Partial<ChaosPlugin> | null;
    if (p && typeof p.debugHealth === "function") void p.debugHealth().catch(() => {});
    void backlog();
  }, 60_000);
}

async function backlog(): Promise<void> {
  try {
    const [file, up] = await Promise.all([readNearbyLogFile("current", 0, 0), import("./nearbyLogUpload")]);
    if (file) coverage.backlog = Math.max(0, file.size - up.loadUploadState().cur);
  } catch { /* no log file here */ }
}

function stopHealth(): void {
  if (lagTimer !== null) window.clearInterval(lagTimer);
  if (healthTimer !== null) window.clearInterval(healthTimer);
  lagTimer = healthTimer = null;
}

const onVisibility = () => nearbyLog("soak", document.visibilityState === "visible" ? "page visible" : "page hidden");

function running(): void {
  const any = autoplayOn || chaosOn;
  if (any && offLog === null) {
    resetStats();
    offLog = subscribeNearbyLog(readLog);
    offFrames = conn.subscribe((m) => onFrame(m as unknown as Frame));
    offStatus = conn.subscribeStatus((s) => driver?.statusChanged(s === "open"));
    offJoin = nearbyJoin.subscribe(() => driver?.joinChanged());
    let hostPhase = nearbyHost.view.phase;
    offHost = nearbyHost.subscribe(() => {
      const ph = nearbyHost.view.phase;
      if (ph === "on" && hostPhase !== "on") nearbyLog("soak", "flow: hosting");
      hostPhase = ph;
    });
    document.addEventListener("visibilitychange", onVisibility);
    summaryTimer = window.setInterval(writeSummary, 10 * 60_000);
    startHealth();
    nearbyLog("soak", `soak started (autoplay ${autoplayOn ? "on" : "off"}, chaos ${chaosOn ? "on" : "off"})`);
  } else if (!any && offLog !== null) {
    writeSummary();
    offLog();
    offLog = null;
    for (const off of [offFrames, offStatus, offJoin, offHost]) off?.();
    offFrames = offStatus = offJoin = offHost = null;
    document.removeEventListener("visibilitychange", onVisibility);
    if (summaryTimer !== null) window.clearInterval(summaryTimer);
    summaryTimer = null;
    stopHealth();
    mem = freshMemory();
    lastYou = null;
  }
  changed();
}

export function setAutoplay(on: boolean): void {
  if (autoplayOn === on) return;
  autoplayOn = on;
  // a soak switched off forgets that this phone hosted its table
  keep(on ? { autoplay: on } : { autoplay: on, hosted: false });
  nearbyLog("soak", `autoplay ${on ? "on" : "off"}`);
  running();
  if (on) startDriver();
  else stopDriver();
}

export function setChaos(on: boolean): void {
  if (chaosOn === on) return;
  chaosOn = on;
  keep({ chaos: on });
  nearbyLog("soak", `chaos ${on ? "on" : "off"}`);
  chaosSession += 1;
  cancelAimed();
  if (on) {
    pacer = new ChaosPacer(() => Date.now(), Math.random, keptSoak()?.calmUntil ?? 0);
    armChaos();
  } else if (chaosTimer !== null) {
    window.clearTimeout(chaosTimer);
    chaosTimer = null;
  }
  running();
}

/** At the page's start (nearbyDebug.tsx): a soak that was on before a reload
 *  is on again, and its driver rejoins the kept code. */
export function resumeSoak(): boolean {
  const k = keptSoak();
  if (!k || (!k.autoplay && !k.chaos)) return false;
  if (k.reload) keep({ reload: false });
  nearbyLog("soak", k.reload ? "flow: reload resumed" : "soak resumed at the page's start");
  if (k.chaos) setChaos(true);
  if (k.autoplay) setAutoplay(true);
  return true;
}
