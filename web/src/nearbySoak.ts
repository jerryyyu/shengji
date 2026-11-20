// The nearby device test's overnight soak: Autoplay plays this phone's seat
// from its own table frames (SmartBot on what the seat can see, at a
// person's pace, Start and next round included), Chaos asks the plugin for a
// fault every 20-120 s, and a soak summary goes to the log every 10 minutes
// and when either stops. Loaded only by the debug ⋯ rows of a Debug build
// made for the device test (nearbyDebug.tsx); the plugin's debugChaos exists
// only in that build.
import type { Card, TrumpSuit } from "./offline/engine/cards";
import type { RoundState } from "./offline/engine/round";
import { SmartBot, type BotView, type PublicTrick } from "./offline/bot";
import { nearbyPluginProxy } from "./native";
import { nearbyLog, nearbyLogLines, subscribeNearbyLog } from "./nearbyLog";
import { conn } from "./ws";

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

/** A person's pace: 0.5-2 s. */
const pace = () => 500 + Math.random() * 1500;

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

// the soak's counts, from the frames and the log
const stats = {
  started: 0, rounds: 0, games: 0, faults: 0, reconnects: 0, stuck: 0, refused: 0,
  moves: [] as number[], warnings: [] as string[],
};
const summaries: string[] = [];
let summaryTimer: number | null = null;
let offLog: (() => void) | null = null;
let offFrames: (() => void) | null = null;

function resetStats(): void {
  Object.assign(stats, { started: Date.now(), rounds: 0, games: 0, faults: 0, reconnects: 0, stuck: 0, refused: 0, moves: [], warnings: [] });
}

function pct(xs: number[], q: number): number {
  if (!xs.length) return 0;
  const s = [...xs].sort((a, b) => a - b);
  return s[Math.min(s.length - 1, Math.floor(q * s.length))];
}

/** One line: what the soak has done since it started. */
export function soakSummary(): string {
  const mins = Math.round((Date.now() - stats.started) / 60_000);
  const warn = stats.warnings.length ? ` WARN ${stats.warnings.length}: ${[...new Set(stats.warnings)].slice(0, 3).join("; ")}` : " warnings 0";
  return `SOAK ${mins} min: games ${stats.games}, rounds ${stats.rounds}, faults ${stats.faults}, reconnects ${stats.reconnects}, ` +
    `STUCK ${stats.stuck}, refused ${stats.refused}, move->state worst ${Math.max(0, ...stats.moves)} ms p95 ${pct(stats.moves, 0.95)} ms (n=${stats.moves.length});${warn}`;
}

function writeSummary(): void {
  const line = soakSummary();
  summaries.push(line);
  nearbyLog("soak", line);
}

/** Every summary so far and the current one, for the clipboard. */
export function soakSummaryText(): string {
  return [...summaries, soakSummary()].join("\n");
}

/** Each new log line, as it is written (the log calls its listeners once
 *  per line). */
function readLog(): void {
  const lines = nearbyLogLines();
  const l = lines[lines.length - 1];
  if (!l || l.from === "soak") return;
  if (l.text.includes("STUCK")) stats.stuck += 1;
  if (l.text.startsWith("resume: accepted")) stats.reconnects += 1;
  if (l.text.startsWith("REFUSED")) stats.refused += 1;
  if (l.text.startsWith("CHAOS ") && !l.text.startsWith("CHAOS stall over")) stats.faults += 1;
  const m = /, (\d+) ms after the move$/.exec(l.text);
  if (m) stats.moves.push(Number(m[1]));
}

// the seat's own frames: Autoplay's moves and the soak's checks
const bot = new SmartBot();
let mem = freshMemory();
let lastYou: number | null = null;
let lastPhase = "";
let lastFrame: Frame | null = null;
let actTimer: number | null = null;
let startSent = "";

function onFrame(m: Frame): void {
  if (m.type === "left") {
    lastYou = null;
    return;
  }
  if (m.type === "error") {
    stats.refused += 1;
    return;
  }
  if (m.type === "room") {
    lastFrame = m;
    schedule();
    return;
  }
  if (m.type !== "state") return;
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
    if ((m.round_result as { game_over?: boolean } | null)?.game_over) stats.games += 1;
  }
  lastPhase = m.phase as string;
  remember(mem, m);
  lastFrame = m;
  schedule();
}

function schedule(): void {
  if (!autoplayOn) return;
  if (actTimer !== null) window.clearTimeout(actTimer);
  actTimer = window.setTimeout(act, pace());
}

function act(): void {
  actTimer = null;
  const f = lastFrame;
  if (!autoplayOn || !f) return;
  if (f.type === "room") {
    // the lobby: this phone's Start, once per lobby frame set
    const nearby = f.nearby as { ready?: number[] } | undefined;
    const key = `${String(f.room)}|${String(f.you)}`;
    if (nearby && !(nearby.ready ?? []).includes(f.you as number) && startSent !== key) {
      if (conn.send({ type: "table_start" } as never)) startSent = key;
    }
    return;
  }
  const players = f.players as { seat: number; controller: string; is_bot: boolean }[] | undefined;
  const me = players?.find((p) => p.seat === f.you);
  if (me && !me.is_bot && me.controller !== "human") conn.send({ type: "im_back" } as never);
  let move: Record<string, unknown> | null = null;
  try {
    move = autoplayMove(f, mem, bot);
  } catch (e) {
    stats.warnings.push(`autoplay: ${String(e).slice(0, 60)}`);
  }
  if (move) conn.send(move as never);
}

// Chaos: a fault every 20-120 s
interface ChaosPlugin {
  debugChaos(opts: { kind: string; seconds?: number }): Promise<{ done?: boolean }>;
}
let chaosTimer: number | null = null;
const KINDS = ["cancel", "stall", "path", "listener"] as const;

function armChaos(): void {
  if (!chaosOn) return;
  chaosTimer = window.setTimeout(() => {
    chaosTimer = null;
    const p = nearbyPluginProxy() as Partial<ChaosPlugin> | null;
    const kind = KINDS[Math.floor(Math.random() * KINDS.length)];
    const seconds = 3 + Math.random() * 9;
    if (p && typeof p.debugChaos === "function") {
      nearbyLog("soak", `chaos: ${kind}${kind === "stall" ? ` ${seconds.toFixed(1)} s` : ""}`);
      void p.debugChaos({ kind, seconds }).then((r) => {
        if (r?.done === false) nearbyLog("soak", `chaos: ${kind} does not apply here`);
      }, (e: unknown) => nearbyLog("soak", `chaos: ${kind} failed: ${String(e)}`));
    }
    armChaos();
  }, 20_000 + Math.random() * 100_000);
}

function running(): void {
  const any = autoplayOn || chaosOn;
  if (any && offLog === null) {
    resetStats();
    offLog = subscribeNearbyLog(readLog);
    offFrames = conn.subscribe((m) => onFrame(m as unknown as Frame));
    summaryTimer = window.setInterval(writeSummary, 10 * 60_000);
    nearbyLog("soak", `soak started (autoplay ${autoplayOn ? "on" : "off"}, chaos ${chaosOn ? "on" : "off"})`);
  } else if (!any && offLog !== null) {
    writeSummary();
    offLog();
    offLog = null;
    offFrames?.();
    offFrames = null;
    if (summaryTimer !== null) window.clearInterval(summaryTimer);
    summaryTimer = null;
    mem = freshMemory();
    lastYou = null;
  }
  changed();
}

export function setAutoplay(on: boolean): void {
  if (autoplayOn === on) return;
  autoplayOn = on;
  nearbyLog("soak", `autoplay ${on ? "on" : "off"}`);
  if (!on && actTimer !== null) {
    window.clearTimeout(actTimer);
    actTimer = null;
  }
  running();
  if (on) schedule();
}

export function setChaos(on: boolean): void {
  if (chaosOn === on) return;
  chaosOn = on;
  nearbyLog("soak", `chaos ${on ? "on" : "off"}`);
  if (on) armChaos();
  else if (chaosTimer !== null) {
    window.clearTimeout(chaosTimer);
    chaosTimer = null;
  }
  running();
}
