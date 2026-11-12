// The release bot for offline bot seats, when the app carries it.
//
// The iOS app embeds CPython with the served pv-search bot (web/ios/pybot/
// offline_bot.py) behind the native ShengjiBot plugin. For a bot seat's
// decision the local server sends it a request that rebuilds the round as the
// game server holds it: the deck in deal order, the trump rank, the round's
// starting banker and every committed action so far. The bot answers with the
// cards to declare (or none), bury or play.
//
// SmartBot stays the fallback for every decision: in a browser (no plugin),
// while the interpreter is still starting, after it failed to start, when a
// call fails or answers something illegal, and when a decision runs past its
// time limit. A late answer is dropped, and until it arrives the bot is
// treated as busy so no decision queues behind it. The game never waits on
// the plugin longer than the limit.
import type { Card } from "../engine/cards";
import type { RoundState } from "../engine/round";
import { nativeBot } from "../../native";
import type { Clock } from "./clock";

export type DecisionKind = "declare" | "bury" | "play";

/** One committed action of the round, in the order it happened. */
export type ActionEntry =
  | ["deal", number]
  | ["declare", number, Card[]]
  | ["pass", number]
  | ["finalize"]
  | ["bury", number, Card[]]
  | ["play", number, Card[]];

export interface DecisionRequest {
  v: 1;
  kind: DecisionKind;
  seat: number;
  /** The 108 cards in deal order (the last eight are the kitty). */
  deck: Card[];
  trump_rank: string;
  /** The banker the round was dealt with; null on a game's first round. */
  banker: number | null;
  log: ActionEntry[];
  final?: boolean;
}

/** Seconds a decision may take before SmartBot plays it instead. */
export const DECISION_LIMIT: Record<DecisionKind, number> = { declare: 6, bury: 6, play: 4 };
/** Failed calls in a row after which the bot is not asked again. */
export const MAX_FAILURES = 3;

/** The bot behind the plugin: `decide` resolves to the cards (null for no
 *  declaration) or rejects. */
export interface RemoteBot {
  ready(): boolean;
  decide(request: DecisionRequest): Promise<Card[] | null>;
}

export function requestFor(rnd: RoundState, log: readonly ActionEntry[], kind: DecisionKind, seat: number, final = false): DecisionRequest {
  const req: DecisionRequest = {
    v: 1,
    kind,
    seat,
    deck: [...rnd.deck],
    trump_rank: rnd.trumpRank,
    banker: rnd.firstRound ? null : rnd.banker,
    log: log.map((e) => [...e] as ActionEntry),
  };
  if (kind === "declare") req.final = final;
  return req;
}

export type AskResult =
  | { ok: true; cards: Card[] | null; seconds: number }
  | { ok: false; reason: "unavailable" | "busy" | "timeout" | "error"; seconds: number };

export interface BotStats {
  asked: number;
  answered: number;
  unavailable: number;
  busy: number;
  timeout: number;
  error: number;
  invalid: number;
  /** Per kind: answered decisions and their total seconds, as seen from the page. */
  seconds: Record<DecisionKind, { n: number; total: number; max: number }>;
}

/** Guards a RemoteBot with the time limit, one call at a time, and a failure cap. */
export class BotGate {
  readonly stats: BotStats = {
    asked: 0, answered: 0, unavailable: 0, busy: 0, timeout: 0, error: 0, invalid: 0,
    seconds: { declare: { n: 0, total: 0, max: 0 }, bury: { n: 0, total: 0, max: 0 }, play: { n: 0, total: 0, max: 0 } },
  };
  private inFlight = false;
  private failures = 0;
  private remote: RemoteBot;
  private clock: Clock;

  constructor(remote: RemoteBot, clock: Clock) {
    this.remote = remote;
    this.clock = clock;
  }

  /** True when a request now would reach the bot. */
  usable(): boolean {
    return !this.inFlight && this.failures < MAX_FAILURES && this.remote.ready();
  }

  ask(req: DecisionRequest): Promise<AskResult> {
    this.stats.asked += 1;
    const started = this.clock.now();
    const elapsed = () => this.clock.now() - started;
    if (this.failures >= MAX_FAILURES || !this.remote.ready()) {
      this.stats.unavailable += 1;
      return Promise.resolve({ ok: false, reason: "unavailable", seconds: 0 });
    }
    if (this.inFlight) {
      this.stats.busy += 1;
      return Promise.resolve({ ok: false, reason: "busy", seconds: 0 });
    }
    this.inFlight = true;
    let call: Promise<Card[] | null>;
    try {
      call = this.remote.decide(req);
    } catch (e) {
      call = Promise.reject(e);
    }
    return new Promise<AskResult>((resolve) => {
      let settled = false;
      const finish = (r: AskResult) => {
        if (settled) return;
        settled = true;
        resolve(r);
      };
      this.clock.setTimeout(() => {
        if (settled) return;
        this.stats.timeout += 1;
        this.failures += 1;
        finish({ ok: false, reason: "timeout", seconds: elapsed() });
      }, DECISION_LIMIT[req.kind]);
      call.then(
        (cards) => {
          this.inFlight = false;
          if (settled) return;
          const s = elapsed();
          const k = this.stats.seconds[req.kind];
          k.n += 1;
          k.total += s;
          k.max = Math.max(k.max, s);
          this.stats.answered += 1;
          finish({ ok: true, cards, seconds: s });
        },
        () => {
          this.inFlight = false;
          if (settled) return;
          this.stats.error += 1;
          this.failures += 1;
          finish({ ok: false, reason: "error", seconds: elapsed() });
        },
      );
    });
  }

  /** An answer the engine took: the failure count starts over. */
  noteAccepted(): void {
    this.failures = 0;
  }

  /** An answer the engine refused; it counts as a failed call. */
  noteInvalid(): void {
    this.stats.invalid += 1;
    this.failures += 1;
  }
}

function isCardList(v: unknown): v is Card[] {
  return Array.isArray(v) && v.every((c) => typeof c === "string");
}

/** The response's cards: a list of codes, or null (no declaration). */
export function parseResponse(text: unknown): Card[] | null {
  if (typeof text !== "string") throw new Error("response is not a string");
  const out = JSON.parse(text) as { cards?: unknown };
  if (out.cards === null) return null;
  if (!isCardList(out.cards)) throw new Error("response has no cards");
  return out.cards;
}

/** The app's plugin, started once in the background. Null outside the app or
 *  in a build without the plugin. */
export function nativeRemoteBot(): RemoteBot | null {
  const plugin = nativeBot();
  if (!plugin) return null;
  let ready = false;
  plugin.start().then(
    (identity) => {
      ready = true;
      console.info("[pybot] ready", identity);
    },
    (e: unknown) => console.warn("[pybot] unavailable; SmartBot plays the bot seats", e),
  );
  return {
    ready: () => ready,
    decide: async (request) => parseResponse(await plugin.decide(JSON.stringify(request))),
  };
}
