// The offline game server: a port of the room logic in
// server/shengji/api/server.py for one human against SmartBot seats. It takes
// the same client messages and sends the same frames as `ws_endpoint`, with
// the same pacing (dealt cards, the declare race and its grace window, bot
// turns), so the UI runs on it unchanged. Fixtures written by
// server/scripts/gen_offline_server_fixtures.py hold its frames to the Python
// server's (server.test.ts).
//
// Single-threaded and synchronous between timers, so the Python room lock has
// no counterpart: every handler runs to completion before the next timer.
import { type Card, type Ordering, RANKS, orderingFor } from "../engine/cards";
import { decompose } from "../engine/combos";
import { type GameState, finishRound, gameLevels, newGame, startRound } from "../engine/game";
import { EngineAssertion, IllegalPlay } from "../engine/legal";
import {
  type RoundState,
  type Trick,
  applyPlay,
  checkPlay,
  bury,
  dealNext,
  declare,
  declareOptions,
  finalizeDeclare,
  passDeclare,
  sortedHand,
} from "../engine/round";
import { SmartBot, viewFor } from "../bot";
import { type Clock, realClock, sleep } from "./clock";
import { type ActionEntry, BotGate, type DecisionKind, type RemoteBot, requestFor } from "./pybot";
import { DeckRng, randomSeed } from "./rng";

export const BOT_DELAY = 0.7;
export const DEAL_DELAY = 0.2;
export const DECLARE_GRACE = 5.0;
export const DECLARE_EXTEND = 3.0;
const DECLARE_POLL = 0.25;
const CHAT_KEEP = 50;
const CHAT_MAX_LEN = 300;
const KITTY_FIRST_ID = 100;

type Json = Record<string, unknown>;

interface ChatEntry {
  seat: number;
  name: string;
  text: string;
  t: number;
  id: number;
  room: string;
}

/** One connection's outbound frames, drained by one timer like the server's
 *  per-seat writer task. Cancelling it drops what it has not sent. */
class Writer {
  private outbox: string[] = [];
  private scheduled = false;
  private dead = false;
  private clock: Clock;
  private deliver: (text: string) => void;

  constructor(clock: Clock, deliver: (text: string) => void) {
    this.clock = clock;
    this.deliver = deliver;
  }

  enqueue(payload: Json): void {
    if (this.dead) return;
    this.outbox.push(JSON.stringify(payload));
    if (this.scheduled) return;
    this.scheduled = true;
    this.clock.setTimeout(() => {
      this.scheduled = false;
      const frames = this.outbox;
      this.outbox = [];
      if (!this.dead) for (const f of frames) this.deliver(f);
    }, 0);
  }

  cancel(): void {
    this.dead = true;
    this.outbox = [];
  }
}

class Seat {
  connected = false;
  gen = 0;
  writer: Writer | null = null;
  name: string;
  isBot: boolean;
  token: string;

  constructor(name: string, isBot: boolean, token: string) {
    this.name = name;
    this.isBot = isBot;
    this.token = token;
  }
}

export class LocalRoom {
  seats: Seat[] = [];
  host = 0;
  game: GameState | null = null;
  ready = new Set<number>();
  chatSeq = 0;
  chat: ChatEntry[] = [];
  ids: Map<number, Card>[] = [new Map(), new Map(), new Map(), new Map()];
  private kittyIds = new Map<number, Card>();
  private kittyGiven = false;
  readonly bot = new SmartBot();
  /** The round's committed actions, for the release bot's requests (pybot.ts). */
  actions: ActionEntry[] = [];
  pumping = false;
  closed = false;
  /** Clock time at which the post-deal declare window closes; null outside it. */
  declareUntil: number | null = null;
  readonly code: string;
  startLevel: string;
  readonly decks: DeckRng;

  constructor(code: string, startLevel: string, decks: DeckRng) {
    this.code = code;
    this.startLevel = startLevel;
    this.decks = decks;
  }

  get round(): RoundState | null {
    return this.game ? this.game.round : null;
  }

  indexRound(): void {
    const rnd = this.round!;
    this.actions = [];
    this.ids = [new Map(), new Map(), new Map(), new Map()];
    this.kittyIds = new Map();
    for (let i = 0; i < 8; i++) this.kittyIds.set(KITTY_FIRST_ID + i, rnd.deck[KITTY_FIRST_ID + i]);
    this.kittyGiven = false;
  }

  mintCardId(seat: number, code: Card): number {
    const nid = Math.max(...this.ids[seat].keys(), KITTY_FIRST_ID + 99) + 1;
    this.ids[seat].set(nid, code);
    return nid;
  }

  syncKitty(): void {
    const rnd = this.round;
    if (rnd && (rnd.phase === "bury" || rnd.phase === "play" || rnd.phase === "round_end") && !this.kittyGiven) {
      for (const [id, code] of this.kittyIds) this.ids[rnd.banker!].set(id, code);
      this.kittyGiven = true;
    }
  }

  codesFor(seat: number, cardIds: number[]): Card[] {
    return cardIds.map((i) => {
      const code = this.ids[seat].get(i);
      if (code === undefined) throw new IllegalPlay("Unknown card id.");
      return code;
    });
  }

  /** Log a dealt card: consecutive deals share one entry, "deal until n". */
  logDeal(dealt: number): void {
    const last = this.actions[this.actions.length - 1];
    if (last && last[0] === "deal") last[1] = dealt;
    else this.actions.push(["deal", dealt]);
  }

  logAction(entry: ActionEntry): void {
    this.actions.push(entry);
  }

  /** A seat's pass, logged only when it is new (a pass is a set member). */
  addPass(seat: number): void {
    const rnd = this.round!;
    if (rnd.passed.includes(seat)) return;
    rnd.passed.push(seat);
    this.logAction(["pass", seat]);
  }

  removeIds(seat: number, cardIds: number[]): void {
    for (const i of cardIds) this.ids[seat].delete(i);
  }

  removeCodes(seat: number, codes: readonly Card[]): void {
    const pool = new Map(this.ids[seat]);
    for (const code of codes) {
      const id = firstIdFor(pool, code);
      if (id === undefined) throw new EngineAssertion(`no id for ${code}`);
      pool.delete(id);
      this.ids[seat].delete(id);
    }
  }

  idsForCodes(seat: number, codes: readonly Card[]): number[] {
    const pool = new Map(this.ids[seat]);
    return codes.map((code) => {
      const id = firstIdFor(pool, code);
      if (id === undefined) throw new EngineAssertion(`no id for ${code}`);
      pool.delete(id);
      return id;
    });
  }
}

function firstIdFor(pool: Map<number, Card>, code: Card): number | undefined {
  for (const [id, c] of pool) if (c === code) return id;
  return undefined;
}

function isDeclareOption(rnd: RoundState, seat: number, cards: readonly Card[]): boolean {
  const key = [...cards].sort().join(",");
  return declareOptions(rnd, seat).some((opt) => [...opt].sort().join(",") === key);
}

// ------------------------------------------------------------------ frames

/** What a play is: "single" | "pair" | "tractor" | "throw" (server.py play_shape). */
export function playShape(cards: readonly Card[], ordering: Ordering | null): string {
  const n = cards.length;
  if (n === 0) return "throw";
  if (n === 1) return "single";
  if (ordering === null) return "throw";
  if (new Set(cards.map((c) => ordering.effSuit(c))).size > 1) return "throw";
  const dec = decompose(cards, ordering);
  if (dec.components.length !== 1) return "throw";
  const comp = dec.components[0];
  if (comp.pairLen === 1 && comp.cards.length === 2) return "pair";
  if (comp.pairLen >= 2) return "tractor";
  return "throw";
}

function trickJson(t: Trick | null, ordering: Ordering | null): Json | null {
  if (t === null) return null;
  const d: Json = {
    leader: t.leader,
    plays: t.plays.map((p) => ({ seat: p.seat, cards: p.cards, shape: playShape(p.cards, ordering) })),
  };
  if (t.winner !== null) {
    d.winner = t.winner;
    d.points = t.points;
  }
  return d;
}

function controller(seat: Seat): string {
  if (seat.isBot) return "bot";
  return seat.connected ? "human" : "bot_cover";
}

/** Seconds left in the declare window, to a tenth, rounded as server.py's
 *  _declare_deadline rounds the same double. */
function declareDeadline(room: LocalRoom, phase: string, now: number): number | null {
  if (phase !== "declare" || room.declareUntil === null) return null;
  return Math.max(0, Math.floor((room.declareUntil - now) * 10 + 0.5)) / 10;
}

export function stateFor(room: LocalRoom, seat: number, now = 0): Json {
  const game = room.game!;
  const rnd = game.round!;
  room.syncKitty();
  const phase = game.gameOver ? "game_over" : rnd.phase;
  const pool = new Map(room.ids[seat]);
  const hand = sortedHand(rnd, seat).map((code) => {
    let id = firstIdFor(pool, code);
    if (id === undefined) id = room.mintCardId(seat, code);
    else pool.delete(id);
    return { id, code };
  });
  const trumpFixed = rnd.phase !== "deal" && rnd.phase !== "declare";
  const ordering = trumpFixed ? orderingFor(rnd.trumpSuit, rnd.trumpRank) : null;
  const trump = trumpFixed
    ? {
        suit: rnd.trumpIsNt ? "NT" : rnd.trumpSuit,
        rank: rnd.trumpRank,
        declarer: rnd.declaration ? rnd.declaration.seat : null,
      }
    : null;
  const result = game.result;
  return {
    type: "state",
    room: room.code,
    you: seat,
    ready: [...room.ready].sort((a, b) => a - b),
    phase,
    players: room.seats.map((sd, s) => ({
      seat: s,
      name: sd.name,
      is_bot: sd.isBot,
      connected: sd.connected || sd.isBot,
      team: s % 2,
      cards_left: rnd.hands[s].length,
      is_banker: rnd.banker === s,
      takeover_in: null,
      controller: controller(sd),
      reserved_for: controller(sd) === "bot_cover" ? sd.name : null,
      reserved_secs: null,
    })),
    hand,
    levels: gameLevels(game),
    games_won: [game.gamesWon[0], game.gamesWon[1]],
    banker: rnd.banker,
    trump,
    turn: rnd.turn,
    declare_options: declareOptions(rnd, seat).map((opt) => room.idsForCodes(seat, opt)),
    passed: [...rnd.passed].sort((a, b) => a - b),
    declare_deadline: declareDeadline(room, phase, now),
    current_declaration: rnd.declaration ? { seat: rnd.declaration.seat, cards: rnd.declaration.cards } : null,
    trick: trickJson(rnd.trick, ordering),
    last_trick: trickJson(rnd.lastTrick, ordering),
    attacker_points: rnd.attackerPoints,
    kitty_count: 8,
    round_result: result
      ? {
          attacker_points: result.attackerPoints,
          kitty_points: result.kittyPoints,
          kitty_cards: result.kittyCards,
          winner_team: result.winnerTeam,
          level_change: result.levelChange,
          next_banker: result.nextBanker,
          new_levels: result.newLevels,
          game_over: result.gameOver,
          games_won: result.gamesWon,
          point_scored: result.pointScored,
        }
      : null,
    message: rnd.message,
    notice: rnd.notice,
    // a solo table never seats an open-table joiner
    joined_round: false,
  };
}

export function roomJson(room: LocalRoom, seat: number): Json {
  return {
    type: "room",
    room: room.code,
    you: seat,
    host: room.host,
    start_level: room.startLevel,
    ready: [...room.ready].sort((a, b) => a - b),
    players: room.seats.map((s, i) => ({ seat: i, name: s.name, is_bot: s.isBot, connected: s.connected || s.isBot })),
  };
}

// ------------------------------------------------------------------ server

export interface LocalServerOptions {
  clock?: Clock;
  /** Seed for a new room's deck shuffle; random by default. */
  seed?: () => number;
  /** The release bot for the bot seats (pybot.ts); SmartBot alone when null. */
  remote?: RemoteBot | null;
  /** SmartBot also plays the human's seat: a whole game runs untouched, to
   *  watch the bots and time them on a device. Never on outside that. */
  autoplay?: boolean;
}

function randomCode(): string {
  const letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";
  let out = "";
  for (let i = 0; i < 4; i++) out += letters[Math.floor(Math.random() * 26)];
  return out;
}

function randomToken(): string {
  const buf = new Uint8Array(12);
  globalThis.crypto.getRandomValues(buf);
  return btoa(String.fromCharCode(...buf)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function cardIds(msg: Json): number[] {
  const ids = msg.card_ids;
  if (
    !Array.isArray(ids) ||
    !ids.length ||
    !ids.every((i) => typeof i === "number" && Number.isInteger(i)) ||
    new Set(ids).size !== ids.length
  ) {
    throw new IllegalPlay("Invalid card selection.");
  }
  return ids as number[];
}

export class LocalServer {
  readonly rooms = new Map<string, LocalRoom>();
  readonly clock: Clock;
  /** Guards the release bot; null when there is none. */
  readonly remote: BotGate | null;
  readonly autoplay: boolean;
  private seed: () => number;

  constructor(opts: LocalServerOptions = {}) {
    this.clock = opts.clock ?? realClock;
    this.seed = opts.seed ?? randomSeed;
    this.remote = opts.remote ? new BotGate(opts.remote, this.clock) : null;
    this.autoplay = opts.autoplay ?? false;
  }

  /** Whether the server moves for `seat`: a bot seat, or any seat under autoplay. */
  drives(room: LocalRoom, seat: number): boolean {
    return this.autoplay || room.seats[seat].isBot;
  }

  /** A new client connection; `deliver` receives each frame as JSON text. */
  connect(deliver: (text: string) => void): LocalConnection {
    return new LocalConnection(this, deliver);
  }

  newRoom(startLevel: string): LocalRoom {
    let code = randomCode();
    while (this.rooms.has(code)) code = randomCode();
    const room = new LocalRoom(code, startLevel, new DeckRng(this.seed()));
    this.rooms.set(code, room);
    return room;
  }

  // -------------------------------------------------------------- fan-out
  enqueue(seat: Seat, payload: Json): void {
    seat.writer?.enqueue(payload);
  }

  broadcast(room: LocalRoom): void {
    room.seats.forEach((seat, i) => {
      if (seat.connected && !seat.isBot) {
        this.enqueue(seat, room.game && room.round ? stateFor(room, i, this.clock.now()) : roomJson(room, i));
      }
    });
  }

  chatPost(room: LocalRoom, entry: { seat: number; name: string; text: string; t: number }): void {
    room.chatSeq += 1;
    const full: ChatEntry = { ...entry, id: room.chatSeq, room: room.code };
    room.chat.push(full);
    if (room.chat.length > CHAT_KEEP) room.chat.splice(0, room.chat.length - CHAT_KEEP);
    for (const sd of room.seats) this.enqueue(sd, { type: "chat", ...full });
  }

  chatSystem(room: LocalRoom, text: string): void {
    this.chatPost(room, { seat: -1, name: "", text, t: Date.now() / 1000 });
  }

  attach(room: LocalRoom, seat: Seat, writer: Writer): number {
    seat.writer?.cancel();
    seat.gen += 1;
    seat.connected = true;
    seat.writer = writer;
    this.enqueue(seat, { type: "resume", token: seat.token, gen: seat.gen });
    this.enqueue(seat, { type: "chat_history", room: room.code, through_id: room.chatSeq, messages: [...room.chat] });
    return seat.gen;
  }

  detach(seat: Seat, room: LocalRoom | null, gen: number | null): void {
    if (gen !== null && gen !== seat.gen) return;
    if (room && room.seats.includes(seat)) room.ready.delete(room.seats.indexOf(seat));
    seat.connected = false;
    seat.writer?.cancel();
    seat.writer = null;
  }

  // ------------------------------------------------------------ bot pump
  currentActor(room: LocalRoom): number | null {
    const rnd = room.round;
    if (rnd === null || rnd.turn === null || rnd.phase === "round_end") return null;
    return rnd.turn;
  }

  kickBots(room: LocalRoom): void {
    const seat = this.currentActor(room);
    if (seat !== null && this.drives(room, seat) && !room.pumping) {
      room.pumping = true;
      this.clock.setTimeout(() => {
        void this.pumpBots(room).finally(() => {
          room.pumping = false;
        });
      }, 0);
    }
  }

  private async pumpBots(room: LocalRoom): Promise<void> {
    for (;;) {
      const started = this.clock.now();
      const seat = this.currentActor(room);
      if (room.closed || seat === null || !this.drives(room, seat)) return;
      const game = room.game!;
      const rnd = game.round!;
      if (game.gameOver) return;
      const phase = rnd.phase;
      const cursor = phase === "play" ? `${rnd.history.length}:${rnd.trick!.plays.length}` : null;
      if (phase !== "bury" && phase !== "play") return;
      let cards: Card[];
      // the release bot's answer, until it is committed or dropped
      let token: string | null = null;
      if (room.seats[seat].isBot && this.remote?.usable()) ({ cards, token } = await this.remoteTurn(room, rnd, seat, phase));
      else if (phase === "bury") cards = room.bot.bury(viewFor(rnd, seat));
      else cards = room.bot.play(viewFor(rnd, seat));
      const pacing = Math.max(0, BOT_DELAY - (this.clock.now() - started));
      if (pacing) await sleep(this.clock, pacing);
      // commit only if the turn this decision was made for is still live
      if (
        room.closed ||
        room.game !== game ||
        game.round !== rnd ||
        rnd.phase !== phase ||
        (phase === "play" && cursor !== `${rnd.history.length}:${rnd.trick!.plays.length}`) ||
        this.currentActor(room) !== seat ||
        !this.drives(room, seat)
      ) {
        if (token) this.remote!.drop(token, "stale");
        return;
      }
      try {
        if (phase === "bury") {
          room.syncKitty();
          bury(rnd, seat, cards);
          room.logAction(["bury", seat, [...cards]]);
          room.removeCodes(seat, cards);
        } else {
          const played = applyPlay(rnd, seat, cards);
          room.logAction(["play", seat, [...cards]]);
          room.removeCodes(seat, played);
        }
        if (token) this.remote!.commit(token);
        // the play just made may have ended the round
        if ((rnd.phase as string) === "round_end" && game.result === null) finishRound(game);
      } catch (e) {
        if (token) this.remote!.drop(token, "invalid");
        if (!(e instanceof IllegalPlay)) throw e;
        rnd.message = `Bot error at seat ${seat}: ${e.message}`;
        return;
      }
      this.broadcast(room);
    }
  }

  /** The release bot's bury or play for `seat`, or SmartBot's when the bot is
   *  unavailable, too slow, or answers something the engine refuses. */
  private async remoteTurn(room: LocalRoom, rnd: RoundState, seat: number, phase: "bury" | "play"): Promise<{ cards: Card[]; token: string | null }> {
    const gate = this.remote!;
    const res = await gate.ask(requestFor(rnd, room.actions, phase, seat));
    if (res.ok && res.cards && this.acceptable(rnd, seat, phase, res.cards)) return { cards: res.cards, token: res.token };
    if (res.ok) gate.drop(res.token, "invalid");
    return { cards: phase === "bury" ? room.bot.bury(viewFor(rnd, seat)) : room.bot.play(viewFor(rnd, seat)), token: null };
  }

  /** Whether the engine would take `cards` from `seat` now (a failing throw counts). */
  private acceptable(rnd: RoundState, seat: number, kind: DecisionKind, cards: Card[]): boolean {
    if (rnd.turn !== seat || rnd.phase !== kind) return false;
    if (kind === "play") return checkPlay(rnd, seat, cards).ok;
    if (cards.length !== 8) return false;
    const hand = [...rnd.hands[seat]];
    return cards.every((c) => {
      const i = hand.indexOf(c);
      if (i < 0) return false;
      hand.splice(i, 1);
      return true;
    });
  }

  // --------------------------------------------------------------- deal
  /** Bot declarations through the release bot, as server.py's _bot_declares:
   *  each decision sees the last committed declaration, and one that a human
   *  declaration overtook while it was being decided is dropped (false). */
  private async botDeclaresRemote(room: LocalRoom, seats: number[], final: boolean): Promise<boolean> {
    const original = room.round;
    let complete = true;
    for (const s of seats) {
      const rnd = room.round;
      if (rnd !== original || rnd === null || (rnd.phase !== "deal" && rnd.phase !== "declare")) return false;
      if (s >= room.seats.length || !room.seats[s].isBot) continue;
      const phase = rnd.phase;
      const declaration = rnd.declaration;
      const gate = this.remote;
      const res = gate?.usable() ? await gate.ask(requestFor(rnd, room.actions, "declare", s, final)) : null;
      if (room.closed || room.round !== rnd || rnd.phase !== phase || rnd.declaration !== declaration || !room.seats[s].isBot) {
        // a human declaration (or a closed room) overtook this decision
        if (res?.ok) gate!.drop(res.token, "stale");
        complete = false;
        continue;
      }
      let cards: Card[] | null;
      // the release bot's answer, until it is committed or dropped
      let token: string | null = null;
      if (res?.ok && (res.cards === null || isDeclareOption(rnd, s, res.cards))) {
        cards = res.cards;
        token = res.token;
      } else {
        if (res?.ok) gate!.drop(res.token, "invalid");
        cards = room.bot.declare(viewFor(rnd, s), final);
      }
      if (cards) {
        try {
          declare(rnd, s, cards);
          room.logAction(["declare", s, [...cards]]);
        } catch (e) {
          if (token) gate!.drop(token, "invalid");
          token = null;
          if (!(e instanceof IllegalPlay)) throw e;
        }
      }
      // no declaration is a decision too: its bot copy is kept like any other
      if (token) gate!.commit(token);
    }
    return complete;
  }

  /** Bot declarations: the release bot's when it is in use, else SmartBot's, inline. */
  private declares(room: LocalRoom, seats: number[], final: boolean): boolean | Promise<boolean> {
    if (this.remote?.usable()) return this.botDeclaresRemote(room, seats, final);
    return this.botDeclares(room, seats, final);
  }

  private botDeclares(room: LocalRoom, seats: number[], final: boolean): boolean {
    const original = room.round;
    for (const s of seats) {
      const rnd = room.round;
      if (rnd !== original || rnd === null || (rnd.phase !== "deal" && rnd.phase !== "declare")) return false;
      if (s >= room.seats.length || !room.seats[s].isBot) continue;
      const cards = room.bot.declare(viewFor(rnd, s), final);
      if (cards) {
        try {
          declare(rnd, s, cards);
          room.logAction(["declare", s, [...cards]]);
        } catch (e) {
          if (!(e instanceof IllegalPlay)) throw e;
        }
      }
    }
    return true;
  }

  spawnDeal(room: LocalRoom): void {
    this.clock.setTimeout(() => void this.runDeal(room), 0);
  }

  /** Stream the deal card by card, then run the declare grace window. */
  private async runDeal(room: LocalRoom): Promise<void> {
    const rnd = room.round!;
    room.declareUntil = null;
    for (;;) {
      if (room.closed || room.round !== rnd) return;
      if (rnd.phase !== "deal") break;
      const dealt = this.clock.now();
      const [seat, idx, code] = dealNext(rnd);
      room.ids[seat].set(idx, code);
      if ((rnd.phase as string) === "declare") {
        // provisional, so the frames before the window opens (the last card,
        // the bots' last declarations) already count down
        room.declareUntil = this.clock.now() + DECLARE_GRACE;
      }
      room.logDeal(rnd.dealPos);
      const declared = this.declares(room, [seat], false);
      if (declared instanceof Promise) {
        await declared;
        if (room.closed || room.round !== rnd) return;
      }
      if (room.round !== rnd) return;
      this.broadcast(room);
      // a remote declaration's time counts toward the deal's pace
      await sleep(this.clock, declared instanceof Promise ? Math.max(0, DEAL_DELAY - (this.clock.now() - dealt)) : DEAL_DELAY);
    }

    const first = this.declares(room, [0, 1, 2, 3], true);
    let needsResponse = !(first instanceof Promise ? await first : first);
    if (room.closed || room.round !== rnd || rnd.phase !== "declare") return;
    for (let s = 0; s < 4; s++) {
      if (this.drives(room, s) && !needsResponse) room.addPass(s);
    }
    let deadline = this.clock.now() + DECLARE_GRACE;
    room.declareUntil = deadline;
    this.broadcast(room);
    let lastDeclaration = rnd.declaration;
    for (;;) {
      await sleep(this.clock, DECLARE_POLL);
      if (room.closed || room.round !== rnd || rnd.phase !== "declare") return;
      let respond = false;
      if (needsResponse || rnd.declaration !== lastDeclaration) {
        lastDeclaration = rnd.declaration;
        deadline = Math.max(deadline, this.clock.now() + DECLARE_EXTEND);
        respond = true;
      }
      if (respond) {
        const again = this.declares(room, [0, 1, 2, 3], true);
        needsResponse = !(again instanceof Promise ? await again : again);
      }
      if (room.closed || room.round !== rnd || rnd.phase !== "declare") return;
      if (needsResponse) continue;
      if (respond) {
        if (rnd.declaration !== lastDeclaration) {
          deadline = Math.max(deadline, this.clock.now() + DECLARE_EXTEND);
        }
        for (let s = 0; s < 4; s++) {
          if (this.drives(room, s)) room.addPass(s);
        }
      }
      const humans = room.seats.flatMap((s, i) => (!s.isBot && s.connected ? [i] : []));
      if (!(humans.every((i) => rnd.passed.includes(i)) || this.clock.now() >= deadline)) {
        if (deadline !== room.declareUntil) {
          // a new declaration bought more time: the countdown shows it
          room.declareUntil = deadline;
          this.broadcast(room);
        }
        continue;
      }
      room.declareUntil = null;
      finalizeDeclare(rnd);
      room.logAction(["finalize"]);
      this.broadcast(room);
      this.kickBots(room);
      return;
    }
  }

  // ------------------------------------------------------------- actions
  private advanceIfAllReady(room: LocalRoom): boolean {
    const game = room.game;
    const rnd = room.round;
    if (game === null || rnd === null || rnd.phase !== "round_end" || game.gameOver) return false;
    const pending = room.seats.some((sd, i) => !sd.isBot && sd.connected && !room.ready.has(i));
    if (pending || room.ready.size === 0) return false;
    room.ready.clear();
    startRound(game, room.decks.deck());
    room.indexRound();
    this.spawnDeal(room);
    return true;
  }

  /** server.py handle_action: throws IllegalPlay on bad input. */
  handleAction(room: LocalRoom, seat: number, msg: Json): void {
    const t = msg.type;
    const game = room.game;
    let rnd = room.round;

    if (t === "chat") {
      const text = String(msg.text ?? "").trim().slice(0, CHAT_MAX_LEN);
      if (!text) return;
      this.chatPost(room, { seat, name: room.seats[seat].name, text, t: Date.now() / 1000 });
      return;
    }
    if (t === "add_bot") {
      if (seat !== room.host || room.seats.length >= 4) throw new IllegalPlay("Cannot add a bot now.");
      room.seats.push(new Seat(`Bot ${room.seats.length}`, true, randomToken()));
    } else if (t === "remove_bot") {
      const last = room.seats[room.seats.length - 1];
      if (seat !== room.host || !last || !last.isBot) throw new IllegalPlay("No bot to remove.");
      if (room.game) throw new IllegalPlay("Game already started.");
      room.seats.pop();
    } else if (t === "set_start_level") {
      if (seat !== room.host) throw new IllegalPlay("Only the host can set the starting level.");
      if (room.game) throw new IllegalPlay("The starting level is fixed once the game has started.");
      const level = msg.start_level;
      if (typeof level !== "string" || !(RANKS as readonly string[]).includes(level)) {
        throw new IllegalPlay("Unknown starting level.");
      }
      room.startLevel = level;
    } else if (t === "start_game") {
      if (seat !== room.host) throw new IllegalPlay("Only the host can start.");
      if (room.seats.length !== 4) throw new IllegalPlay("Need exactly 4 players.");
      if (room.game) throw new IllegalPlay("Game already started.");
      // gamesToWin null: a table keeps playing; holding A scores a point
      room.game = newGame({ startLevel: room.startLevel, gamesToWin: null });
      startRound(room.game, room.decks.deck());
      room.indexRound();
      this.spawnDeal(room);
    } else if (game === null || rnd === null) {
      throw new IllegalPlay("Game not started.");
    } else if (t === "declare") {
      const codes = room.codesFor(seat, cardIds(msg));
      declare(rnd, seat, codes);
      room.logAction(["declare", seat, [...codes]]);
    } else if (t === "pass_declare") {
      const wasPassed = rnd.passed.includes(seat);
      passDeclare(rnd, seat);
      if (!wasPassed) room.logAction(["pass", seat]);
    } else if (t === "bury") {
      room.syncKitty();
      const ids = cardIds(msg);
      const codes = room.codesFor(seat, ids);
      bury(rnd, seat, codes);
      room.logAction(["bury", seat, [...codes]]);
      room.removeIds(seat, ids);
    } else if (t === "play") {
      const ids = cardIds(msg);
      const codes = room.codesFor(seat, ids);
      // a failed throw records fewer cards than were sent
      const played = applyPlay(rnd, seat, codes);
      room.logAction(["play", seat, [...codes]]);
      const same = [...played].sort().join(",") === [...codes].sort().join(",");
      if (same) room.removeIds(seat, ids);
      else room.removeCodes(seat, played);
    } else if (t === "next_round") {
      if (rnd.phase !== "round_end") throw new IllegalPlay("Round not finished.");
      if (game.gameOver) throw new IllegalPlay("Game is over.");
      room.ready.add(seat);
      if (!this.advanceIfAllReady(room)) this.broadcast(room);
    } else {
      throw new IllegalPlay(`Unknown action: ${t === undefined ? "None" : String(t)}`);
    }

    rnd = room.round;
    if (rnd && rnd.phase === "round_end" && room.game && room.game.result === null) finishRound(room.game);
  }

  closeRoom(room: LocalRoom): void {
    room.closed = true;
    this.rooms.delete(room.code);
  }
}

/** One client socket: the counterpart of a `ws_endpoint` invocation. */
export class LocalConnection {
  private room: LocalRoom | null = null;
  private me: Seat | null = null;
  private myGen = 0;
  private closed = false;
  private server: LocalServer;
  private deliver: (text: string) => void;

  constructor(server: LocalServer, deliver: (text: string) => void) {
    this.server = server;
    this.deliver = deliver;
  }

  /** A frame sent straight to the socket, outside any seat's writer. */
  private sendDirect(payload: Json): void {
    const text = JSON.stringify(payload);
    this.server.clock.setTimeout(() => {
      if (!this.closed) this.deliver(text);
    }, 0);
  }

  private attach(room: LocalRoom, seat: Seat): void {
    this.myGen = this.server.attach(room, seat, new Writer(this.server.clock, (text) => {
      if (!this.closed) this.deliver(text);
    }));
  }

  receive(text: string): void {
    if (this.closed) return;
    let msg: unknown;
    try {
      msg = JSON.parse(text);
    } catch {
      return;
    }
    if (typeof msg !== "object" || msg === null || Array.isArray(msg)) return;
    this.handle(msg as Json);
  }

  private handle(msg: Json): void {
    const server = this.server;
    const t = msg.type;
    if (this.room === null || this.me === null) {
      if (t === "create_room") {
        let level = msg.start_level;
        if (level === undefined || level === null) level = RANKS[0];
        else if (typeof level !== "string" || !(RANKS as readonly string[]).includes(level)) {
          this.sendDirect({ type: "error", code: "bad_start_level", message: "Unknown starting level." });
          return;
        }
        const room = server.newRoom(level as string);
        const me = new Seat(String(msg.name || "Player"), false, randomToken());
        room.seats.push(me);
        this.room = room;
        this.me = me;
        this.attach(room, me);
        server.broadcast(room);
      } else if (t === "peek_room") {
        this.sendDirect({ type: "error", code: "room_not_found", message: "Room not found." });
      } else if (t === "join_room") {
        // Offline there is one player: a join can only resume this page's
        // own seat, by its token.
        const room = server.rooms.get(String(msg.room ?? "").toUpperCase());
        const tok = msg.token;
        const seat = room && typeof tok === "string" && tok
          ? room.seats.find((s) => !s.isBot && s.token === tok)
          : undefined;
        if (!room || !seat) {
          this.sendDirect({ type: "error", code: "room_not_found", message: "Room not found." });
          return;
        }
        this.room = room;
        this.me = seat;
        this.attach(room, seat);
        server.chatSystem(room, `${seat.name} reconnected`);
        server.kickBots(room);
        server.broadcast(room);
      } else {
        this.sendDirect({ type: "error", message: "Join a room first." });
      }
      return;
    }

    const room = this.room;
    const me = this.me;
    if (this.myGen !== me.gen) {
      this.sendDirect({ type: "error", code: "stale_connection", message: "This connection was replaced by a newer one." });
      this.close();
      return;
    }
    if (t === "leave_room") {
      server.chatSystem(room, `${me.name} left`);
      server.detach(me, room, this.myGen);
      if (room.game === null) {
        room.seats.splice(room.seats.indexOf(me), 1);
        const humans = room.seats.flatMap((s, i) => (s.isBot ? [] : [i]));
        if (!humans.length) server.closeRoom(room);
        else {
          room.host = humans[0];
          server.broadcast(room);
        }
      } else if (!room.seats.some((s) => !s.isBot && s.connected)) {
        // nobody is left to play the human seat: the game ends here
        server.closeRoom(room);
      }
      this.sendDirect({ type: "left" });
      this.room = null;
      this.me = null;
      return;
    }
    const seatIdx = room.seats.indexOf(me);
    if (seatIdx < 0) {
      this.room = null;
      this.me = null;
      this.sendDirect({ type: "error", code: "room_not_found", message: "Seat no longer exists." });
      return;
    }
    try {
      server.handleAction(room, seatIdx, msg);
      server.broadcast(room);
      server.kickBots(room);
    } catch (e) {
      server.enqueue(me, { type: "error", message: e instanceof IllegalPlay ? e.message : "Invalid request." });
    }
  }

  /** The socket closed: the seat waits, and a join with its token resumes it. */
  close(): void {
    if (this.closed) return;
    if (this.room && this.me) this.server.detach(this.me, this.room, this.myGen);
    this.closed = true;
    this.room = null;
    this.me = null;
  }

  /** For tests and the e2e harness: the room this connection is seated in. */
  get currentRoom(): LocalRoom | null {
    return this.room;
  }
}
