// The whole-app soak's coverage table, from this phone's log lines and its
// table frames: what the soak actually tested.
//   - faults by kind x phase x role x link kind (from the soak's "chaos: ..."
//     lines, which name all four, and how each was picked);
//   - each app flow (from the driver's "flow: ..." lines and the soak's page
//     lines): how often it was walked, and how often with a fault running;
//   - the page's health: event-loop lag, the spans the page was suspended
//     (hidden), the host's ping service time, away marks, takeovers, seat
//     changes, declares sent and shown, the seat's cover after a person's
//     link went, bot fallbacks (from the game's lines), the largest frame,
//     refusals by reason, the most seats down at once, the phone's thermal
//     state, Low Power and memory (the plugin's HEALTH lines), the log
//     upload's backlog, driver stalls.
type Line = { t: number; from: string; text: string };
type Frame = Record<string, unknown> & { type: string };

/** The app flows the table counts, each from the lines that mark it. */
export const FLOWS: readonly { name: string; test: (l: Line) => boolean }[] = [
  { name: "host", test: (l) => l.from === "soak" && l.text.startsWith("flow: hosting") },
  { name: "join", test: (l) => l.from === "join" && l.text.startsWith("join sent") },
  { name: "lobby", test: (l) => l.from === "soak" && l.text === "flow: lobby" },
  { name: "lobby move", test: (l) => l.from === "soak" && l.text.startsWith("flow: lobby move") },
  { name: "start", test: (l) => l.from === "soak" && (l.text === "flow: start" || l.text === "flow: game started") },
  { name: "start taken back", test: (l) => l.from === "soak" && l.text === "flow: start taken back" },
  { name: "mid-game join", test: (l) => l.from === "soak" && l.text === "flow: midgame join" },
  { name: "declare", test: (l) => l.from === "soak" && l.text.startsWith("flow: declare") },
  { name: "leave", test: (l) => l.from === "soak" && l.text.startsWith("flow: leave") },
  { name: "rejoin", test: (l) => l.from === "soak" && l.text.startsWith("flow: rejoin by code") },
  { name: "next round", test: (l) => l.from === "soak" && l.text === "flow: next round" },
  { name: "game over", test: (l) => l.from === "soak" && (l.text === "flow: game over" || l.text.startsWith("flow: game won")) },
  { name: "menu", test: (l) => l.from === "soak" && l.text.startsWith("flow: menu ") && !l.text.includes("failed") },
  {
    name: "background/reload",
    test: (l) => l.from === "soak" && (/^chaos: (bgfake|hostend|jsfreeze|reload)/.test(l.text) || l.text === "page hidden" || l.text === "flow: reload resumed"),
  },
];

/** How long a fault counts as running past its start, by kind: its own
 *  seconds (and 2 s), or 5 s for a one-shot. */
function faultSpan(kind: string, seconds: number): number {
  const oneShot = ["cancel", "path", "listener", "storm", "leave", "reload", "loss"].includes(kind);
  return (oneShot ? 5 : seconds + 2) * 1000;
}

const CHAOS_LINE = /^chaos: (\w+)(?: [^(]*)? \(phase (\S+), role (\S+), link (\S+), by (\S+)\)$/;

const pct = (xs: number[], q: number): number => {
  if (!xs.length) return 0;
  const s = [...xs].sort((a, b) => a - b);
  return s[Math.min(s.length - 1, Math.floor(q * s.length))];
};

export class Coverage {
  /** "kind|phase|role|link" -> faults. */
  faults = new Map<string, number>();
  /** Phase-aimed faults by trigger. */
  byTrigger = new Map<string, number>();
  flows = new Map<string, { n: number; faulted: number }>();
  lags: number[] = [];
  /** The lag sampler's late ticks with the page hidden since the last one. */
  suspends: number[] = [];
  pongMs: number[] = [];
  away = 0;
  takeovers = 0;
  seatChanges = 0;
  declaresSent = 0;
  declaresShown = 0;
  coverMs: number[] = [];
  botFallbacks = 0;
  maxFrame = 0;
  refusals = new Map<string, number>();
  peakDown = 0;
  stalls = 0;
  health: { thermal: string; worstThermal: string; lowPower: number; memMb: number; maxMemMb: number } = {
    thermal: "-", worstThermal: "-", lowPower: 0, memMb: 0, maxMemMb: 0,
  };
  backlog = 0;
  private running: { kind: string; until: number }[] = [];
  private pings = new Map<string, number>();
  private players = new Map<number, { controller: string; is_bot: boolean; connected: boolean; away: boolean }>();
  private downAt = new Map<number, number>();
  private lastDecl = "";
  private lastYou: number | null = null;

  see(l: Line): void {
    const c = CHAOS_LINE.exec(l.text);
    if (l.from === "soak" && c) {
      const [, kind, phase, role, link, by] = c;
      const key = `${kind}|${phase}|${role}|${link}`;
      this.faults.set(key, (this.faults.get(key) ?? 0) + 1);
      if (by !== "bg") this.byTrigger.set(by, (this.byTrigger.get(by) ?? 0) + 1);
      const secs = /(\d+(?:\.\d+)?) s/.exec(l.text);
      this.running.push({ kind, until: l.t + faultSpan(kind, secs ? Number(secs[1]) : 5) });
    }
    if (l.from === "native" && l.text.startsWith("CHAOS ")) this.running.push({ kind: "native", until: l.t + 5000 });
    this.running = this.running.filter((r) => r.until >= l.t);
    for (const f of FLOWS) {
      if (!f.test(l)) continue;
      const e = this.flows.get(f.name) ?? { n: 0, faulted: 0 };
      e.n += 1;
      if (this.running.length > 0) e.faulted += 1;
      this.flows.set(f.name, e);
    }
    if (l.text.startsWith("SOAK DRIVER STALLED")) this.stalls += 1;
    if (l.from === "soak" && l.text.startsWith("flow: declare")) this.declaresSent += 1;
    const ref = /^REFUSED (\S+)/.exec(l.text);
    if (ref) this.bump(ref[1]);
    // the soak's own lines (its summary names the count) are not fallbacks
    if (l.from !== "soak" && /fallback|bot timed? ?out/i.test(l.text)) this.botFallbacks += 1;
    const ping = /^in ping from (\S+)/.exec(l.text);
    if (l.from === "host" && ping) this.pings.set(ping[1], l.t);
    const pong = /^out pong to (\S+)/.exec(l.text);
    if (l.from === "host" && pong && this.pings.has(pong[1])) {
      this.pongMs.push(l.t - this.pings.get(pong[1])!);
      this.pings.delete(pong[1]);
    }
    const h = /^HEALTH thermal (\S+) lowPower (\d) mem (\d+) MB/.exec(l.text);
    if (h) {
      const rank = ["nominal", "fair", "serious", "critical"];
      this.health.thermal = h[1];
      if (rank.indexOf(h[1]) > rank.indexOf(this.health.worstThermal)) this.health.worstThermal = h[1];
      if (h[2] === "1") this.health.lowPower += 1;
      this.health.memMb = Number(h[3]);
      this.health.maxMemMb = Math.max(this.health.maxMemMb, Number(h[3]));
    }
  }

  private bump(reason: string): void {
    this.refusals.set(reason, (this.refusals.get(reason) ?? 0) + 1);
  }

  /** One frame this phone's page was handed (`bytes` its text's length). */
  frame(f: Frame, t: number, bytes: number): void {
    this.maxFrame = Math.max(this.maxFrame, bytes);
    if (f.type === "error") this.bump(`error:${String(f.code ?? "none")}`);
    if (f.type !== "state" && f.type !== "room") return;
    const you = f.you as number;
    if (this.lastYou !== null && you !== this.lastYou) this.seatChanges += 1;
    this.lastYou = you;
    if (f.type !== "state") {
      this.players.clear();
      return;
    }
    const decl = f.current_declaration as { seat: number; cards: string[] } | null;
    const dk = decl ? `${decl.seat}|${decl.cards.join(",")}` : "";
    if (dk !== this.lastDecl && decl && decl.seat === you) this.declaresShown += 1;
    this.lastDecl = dk;
    let down = 0;
    for (const p of (f.players as { seat: number; controller: string; is_bot: boolean; connected: boolean; away?: boolean }[]) ?? []) {
      const was = this.players.get(p.seat);
      const away = p.away === true || (!p.is_bot && p.controller !== "human");
      if (!p.is_bot && !p.connected) down += 1;
      if (was) {
        if (!was.away && away && !p.is_bot) this.away += 1;
        if (!was.is_bot && p.is_bot) this.takeovers += 1;
        if (was.connected && !p.connected && p.controller === "human") this.downAt.set(p.seat, t);
      }
      if (this.downAt.has(p.seat) && (p.controller !== "human" || p.is_bot)) {
        this.coverMs.push(t - this.downAt.get(p.seat)!);
        this.downAt.delete(p.seat);
      } else if (p.connected) this.downAt.delete(p.seat);
      this.players.set(p.seat, { controller: p.controller, is_bot: p.is_bot, connected: p.connected, away });
    }
    this.peakDown = Math.max(this.peakDown, down);
  }

  /** The lag sampler's tick came `ms` late; `hidden`: the page was hidden
   *  at some point since its last tick, so the span is the page suspended,
   *  not its event loop's lag. */
  loop(ms: number, hidden: boolean): void {
    if (!hidden) {
      this.lag(ms);
      return;
    }
    this.suspends.push(ms);
    if (this.suspends.length > 20_000) this.suspends.splice(0, 10_000);
  }

  /** The page's event loop ran `ms` late. */
  lag(ms: number): void {
    this.lags.push(ms);
    if (this.lags.length > 20_000) this.lags.splice(0, 10_000);
  }

  private suspendedText(): string {
    return this.suspends.length ? `n=${this.suspends.length} max ${(Math.max(...this.suspends) / 1000).toFixed(1)} s` : "n=0";
  }

  /** The table, a few lines. */
  table(): string[] {
    const s = (xs: number[]) => (xs.length ? `p95 ${Math.round(pct(xs, 0.95))} max ${Math.round(Math.max(...xs))} ms (n=${xs.length})` : "n=0");
    const faults = [...this.faults.entries()].sort((a, b) => b[1] - a[1]).map(([k, v]) => `${k.replace(/\|/g, "/")} ${v}`);
    const byPhase = new Map<string, number>();
    for (const [k, v] of this.faults) byPhase.set(k.split("|")[1], (byPhase.get(k.split("|")[1]) ?? 0) + v);
    const flows = FLOWS.map((f) => {
      const e = this.flows.get(f.name) ?? { n: 0, faulted: 0 };
      return `${f.name} ${e.n}/${e.faulted}`;
    });
    const refused = [...this.refusals.entries()].map(([k, v]) => `${k} ${v}`).join(", ") || "none";
    return [
      `coverage faults (kind/phase/role/link): ${faults.join(", ") || "none"}`,
      `coverage faults by phase: ${[...byPhase.entries()].map(([k, v]) => `${k} ${v}`).join(", ") || "none"}; aimed by trigger: ${[...this.byTrigger.entries()].map(([k, v]) => `${k} ${v}`).join(", ") || "none"}`,
      `coverage flows (walked/with a fault): ${flows.join(", ")}`,
      `coverage health: loop lag ${s(this.lags)}, suspended ${this.suspendedText()}, host pong service ${s(this.pongMs)}, away marks ${this.away}, takeovers ${this.takeovers}, ` +
        `seat changes ${this.seatChanges}, declares sent ${this.declaresSent} shown ${this.declaresShown}, seat cover after a drop ${s(this.coverMs)}, ` +
        `bot fallbacks ${this.botFallbacks}, max frame ${this.maxFrame} B, refused ${refused}, peak seats down ${this.peakDown}, ` +
        `thermal ${this.health.thermal} (worst ${this.health.worstThermal}), low power ${this.health.lowPower}, mem ${this.health.memMb} MB (max ${this.health.maxMemMb}), ` +
        `upload backlog ${Math.round(this.backlog / 1024)} KB, driver stalls ${this.stalls}`,
    ];
  }
}
