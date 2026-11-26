// The offline game server: a port of the room logic in
// server/shengji/api/server.py for one human against SmartBot seats, and, in
// a nearby room, for up to four humans on nearby phones (nearby/host.ts). It takes
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
import { type Clock, type PauseWatch, pausedAfter, pauseWatch, realClock, sleep } from "./clock";
import { BOT_LEVELS, type BotLevel } from "../../queue/messages";
import { type ActionEntry, BotGate, DEFAULT_BOT_LEVEL, type DecisionKind, type RemoteBot, requestFor } from "./pybot";
import { DeckRng, randomSeed } from "./rng";
import { CANONICAL, LOBBY, RETIRED_MESSAGE, forQueue, forRoom, retired } from "./tables";
import { newNearbyCode } from "./nearby/codes";
import { NEARBY_COPY } from "./nearby/copy";
import { nearbyName } from "./nearby/names";
import { LIMITS, utf8Bytes } from "./nearby/protocol";

export const BOT_DELAY = 0.7;
export const DEAL_DELAY = 0.2;
export const DECLARE_GRACE = 5.0;
export const DECLARE_EXTEND = 3.0;
const DECLARE_POLL = 0.25;
const CHAT_KEEP = 50;
const CHAT_MAX_LEN = 300;
const KITTY_FIRST_ID = 100;
/** server.py MOVE_TIMER: while two or more people sit at a nearby table, a
 *  connected person has this long for each bury, play and round-end Next;
 *  then the bot makes that one decision. */
export const MOVE_TIMER = 60.0;
/** A nearby player back on their link mid-decision has at least this long
 *  left for it: their clock stood still while they were gone, and one that
 *  had nearly run out before the drop gets enough for a decision, but no
 *  more, so dropping and coming back never buys a whole new clock. */
export const RETURN_MIN = 15.0;
/** server.py AWAY_IN_A_ROW and AWAY_PER_ROUND: this many timeouts mark the
 *  seat away, and the bot plays every decision for it until its player is back. */
export const AWAY_IN_A_ROW = 2;
export const AWAY_PER_ROUND = 3;
/** server.py TAKEOVER_AFTER: a dropped human keeps their seat this long
 *  before the bot plays for them (nearby rooms). */
export const TAKEOVER_AFTER = MOVE_TIMER;
/** A nearby lobby seat whose link dropped is kept this long for its owner
 *  to come back by token, then freed: longer than a stuck link's recovery
 *  (up to 8 s to call it stuck over peer-to-peer, 8 s for the new link, 7 s
 *  for the host's answer to its hello), so a seat is never lost to one. */
export const LOBBY_SEAT_HOLD = 30.0;
/** server.py's casual-room watchdog period. */
export const WATCHDOG_POLL = 5.0;
/** A nearby seat's link that is back within this long was a blip: the
 *  table's chat says "disconnected" only for a seat gone longer, and
 *  "reconnected" only after it said "disconnected". */
export const DISCONNECT_NOTICE = 3.0;
/** matchmaking.py BOT_FILL_SECS: once a nearby table has a second person,
 *  bots take its open seats this long after, unless everyone is ready first. */
export const NEARBY_BOT_FILL = 60.0;

type Json = Record<string, unknown>;

/** server.py system_event: a system line's kind and participants. `actor`
 *  is always a person; a seat claim also names `target`, the seat's
 *  previous holder, and whether it was a bot. */
type SystemEvent =
  | { event: "joined" | "left" | "disconnected" | "reconnected" | "reconnected_from_bot" | "bot_playing_for"; actor: string }
  | { event: "took_seat" | "took_over"; actor: string; target: string; target_is_bot: boolean };

interface ChatEntry {
  seat: number;
  name: string;
  text: string;
  t: number;
  /** server.py system_event: a system line's kind and participants. */
  event?: SystemEvent["event"];
  actor?: string;
  target?: string;
  target_is_bot?: boolean;
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

export class Seat {
  connected = false;
  gen = 0;
  writer: Writer | null = null;
  name: string;
  isBot: boolean;
  token: string;
  /** Clock time the owner's socket went, while it is gone. */
  leftAt: number | null = null;
  /** The owner pressed Leave: the bot covers at once, with no window. */
  leftByChoice = false;
  /** The watchdog's first cover of this absence has been announced. */
  botAnnounced = false;
  /** The table's chat has said this seat disconnected, and not yet that it
   *  is back. */
  goneAnnounced = false;
  /** Clock time this seat's move clock started for the decision it owes;
   *  null when it owes none or no clock runs (server.py turn_started). */
  turnStarted: number | null = null;
  /** The move timer marked this present player away: the bot plays for them. */
  away = false;
  timeoutsInRow = 0;
  timeoutsInRound = 0;

  constructor(name: string, isBot: boolean, token: string) {
    this.name = name;
    this.isBot = isBot;
    this.token = token;
  }
}

/** A new room's settings: a table for nearby phones, and its Bots
 *  (Standard unless named). */
export interface RoomOptions {
  nearby?: boolean;
  botLevel?: BotLevel;
}

/** Score the finished round, noting the levels it was played at first (server.py _finish_round). */
function finishRoundOf(room: LocalRoom, game: GameState): void {
  const playedAt = gameLevels(game);
  finishRound(game);
  room.roundLevels = { roundNo: game.roundNo, levels: playedAt };
}

export class LocalRoom {
  seats: Seat[] = [];
  host = 0;
  /** The room frame's Allow joiners, as server.py keeps it; nobody can
   *  reach a table on the device, so it changes nothing else. */
  allowJoiners = true;
  game: GameState | null = null;
  /** The levels the finished round was played at, with its round number
   *  (server.py Room.round_levels): the result holds only the new ones. */
  roundLevels: { roundNo: number; levels: [string, string] } | null = null;
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
  /** The table's Bots, fixed for its game: every release-bot request names it. */
  /** The table's Bots; a nearby lobby's host may change it before the game. */
  botLevel: BotLevel;
  readonly decks: DeckRng;
  /** A table for nearby phones: it waits in a lobby for joiners until the
   *  host starts it, and a dropped seat is covered by a bot. */
  readonly nearby: boolean;
  /** The nearby lobby's four seats, null where nobody sits; null once the
   *  game has started, when `seats` holds all four. */
  lobby: (Seat | null)[] | null = null;
  /** The watchdog timer is pending. */
  watching = false;
  /** Clock time the lobby's bots fill the open seats; null while the host
   *  sits alone, who waits for people. */
  botsAt: number | null = null;
  /** Bumped whenever `botsAt` is set or cleared, so an older timer does nothing. */
  botsGen = 0;
  /** Someone has joined: the host's Nearby switch can no longer turn the
   *  table back into a solo one; Leave ends it. */
  joinedOnce = false;
  /** The decision the seats' move clocks belong to (server.py timer_key). */
  timerKey: string | null = null;
  /** The decision whose clock ran out, which the bot makes for its seat. */
  timeoutKey: string | null = null;
  /** Called once when the room closes (the nearby host stops its link then). */
  onClosed: (() => void) | null = null;

  constructor(code: string, startLevel: string, decks: DeckRng,
              { nearby = false, botLevel = DEFAULT_BOT_LEVEL }: RoomOptions = {}) {
    this.code = code;
    this.startLevel = startLevel;
    this.decks = decks;
    this.nearby = nearby;
    this.botLevel = botLevel;
    if (nearby) this.lobby = [null, null, null, null];
  }

  /** The seats by index: the lobby's before the start, else the game's. */
  slots(): (Seat | null)[] {
    return this.lobby ?? this.seats;
  }

  seatIndex(seat: Seat): number {
    return this.slots().indexOf(seat);
  }

  humans(): Seat[] {
    return this.slots().filter((s): s is Seat => s !== null && !s.isBot);
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

/** The chat_history frame a seat gets on attach. At a nearby table it
 *  keeps only the newest lines that fit in one link frame
 *  (LIMITS.frameBytes): a frame over it would never cross the link. */
export function chatHistory(room: LocalRoom): Json {
  const frame = { type: "chat_history", room: room.code, through_id: room.chatSeq, messages: [...room.chat] };
  if (room.nearby) while (frame.messages.length && utf8Bytes(JSON.stringify(frame)) > LIMITS.frameBytes) frame.messages.shift();
  return frame;
}

/** server.py _takeover_in: seconds before the bot plays for a dropped human. */
export function takeoverIn(seat: Seat, now: number): number | null {
  if (seat.isBot || seat.connected || seat.botAnnounced || seat.leftAt === null) return null;
  return Math.round(Math.max(0, TAKEOVER_AFTER - (now - seat.leftAt)) * 10) / 10;
}

/** server.py _decision_key: the decision the table waits on; a new key
 *  restarts every owing seat's move clock. */
export function decisionKey(room: LocalRoom): string | null {
  const game = room.game;
  const rnd = room.round;
  if (game === null || rnd === null || game.gameOver) return null;
  if (rnd.phase === "round_end") return `${game.roundNo}:end`;
  if (rnd.phase === "bury") return `${game.roundNo}:bury:${rnd.turn}`;
  if (rnd.phase === "play") return `${game.roundNo}:play:${rnd.turn}:${rnd.history.length}:${rnd.trick ? rnd.trick.plays.length : 0}`;
  return null;
}

/** server.py _owing_seats: the human seats that owe the current decision. */
export function owingSeats(room: LocalRoom): number[] {
  const key = decisionKey(room);
  if (key === null) return [];
  if (key.endsWith(":end")) return room.seats.flatMap((sd, i) => (!sd.isBot && !room.ready.has(i) ? [i] : []));
  const seat = room.round!.turn;
  return seat === null || room.seats[seat].isBot ? [] : [seat];
}

/** server.py _timer_live: a nearby room's move clock runs while two or more
 *  of its seats are people's. Nobody waits on a lone player. */
export function moveTimerLive(room: LocalRoom): boolean {
  return room.nearby && room.game !== null && room.seats.filter((s) => !s.isBot).length >= 2;
}

/** server.py _timed: whether `sd`'s move clock is running. */
function timed(room: LocalRoom, sd: Seat): boolean {
  return moveTimerLive(room) && !sd.isBot && sd.connected && sd.turnStarted !== null;
}

/** server.py _turn_deadline: seconds this seat has left for its decision,
 *  or null when no clock runs for it. */
export function turnDeadline(room: LocalRoom, seat: number, now: number): number | null {
  const sd = room.seats[seat];
  if (!timed(room, sd) || sd.away) return null;
  return Math.round(Math.max(0, MOVE_TIMER - (now - sd.turnStarted!)) * 10) / 10;
}

/** server.py _reserved: the dropped seat is still its owner's alone. */
export function reserved(seat: Seat, now: number): boolean {
  if (seat.isBot || seat.connected || seat.leftAt === null) return false;
  return now - seat.leftAt < TAKEOVER_AFTER;
}

/** A nearby room's per-player cover fields, as server.py's state_for sends them. */
function coverFields(sd: Seat, now: number): Json {
  return {
    takeover_in: sd.leftByChoice ? null : takeoverIn(sd, now),
    controller: controller(sd),
    reserved_for: controller(sd) === "bot_cover" ? sd.name : null,
    reserved_secs: reserved(sd, now) ? takeoverIn(sd, now) : null,
    left: sd.leftByChoice && controller(sd) === "bot_cover",
  };
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
      ...(room.nearby
        ? { ...coverFields(sd, now), turn_deadline: turnDeadline(room, s, now), away: sd.away }
        : {
            takeover_in: null,
            controller: controller(sd),
            reserved_for: controller(sd) === "bot_cover" ? sd.name : null,
            reserved_secs: null,
          }),
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
    tricks_done: rnd.history.length,
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
          ...(room.roundLevels && room.roundLevels.roundNo === game.roundNo ? { old_levels: room.roundLevels.levels } : {}),
          game_over: result.gameOver,
          games_won: result.gamesWon,
          point_scored: result.pointScored,
        }
      : null,
    message: rnd.message,
    notice: rnd.notice,
    opener: room.host,
    allow_joiners: room.allowJoiners,
    // a solo table never seats an open-table joiner
    joining: [],
    joined_round: false,
  };
}

/** A nearby lobby's waiting state, for its panel: the seconds until bots
 *  take the open seats, and whether the table is locked to its joiners. */
function nearbyJson(room: LocalRoom, now: number): Json {
  return {
    bots_in: room.botsAt === null ? null : Math.max(0, Math.round((room.botsAt - now) * 10) / 10),
    locked: room.joinedOnce,
  };
}

/** The seats a newcomer may take at a nearby game in progress, as the
 *  online by-code join's claimable seats (server.py _join_room): every bot
 *  seat, and a dropped person's seat once its hold has run out (or at once
 *  after a Leave). None while Allow joiners is off, before the start, or
 *  once the game is over. A connected person's seat is never one. */
export function nearbyClaimable(room: LocalRoom, now: number): number[] {
  const game = room.game;
  if (room.lobby !== null || !room.allowJoiners || game === null || game.gameOver || room.round === null) return [];
  return room.seats.flatMap((sd, i) =>
    sd.isBot || (!sd.connected && (sd.leftByChoice || !reserved(sd, now))) ? [i] : []);
}

/** The peek's answer for a nearby table: its people, and full once no seat
 *  is left for a newcomer. Before the start the open seats are the ones it
 *  does not list; in a game the seats it does not list are the ones a
 *  newcomer may take over (nearbyClaimable), so the joiner's seat picker
 *  offers exactly those. */
export function nearbyPeekJson(room: LocalRoom, now = 0, token: string | null = null): Json {
  const slots = room.slots();
  const claimable = room.lobby === null ? new Set(nearbyClaimable(room, now)) : new Set<number>();
  // a peek with a token: the seat that token resumes, for that asker alone;
  // null when the table does not know it. Never the token, nor anyone else's.
  const held = token ? slots.findIndex((s) => s !== null && !s.isBot && s.token === token) : -1;
  return {
    type: "room_seats",
    ...(token ? { held_seat: held >= 0 ? held : null } : {}),
    room: room.code,
    in_game: room.lobby === null,
    seats: slots.flatMap((s, i) => s === null || claimable.has(i) || (room.lobby !== null && s.isBot) ? [] : [{
      seat: i, name: s.name, is_bot: s.isBot, connected: room.lobby !== null ? s.connected : s.connected || s.isBot, team: i % 2,
      claimable: false, controller: room.lobby !== null ? "human" : controller(s), reserved_secs: null,
    }]),
    full: room.lobby === null ? claimable.size === 0 : room.lobby.every((s) => s !== null),
  };
}

export function roomJson(room: LocalRoom, seat: number, now = 0): Json {
  return {
    type: "room",
    room: room.code,
    you: seat,
    host: room.host,
    opener: room.host,
    start_level: room.startLevel,
    allow_joiners: room.allowJoiners,
    players: room.slots().flatMap((s, i) =>
      s === null ? [] : [{ seat: i, name: s.name, is_bot: s.isBot, connected: s.connected || s.isBot }]),
    ...(room.nearby ? { bot_level: room.botLevel } : {}),
    ...(room.lobby ? { nearby: nearbyJson(room, now) } : {}),
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

  /** The page's own pauses, told while a nearby host holds the watch. */
  private pauses: PauseWatch;

  constructor(opts: LocalServerOptions = {}) {
    this.clock = opts.clock ?? realClock;
    this.pauses = pauseWatch(this.clock);
    this.pauses.on((from, to) => this.paused(from, to));
    this.seed = opts.seed ?? randomSeed;
    this.remote = opts.remote ? new BotGate(opts.remote, this.clock) : null;
    this.autoplay = opts.autoplay ?? false;
  }

  /** Whether the server moves for `seat`: a bot seat, any seat under
   *  autoplay, or (server.py _auto_mode "takeover") a nearby seat whose owner
   *  left by choice or whose absence the watchdog has covered once. */
  drives(room: LocalRoom, seat: number): boolean {
    const sd = room.seats[seat];
    if (this.autoplay || sd.isBot) return true;
    if (!room.nearby) return false;
    // a present player: away, or this one decision ran out of time
    if (sd.connected) return sd.away || this.timedOutTurn(room, seat);
    return sd.botAnnounced || sd.leftByChoice;
  }

  /** The bot makes `seat`'s current decision because its clock ran out. */
  private timedOutTurn(room: LocalRoom, seat: number): boolean {
    return room.timeoutKey !== null && this.currentActor(room) === seat && room.timeoutKey === decisionKey(room);
  }

  // ----------------------------------------------------------- move timer
  /** server.py _sync_move_timer: start the clock of every seat that newly
   *  owes a decision, and look again when the earliest one runs out. */
  syncMoveTimer(room: LocalRoom): void {
    if (!room.nearby || room.game === null) return;
    if (!moveTimerLive(room)) {
      room.timerKey = null;
      for (const sd of room.seats) sd.turnStarted = null;
      return;
    }
    const key = decisionKey(room);
    const owing = new Set(owingSeats(room));
    const fresh = key !== room.timerKey;
    room.timerKey = key;
    let started = false;
    room.seats.forEach((sd, i) => {
      if (!owing.has(i)) sd.turnStarted = null;
      else if (fresh || sd.turnStarted === null) {
        sd.turnStarted = this.clock.now();
        started = true;
      }
    });
    if (started) this.moveCheckIn(room, MOVE_TIMER);
    // an away player owes no wait at the round end
    if (fresh && room.round?.phase === "round_end" && room.seats.some((sd, i) => owing.has(i) && sd.connected && sd.away)) {
      this.moveCheckIn(room, 0);
    }
  }

  /** A nearby seat back from a drop while it owes a decision: its clock
   *  takes up where it stood at the drop (no time away counts, so no strike
   *  comes of it), with at least RETURN_MIN left, and is checked again then. */
  private resumeMoveClock(room: LocalRoom, seat: Seat): void {
    if (!room.nearby || room.game === null || seat.connected || seat.leftAt === null || seat.turnStarted === null) return;
    const now = this.clock.now();
    const used = Math.max(0, seat.leftAt - seat.turnStarted);
    const left = Math.min(MOVE_TIMER, Math.max(RETURN_MIN, MOVE_TIMER - used));
    seat.turnStarted = now - (MOVE_TIMER - left);
    this.moveCheckIn(room, left);
  }

  /** The host page was stopped from `from` to `to`: no one at a nearby
   *  table could move, so every move clock, the declare window and a
   *  dropped seat's wait for its bot leave that time out, and no one is
   *  struck for the host's own pause. */
  private paused(from: number, to: number): void {
    for (const room of this.rooms.values()) {
      if (!room.nearby || room.closed || !room.game) continue;
      for (const sd of room.seats) {
        // a dropped seat's clock already stopped at its drop: both ends move
        if (!sd.connected && sd.leftAt !== null) sd.leftAt += pausedAfter(sd.leftAt, from, to);
        if (sd.turnStarted !== null) sd.turnStarted += pausedAfter(sd.turnStarted, from, to);
      }
      if (room.declareUntil !== null && room.declareUntil > from) room.declareUntil += to - from;
      this.broadcast(room);
    }
  }

  private moveCheckIn(room: LocalRoom, seconds: number): void {
    this.clock.setTimeout(() => this.moveTimerTick(room), Math.max(0, seconds));
  }

  /** server.py move_timer_tick: a present player whose clock ran out has the
   *  bot make that decision (a bury or a play), or is counted ready at the
   *  round end. */
  moveTimerTick(room: LocalRoom): void {
    if (room.closed || !room.game) return;
    // a pause that ends now moves the clocks on before they are read
    this.pauses.poll();
    this.syncMoveTimer(room);
    const game = room.game;
    const rnd = room.round;
    if (rnd === null || game.gameOver || !moveTimerLive(room)) return;
    const now = this.clock.now();
    let soonest = Infinity;
    const ranOut = (seat: number): boolean => {
      const sd = room.seats[seat];
      if (!timed(room, sd)) return false;
      const left = MOVE_TIMER - (now - sd.turnStarted!);
      if (left > 1e-9) {
        soonest = Math.min(soonest, left);
        return false;
      }
      return true;
    };
    if (rnd.phase === "round_end") {
      let readied = false;
      for (const s of owingSeats(room)) {
        const sd = room.seats[s];
        if (!sd.connected) continue;
        if (sd.away) {
          room.ready.add(s);
          readied = true;
        } else if (ranOut(s)) {
          room.ready.add(s);
          this.countTimeout(room, s);
          readied = true;
        }
      }
      if (readied) {
        this.advanceIfAllReady(room);
        this.broadcast(room);
      }
    } else {
      const seat = this.currentActor(room);
      if (seat !== null && !room.seats[seat].isBot && !room.seats[seat].away && ranOut(seat)) {
        room.timeoutKey = room.timerKey;
        this.kickBots(room);
      }
    }
    if (soonest < Infinity) this.moveCheckIn(room, soonest);
  }

  /** server.py _count_timeout: the bot made a decision a present player let run out. */
  private countTimeout(room: LocalRoom, seat: number): void {
    const sd = room.seats[seat];
    if (sd.away) return;
    sd.timeoutsInRow += 1;
    sd.timeoutsInRound += 1;
    if (sd.timeoutsInRow >= AWAY_IN_A_ROW || sd.timeoutsInRound >= AWAY_PER_ROUND) sd.away = true;
  }

  /** server.py _player_moved: a real decision (or im_back) from the seat's player. */
  private playerMoved(room: LocalRoom, seat: number): void {
    const sd = room.seats[seat];
    sd.away = false;
    sd.timeoutsInRow = 0;
  }

  /** A new client connection; `deliver` receives each frame as JSON text. */
  connect(deliver: (text: string) => void): LocalConnection {
    return new LocalConnection(this, deliver);
  }

  newRoom(startLevel: string, options: RoomOptions = {}): LocalRoom {
    const mint = options.nearby ? newNearbyCode : randomCode;
    let code = mint();
    while (this.rooms.has(code)) code = mint();
    const room = new LocalRoom(code, startLevel, new DeckRng(this.seed()), options);
    this.rooms.set(code, room);
    return room;
  }

  // -------------------------------------------------------------- fan-out
  enqueue(seat: Seat, payload: Json): void {
    seat.writer?.enqueue(payload);
  }

  broadcast(room: LocalRoom): void {
    this.syncMoveTimer(room);
    room.slots().forEach((seat, i) => {
      if (seat && seat.connected && !seat.isBot) {
        this.enqueue(seat, room.game && room.round ? stateFor(room, i, this.clock.now()) : roomJson(room, i, this.clock.now()));
      }
    });
  }

  chatPost(room: LocalRoom, entry: { seat: number; name: string; text: string; t: number } & Partial<Omit<ChatEntry, "id" | "room">>): void {
    room.chatSeq += 1;
    const full: ChatEntry = { ...entry, id: room.chatSeq, room: room.code };
    room.chat.push(full);
    if (room.chat.length > CHAT_KEEP) room.chat.splice(0, room.chat.length - CHAT_KEEP);
    for (const sd of room.slots()) if (sd) this.enqueue(sd, { type: "chat", ...full });
  }

  chatSystem(room: LocalRoom, text: string, event: SystemEvent): void {
    this.chatPost(room, { seat: -1, name: "", text, t: Date.now() / 1000, ...event });
  }

  attach(room: LocalRoom, seat: Seat, writer: Writer): number {
    this.resumeMoveClock(room, seat);
    seat.writer?.cancel();
    seat.gen += 1;
    seat.connected = true;
    seat.writer = writer;
    seat.leftAt = null;
    seat.leftByChoice = false;
    seat.botAnnounced = false;
    this.enqueue(seat, { type: "resume", token: seat.token, gen: seat.gen });
    this.enqueue(seat, chatHistory(room));
    return seat.gen;
  }

  detach(seat: Seat, room: LocalRoom | null, gen: number | null): void {
    if (gen !== null && gen !== seat.gen) return;
    if (room && room.seatIndex(seat) >= 0) room.ready.delete(room.seatIndex(seat));
    seat.connected = false;
    seat.leftAt = this.clock.now();
    seat.writer?.cancel();
    seat.writer = null;
    if (room?.nearby && room.game) this.watch(room);
  }

  /** server.py watchdog, for a nearby room: while some dropped human has
   *  not been covered yet, every WATCHDOG_POLL seconds check whether the
   *  turn holder's window has run out; if so the bot covers that seat from
   *  now on, announced once in chat. It stops when nobody is left to cover,
   *  so an idle room leaves no timer behind. */
  private watch(room: LocalRoom): void {
    if (room.watching) return;
    room.watching = true;
    this.clock.setTimeout(() => {
      room.watching = false;
      if (room.closed || !room.game) return;
      this.pauses.poll();
      const now = this.clock.now();
      const seat = this.currentActor(room);
      const sd = seat === null ? null : room.seats[seat];
      if (sd && !sd.isBot && !sd.connected && !sd.botAnnounced && !sd.leftByChoice
          && sd.leftAt !== null && now - sd.leftAt >= TAKEOVER_AFTER) {
        sd.botAnnounced = true;
        this.chatSystem(room, `bot is playing for ${sd.name} (disconnected)`, { event: "bot_playing_for", actor: sd.name });
        this.broadcast(room);
        this.kickBots(room);
      }
      if (room.seats.some((s) => !s.isBot && !s.connected && !s.botAnnounced && !s.leftByChoice)) this.watch(room);
    }, WATCHDOG_POLL);
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
        let stale = false;
        void this.pumpBots(room, () => { stale = true; }).finally(() => {
          room.pumping = false;
          // the turn moved on while a decision was being made (its owner
          // came back and played, say): whoever holds it now may be a bot,
          // and the kick that move made found the pump busy
          if (stale) this.kickBots(room);
        });
      }, 0);
    }
  }

  private async pumpBots(room: LocalRoom, overtaken: () => void): Promise<void> {
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
      // a present player's clock ran out: counted once the decision is made
      const timeout = !room.seats[seat].isBot && room.seats[seat].connected && !room.seats[seat].away
        && this.timedOutTurn(room, seat);
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
        overtaken();
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
        if (timeout) {
          room.timeoutKey = null;
          this.countTimeout(room, seat);
        }
        // the play just made may have ended the round
        if ((rnd.phase as string) === "round_end" && game.result === null) finishRoundOf(room, game);
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
    const res = await gate.ask(requestFor(rnd, room.actions, phase, seat, false, room.botLevel));
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
      const res = gate?.usable() ? await gate.ask(requestFor(rnd, room.actions, "declare", s, final, room.botLevel)) : null;
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
      let declared = false;
      if (cards) {
        try {
          declare(rnd, s, cards);
          room.logAction(["declare", s, [...cards]]);
          declared = true;
        } catch (e) {
          if (token) gate!.drop(token, "invalid");
          token = null;
          if (!(e instanceof IllegalPlay)) throw e;
        }
      }
      // no declaration is a decision too: its bot copy is kept like any other
      if (token) gate!.commit(token);
      // every declaration reaches the table as it commits, as on the game server
      if (declared) this.broadcast(room);
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
          continue;
        }
        this.broadcast(room);
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
      const [seat, idx, code] = dealNext(rnd);
      room.ids[seat].set(idx, code);
      if ((rnd.phase as string) === "declare") {
        // provisional, so the frames before the window opens (the last card,
        // the bots' last declarations) already count down
        room.declareUntil = this.clock.now() + DECLARE_GRACE;
      }
      room.logDeal(rnd.dealPos);
      // The card shows at once, as the game server deals; the bots decide
      // on it inside its gap, each declaration publishing as it commits.
      this.broadcast(room);
      const shown = this.clock.now();
      const declared = this.declares(room, [seat], false);
      if (declared instanceof Promise) {
        await declared;
        if (room.closed || room.round !== rnd) return;
      }
      if (room.round !== rnd) return;
      await sleep(this.clock, Math.max(0, DEAL_DELAY - (this.clock.now() - shown)));
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
      // the window moved on over a pause of the host page (paused())
      this.pauses.poll();
      if (room.declareUntil !== null && room.declareUntil > deadline) deadline = room.declareUntil;
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
  /** server.py's leave path: the last unready player leaving never holds
   *  the others at the round end. */
  advanceAfterLeave(room: LocalRoom): boolean {
    const advanced = this.advanceIfAllReady(room);
    if (advanced) this.broadcast(room);
    return advanced;
  }

  private advanceIfAllReady(room: LocalRoom): boolean {
    const game = room.game;
    const rnd = room.round;
    if (game === null || rnd === null || rnd.phase !== "round_end" || game.gameOver) return false;
    const pending = room.seats.some((sd, i) => !sd.isBot && sd.connected && !room.ready.has(i));
    if (pending || room.ready.size === 0) return false;
    room.ready.clear();
    for (const sd of room.seats) sd.timeoutsInRound = 0;
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

    if (t === "start_game") {
      // the creator's start, sent for them by create_room: the one way a
      // room's game begins
      if (room.game) throw new IllegalPlay("Game already started.");
      if (seat !== room.host) throw new IllegalPlay("Only the host can start.");
      if (room.lobby) {
        // a nearby lobby keeps its seat numbers: a bot takes each empty one
        room.seats = room.lobby.map((s, i) => s ?? new Seat(`Bot ${i}`, true, randomToken()));
        room.lobby = null;
      }
      // a bot plays every seat nobody took, named for its seat
      while (room.seats.length < 4) room.seats.push(new Seat(`Bot ${room.seats.length}`, true, randomToken()));
      // gamesToWin null: a table keeps playing; holding A scores a point
      room.game = newGame({ startLevel: room.startLevel, gamesToWin: null });
      startRound(room.game, room.decks.deck());
      room.indexRound();
      this.spawnDeal(room);
    } else if (room.lobby && typeof t === "string" && LOBBY.has(t)) {
      this.handleLobby(room, seat, msg);
    } else if (typeof t === "string" && LOBBY.has(t)) {
      // a room exists only to play its game, so a lobby control has nothing
      // left to set
      throw new IllegalPlay("Game already started.");
    } else if (game === null || rnd === null) {
      throw new IllegalPlay("Game not started.");
    } else if (t === "chat") {
      const text = String(msg.text ?? "").trim().slice(0, CHAT_MAX_LEN);
      if (!text) return;
      this.chatPost(room, { seat, name: room.seats[seat].name, text, t: Date.now() / 1000 });
      return;
    } else if (t === "allow_joiners") {
      if (seat !== room.host) throw new IllegalPlay("Only the table's opener sets Allow joiners.");
      room.allowJoiners = msg.on === true;
    } else if (t === "im_back") {
      // the player is back: the bot stops playing for the seat, and a
      // decision it owes now gets a fresh clock
      const sd = room.seats[seat];
      const wasAway = sd.away;
      this.playerMoved(room, seat);
      if (wasAway && sd.turnStarted !== null) {
        sd.turnStarted = this.clock.now();
        this.moveCheckIn(room, MOVE_TIMER);
      }
    } else if (t === "declare") {
      const codes = room.codesFor(seat, cardIds(msg));
      declare(rnd, seat, codes);
      room.logAction(["declare", seat, [...codes]]);
      this.playerMoved(room, seat);
    } else if (t === "pass_declare") {
      const wasPassed = rnd.passed.includes(seat);
      passDeclare(rnd, seat);
      if (!wasPassed) room.logAction(["pass", seat]);
      this.playerMoved(room, seat);
    } else if (t === "bury") {
      room.syncKitty();
      const ids = cardIds(msg);
      const codes = room.codesFor(seat, ids);
      bury(rnd, seat, codes);
      room.logAction(["bury", seat, [...codes]]);
      room.removeIds(seat, ids);
      this.playerMoved(room, seat);
    } else if (t === "play") {
      const ids = cardIds(msg);
      const codes = room.codesFor(seat, ids);
      // a failed throw records fewer cards than were sent
      const played = applyPlay(rnd, seat, codes);
      room.logAction(["play", seat, [...codes]]);
      const same = [...played].sort().join(",") === [...codes].sort().join(",");
      if (same) room.removeIds(seat, ids);
      else room.removeCodes(seat, played);
      this.playerMoved(room, seat);
    } else if (t === "next_round") {
      if (rnd.phase !== "round_end") throw new IllegalPlay("Round not finished.");
      if (game.gameOver) throw new IllegalPlay("Game is over.");
      room.ready.add(seat);
      this.playerMoved(room, seat);
      if (!this.advanceIfAllReady(room)) this.broadcast(room);
    } else {
      throw new IllegalPlay(`Unknown action: ${t === undefined ? "None" : String(t)}`);
    }

    rnd = room.round;
    if (rnd && rnd.phase === "round_end" && room.game && room.game.result === null) finishRoundOf(room, room.game);
  }

  /** A nearby lobby's controls (tables.py LOBBY), before its game. */
  private handleLobby(room: LocalRoom, seat: number, msg: Json): void {
    const lobby = room.lobby!;
    const t = msg.type;
    if (t === "table_start" || t === "table_start_now" || t === "table_start_bots") {
      // only the host starts, with everyone seated (as an online table's
      // owner); a guest's table_start is an older page's Start, which
      // changes nothing: joining is all a guest does
      if (seat !== room.host) {
        if (t === "table_start") return;
        throw new IllegalPlay("Only the host can start.");
      }
      if (msg.on === false) return;
      this.startNearby(room);
    } else if (t === "table_start_level") {
      if (seat !== room.host) throw new IllegalPlay("Only the table's opener sets the starting level.");
      const level = msg.level ?? msg.start_level;
      if (typeof level !== "string" || !(RANKS as readonly string[]).includes(level)) throw new IllegalPlay("Unknown starting level.");
      room.startLevel = level;
    } else if (t === "table_bot_level") {
      if (seat !== room.host) throw new IllegalPlay("Only the table's opener sets the bots.");
      const level = msg.level ?? msg.bot_level;
      if (typeof level !== "string" || !(BOT_LEVELS as readonly string[]).includes(level)) throw new IllegalPlay("Bots is Beginner, Standard or Advanced.");
      room.botLevel = level as BotLevel;
    } else if (t === "table_move") {
      const to = msg.seat;
      const from = msg.from === undefined || msg.from === null ? seat : msg.from;
      if (typeof to !== "number" || !Number.isInteger(to) || to < 0 || to > 3) throw new IllegalPlay("No such seat.");
      if (typeof from !== "number" || !Number.isInteger(from) || from < 0 || from > 3 || lobby[from] === null) throw new IllegalPlay("No such seat.");
      if (from !== seat && seat !== room.host) throw new IllegalPlay("Only the table's opener moves other players.");
      if (lobby[to] !== null) throw new IllegalPlay("That seat is taken.");
      lobby[to] = lobby[from];
      lobby[from] = null;
      if (room.host === from) room.host = to;
    }
  }

  /** The nearby lobby's game begins: bots take the open seats. */
  startNearby(room: LocalRoom): void {
    if (!room.lobby) return;
    this.setBotsAt(room, null);
    this.handleAction(room, room.host, { type: "start_game" });
    // a joiner whose socket dropped in the lobby is covered after its window
    if (room.seats.some((s) => !s.isBot && !s.connected)) this.watch(room);
  }

  /** A lobby seat's link dropped: the seat is its owner's for LOBBY_SEAT_HOLD, to come back by token; then it
   *  is free again, so a phone that is gone never holds a place at the table. */
  lobbyDropped(room: LocalRoom, seat: Seat): void {
    const gen = seat.gen;
    this.pauses.after(() => {
      if (room.closed || !room.lobby || seat.connected || seat.gen !== gen) return;
      const i = room.lobby.indexOf(seat);
      if (i < 0 || i === room.host) return;
      room.lobby[i] = null;
      this.chatSystem(room, `${seat.name} left`, { event: "left", actor: seat.name });
      this.syncBotsTimer(room);
      this.broadcast(room);
      this.kickBots(room);
    }, LOBBY_SEAT_HOLD);
    this.broadcast(room);
    this.kickBots(room);
  }

  /** A nearby joiner's seat its phone never showed it had (host.ts
   *  confirmBy), with its link gone: given up as by that joiner's Leave. */
  giveUpNearbySeat(room: LocalRoom, seat: Seat): void {
    const idx = room.seatIndex(seat);
    if (room.closed || idx < 0 || idx === room.host || seat.connected) return;
    this.chatSystem(room, `${seat.name} left`, { event: "left", actor: seat.name });
    if (room.lobby) {
      room.lobby[idx] = null;
      this.syncBotsTimer(room);
    } else seat.leftByChoice = true;
    this.broadcast(room);
    this.kickBots(room);
  }

  /** A nearby seat's link went: the chat says so once the seat has been
   *  gone DISCONNECT_NOTICE, so a link that is back at once leaves the chat
   *  as it was. */
  noticeGone(room: LocalRoom, seat: Seat): void {
    const gen = seat.gen;
    this.clock.setTimeout(() => {
      if (room.closed || seat.connected || seat.gen !== gen || seat.goneAnnounced || seat.leftByChoice) return;
      if (room.seatIndex(seat) < 0) return;
      seat.goneAnnounced = true;
      this.chatSystem(room, `${seat.name} disconnected`, { event: "disconnected", actor: seat.name });
    }, DISCONNECT_NOTICE);
  }

  /** The lobby's bot timer follows who sits there: it runs from the moment
   *  a second person sits, and stops when the host is alone again. */
  syncBotsTimer(room: LocalRoom): void {
    if (!room.lobby) return;
    const people = room.lobby.filter((s) => s !== null && !s.isBot).length;
    if (people < 2) this.setBotsAt(room, null);
    else if (room.botsAt === null) this.setBotsAt(room, this.clock.now() + NEARBY_BOT_FILL);
  }

  private setBotsAt(room: LocalRoom, at: number | null): void {
    if (room.botsAt === at) return;
    room.botsAt = at;
    const gen = ++room.botsGen;
    if (at === null) return;
    this.clock.setTimeout(() => {
      if (room.botsGen !== gen || room.closed || !room.lobby) return;
      this.startNearby(room);
      this.broadcast(room);
      this.kickBots(room);
    }, Math.max(0, at - this.clock.now()));
  }

  closeRoom(room: LocalRoom): void {
    if (!room.closed) {
      room.closed = true;
      const done = room.onClosed;
      room.onClosed = null;
      done?.();
    }
    this.rooms.delete(room.code);
  }

  /** The nearby host's table ends: everyone else seated is told, and their
   *  writers drain before the room goes. There is no host migration, since
   *  that would copy every hand to another phone. */
  endNearbyRoom(room: LocalRoom, host: Seat): void {
    for (const sd of room.humans()) {
      if (sd !== host && sd.connected) this.enqueue(sd, { type: "left", reason: "host_left", message: NEARBY_COPY.hostLeft });
    }
    this.closeRoom(room);
  }

  /** The host phone was away too long: the table ends for every seat,
   *  the host's own page included. */
  endNearbyRoomForAll(room: LocalRoom): void {
    if (room.closed) return;
    const host = room.slots()[room.host];
    if (host && host.connected) this.enqueue(host, { type: "left" });
    if (host) this.endNearbyRoom(room, host);
    else this.closeRoom(room);
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

  /** A frame sent straight to the socket, outside any seat's writer.
   *  `last`: the connection closes right after it, and it still goes out, as
   *  server.py sends its error before it ends the socket. */
  private sendDirect(payload: Json, last = false): void {
    const text = JSON.stringify(payload);
    this.server.clock.setTimeout(() => {
      if (last || !this.closed) this.deliver(text);
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
    if (retired(msg)) {
      // the server's own names are not a client's
      this.sendDirect({ type: "error", code: "retired", message: RETIRED_MESSAGE });
      return;
    }
    // A canonical name becomes the message this server handles before any
    // check reads its type, so each check applies to it.
    const canonical = typeof msg.type === "string" && CANONICAL.has(msg.type) ? msg.type : null;
    if (canonical !== null) {
      if (this.room === null || this.me === null) {
        const local = forQueue(msg);
        if (local === null) return;
        msg = local;
      } else {
        msg = forRoom(msg);
      }
    }
    const t = msg.type;
    if (this.room === null || this.me === null) {
      if (t === "create_room") {
        let level = msg.start_level;
        if (level === undefined || level === null) level = RANKS[0];
        else if (typeof level !== "string" || !(RANKS as readonly string[]).includes(level)) {
          this.sendDirect({ type: "error", code: "bad_start_level", message: "Unknown starting level." });
          return;
        }
        // the table's Bots, as a casual table's (matchmaking.py): Standard
        // unless it names Advanced, a nearby table's as a solo one's
        const bots = msg.bot_level ?? DEFAULT_BOT_LEVEL;
        if (typeof bots !== "string" || !(BOT_LEVELS as readonly string[]).includes(bots)) {
          this.sendDirect({ type: "error", code: "bad_setting", message: "Bots is Beginner, Standard or Advanced." });
          return;
        }
        const nearby = msg.nearby === true;
        const room = server.newRoom(level as string, { nearby, botLevel: bots as BotLevel });
        const me = new Seat(nearby ? nearbyName(msg.name, 0) : String(msg.name || "Player"), false, randomToken());
        if (room.lobby) room.lobby[0] = me;
        else room.seats.push(me);
        this.room = room;
        this.me = me;
        this.attach(room, me);
        // the client saves a room only from a room frame, so one goes out
        // before the start begins the game
        server.broadcast(room);
        // a nearby table waits in its lobby for the host's Start
        if (!nearby) this.startCreatedRoom(room, me);
      } else if (t === "peek_room") {
        this.sendDirect({ type: "error", code: "room_not_found", message: "Room not found." });
      } else if (t === "join_room") {
        // Offline there is one player: a join can only resume this page's
        // own seat, by its token.
        const room = server.rooms.get(String(msg.room ?? "").toUpperCase());
        const tok = msg.token;
        let seat = room && typeof tok === "string" && tok
          ? room.humans().find((s) => s.token === tok)
          : undefined;
        if (room && !seat && room.nearby && typeof tok === "string" && tok && (msg.seat === undefined || msg.seat === null)) {
          // a seated phone's resume whose token the table no longer knows
          // (its seat was taken over, or freed): it is refused, never seated
          // in some other seat without the player's pick, and the phone
          // goes back to the seat picker
          this.sendDirect({ type: "error", code: "room_not_found", message: "Seat no longer exists." });
          return;
        }
        if (room && seat && room.nearby && msg.chosen === true && this.moveChosen(room, seat, msg)) return;
        if (room && !seat && room.nearby && !room.lobby) {
          // a game in progress: a newcomer takes over a seat a bot plays, at
          // once, as the online by-code join does (server.py _join_room)
          this.takeOver(room, msg);
          return;
        }
        if (room && !seat && room.nearby) {
          // a nearby lobby seats a newcomer in its first free seat
          const want = msg.seat;
          const free = typeof want === "number" && Number.isInteger(want) && want >= 0 && want < 4 && room.lobby![want] === null
            ? want : room.lobby!.indexOf(null);
          if (free < 0) {
            this.sendDirect({ type: "error", code: "room_full", message: NEARBY_COPY.full });
            return;
          }
          seat = new Seat(nearbyName(msg.name, free), false, randomToken());
          room.lobby![free] = seat;
          room.joinedOnce = true;
          this.room = room;
          this.me = seat;
          this.attach(room, seat);
          server.syncBotsTimer(room);
          server.chatSystem(room, `${seat.name} joined`, { event: "joined", actor: seat.name });
          server.broadcast(room);
          return;
        }
        if (!room || !seat) {
          this.sendDirect({ type: "error", code: "room_not_found", message: "Room not found." });
          return;
        }
        this.room = room;
        this.me = seat;
        this.attach(room, seat);
        if (!room.nearby || seat.goneAnnounced) server.chatSystem(room, `${seat.name} reconnected`, { event: "reconnected", actor: seat.name });
        seat.goneAnnounced = false;
        server.kickBots(room);
        server.broadcast(room);
      } else {
        this.sendDirect({ type: "error", code: "no_room", message: "Join a room first." });
      }
      return;
    }

    const room = this.room;
    const me = this.me;
    if (this.myGen !== me.gen) {
      this.sendDirect({ type: "error", code: "stale_connection", message: "This connection was replaced by a newer one." }, true);
      this.close();
      return;
    }
    if (t === "leave_room" && room.nearby) {
      this.leaveNearby(room, me);
      return;
    }
    if (t === "leave_room") {
      server.chatSystem(room, `${me.name} left`, { event: "left", actor: me.name });
      server.detach(me, room, this.myGen);
      if (!room.seats.some((s) => !s.isBot && s.connected)) {
        // nobody is left to play the human seat: the game ends here
        server.closeRoom(room);
      }
      this.sendDirect({ type: "left" });
      this.room = null;
      this.me = null;
      return;
    }
    const seatIdx = room.seatIndex(me);
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

  /** A held seat's phone back by its token with another seat picked: the
   *  player moves to that seat when it is free, and the one held is given
   *  up, so the player sits in one seat. Before the start the lobby seat
   *  moves (as a seat move); in a game the held seat is left by choice for
   *  its bot and the picked one is taken over. False (the seat is resumed
   *  in place) when the pick is the held seat, or not free. */
  private moveChosen(room: LocalRoom, held: Seat, msg: Json): boolean {
    const want = msg.seat;
    const from = room.seatIndex(held);
    if (typeof want !== "number" || !Number.isInteger(want) || want < 0 || want > 3 || want === from || held.connected) return false;
    if (room.lobby) {
      if (room.lobby[want] !== null) return false;
      room.lobby[want] = held;
      room.lobby[from] = null;
      return false;
    }
    if (!nearbyClaimable(room, this.server.clock.now()).includes(want)) return false;
    // the held seat cannot be taken back by the old token, and its bot plays it
    held.token = randomToken();
    held.leftByChoice = true;
    this.takeOver(room, msg);
    return true;
  }

  /** A newcomer at a nearby game in progress takes the seat it picked
   *  when that one may be taken, else the first that may (the hello's
   *  rule), from this moment on. The seat changes hands in place: its hand,
   *  its card ids and its place in the trick stay, and the bot stops
   *  playing it. A new token, so whoever held the seat before cannot take
   *  it back by theirs. No seat (every seat a connected person's or held,
   *  or Allow joiners off) is the table-full refusal. */
  private takeOver(room: LocalRoom, msg: Json): void {
    const server = this.server;
    const claimable = nearbyClaimable(room, server.clock.now());
    const want = msg.seat;
    const pick = typeof want === "number" && claimable.includes(want) ? want : claimable[0];
    if (pick === undefined) {
      this.sendDirect({ type: "error", code: "room_full", message: NEARBY_COPY.full });
      return;
    }
    const seat = room.seats[pick];
    const took = seat.name;
    const fromPerson = !seat.isBot;
    seat.isBot = false;
    seat.name = nearbyName(msg.name, pick);
    seat.token = randomToken();
    seat.away = false;
    seat.timeoutsInRow = 0;
    seat.timeoutsInRound = 0;
    seat.turnStarted = null;
    room.joinedOnce = true;
    this.room = room;
    this.me = seat;
    this.attach(room, seat);
    server.chatSystem(room, fromPerson ? `${seat.name} took over for ${took} (offline)` : `${seat.name} took ${took}'s seat`,
                      { event: fromPerson ? "took_over" : "took_seat", actor: seat.name, target: took, target_is_bot: !fromPerson });
    server.kickBots(room);
    server.broadcast(room);
  }

  /** Every `create_room`, with or without `start: true`: the creator's own
   *  `start_game`, sent for them, so every start check applies and a bot
   *  takes every empty seat. A refusal discards the room: the creator gets
   *  the `error`, then `left`, through its writer so they arrive in order. */
  private startCreatedRoom(room: LocalRoom, me: Seat): void {
    const server = this.server;
    try {
      server.handleAction(room, room.seats.indexOf(me), { type: "start_game" });
    } catch (e) {
      server.enqueue(me, { type: "error", message: e instanceof IllegalPlay ? e.message : "Invalid request." });
      server.enqueue(me, { type: "left" });
      server.closeRoom(room);
      this.room = null;
      this.me = null;
      return;
    }
    server.broadcast(room);
    server.kickBots(room);
  }

  /** A Leave at a nearby table. The host's ends the table for everyone. A
   *  joiner's frees their lobby seat before the game; during it the seat
   *  stays theirs to reclaim by token and the bot covers it at once
   *  (server.py left_by_choice), and the round-end quorum is checked again. */
  private leaveNearby(room: LocalRoom, me: Seat): void {
    const server = this.server;
    const idx = room.seatIndex(me);
    server.chatSystem(room, `${me.name} left`, { event: "left", actor: me.name });
    server.detach(me, room, this.myGen);
    if (idx === room.host) {
      server.endNearbyRoom(room, me);
    } else if (room.lobby) {
      room.lobby[idx] = null;
      server.syncBotsTimer(room);
      server.broadcast(room);
      server.kickBots(room);
    } else {
      me.leftByChoice = true;
      if (!server.advanceAfterLeave(room)) server.broadcast(room);
      server.kickBots(room);
    }
    this.sendDirect({ type: "left" });
    this.room = null;
    this.me = null;
  }

  /** The socket closed: the seat waits, and a join with its token resumes it. */
  close(): void {
    if (this.closed) return;
    const room = this.room;
    const me = this.me;
    if (room && me && room.nearby && !room.closed && me.connected && this.myGen === me.gen) {
      // server.py's socket-closed path: the others are told, and the
      // round-end quorum no longer waits on this seat
      const server = this.server;
      server.detach(me, room, this.myGen);
      server.noticeGone(room, me);
      if (room.lobby) server.lobbyDropped(room, me);
      else if (room.humans().some((s) => s.connected) && !server.advanceAfterLeave(room)) server.broadcast(room);
    } else if (room && me) this.server.detach(me, room, this.myGen);
    this.closed = true;
    this.room = null;
    this.me = null;
  }

  /** For tests and the e2e harness: the room this connection is seated in. */
  get currentRoom(): LocalRoom | null {
    return this.room;
  }

  /** The seat this connection holds, or null. */
  get seat(): Seat | null {
    return this.me;
  }
}
