// Rebuild one round, as its viewer saw it, from the filtered room-log events
// that `GET /api/me/games/{id}/rounds/{n}` returns. Pure: no socket, no fetch.
// The records carry the room log's own keys (server.py `log_event`):
//   round_start {deck, banker, trump_rank, levels, players[{seat,name,is_bot}]}
//   declare {seat, cards}   trump {suit ("NT" or a letter), rank, banker, declared}
//   bury {seat, cards}      play {seat, cards}   trick {winner, points, plays}
//   round_end {attacker_points, kitty, kitty_points, winner_team, level_change,
//              new_levels, next_banker, game_over, games_won, point_scored}
// Hidden cards are tolerated in every form the filter might use: a deck
// position that is null (or "?"), a missing `deck` with a `hand` list for the
// viewer instead, a bury without cards. Unknown cards are never invented: a
// seat whose hand is unknown keeps only a card count.
import type { HandCard, Trick } from "../protocol";
import { compareCards } from "./cards";

const HAND_SIZE = 25;
const DEALT = 4 * HAND_SIZE;

export interface RoundEvent {
  e: string;
  [key: string]: unknown;
}

export interface RoundReplayDoc {
  game_id: string;
  round: number;
  seat: number;
  players: string[];
  finished: boolean;
  events: RoundEvent[];
}

export interface RoundEndRecord {
  attacker_points: number;
  kitty?: string[] | null;
  kitty_points: number;
  winner_team: 0 | 1;
  level_change: number;
  new_levels: [string, string];
  next_banker: number;
  game_over: boolean;
  games_won: [number, number];
  point_scored: boolean;
}

export interface ReplayPlayer {
  seat: number;
  name: string;
  is_bot: boolean;
}

export interface ReplaySetup {
  seat: number;
  players: ReplayPlayer[];
  trumpRank: string;
  /** "NT", a suit letter, or null when the log has no trump record. */
  trumpSuit: string | null;
  banker: number | null;
  trumpDeclared: boolean;
  declarations: { seat: number; cards: string[] }[];
  levels: [string, string];
  /** The viewer's own bury, when the viewer was the banker. */
  ownBury: string[] | null;
  /** The kitty as dealt, when the viewer may see it. */
  kitty: string[] | null;
  finished: boolean;
}

export type FrameKind = "deal" | "start" | "play" | "end";

export interface ReplayFrame {
  kind: FrameKind;
  /** 1-based trick number; 0 before the first play. */
  trickNo: number;
  /** Index into the trick's plays for a "play" frame; -1 otherwise. */
  playNo: number;
  trick: Trick | null;
  /** Set once the trick is complete. */
  winner: number | null;
  trickPoints: number | null;
  /** The viewer's hand at this step. */
  hand: HandCard[];
  /** Every seat's hand where it is known (the viewer's always; others only
   *  in a finished round), else null. */
  hands: (HandCard[] | null)[];
  cardsLeft: number[];
  attackerPoints: number;
  /** Whose play comes next; null between tricks' resolution and at the end. */
  turn: number | null;
  result: RoundEndRecord | null;
}

export interface Replay {
  setup: ReplaySetup;
  frames: ReplayFrame[];
  /** Number of tricks with at least one play. */
  trickCount: number;
  /** Whether the log reached round_end. */
  complete: boolean;
}

function cardList(v: unknown): string[] | null {
  if (!Array.isArray(v)) return null;
  if (v.some((c) => typeof c !== "string" || c === "?" || c === "")) return null;
  return v as string[];
}

function known(code: unknown): code is string {
  return typeof code === "string" && code !== "?" && code !== "";
}

type Hands = (HandCard[] | null)[];

function removeCards(hand: HandCard[] | null, cards: string[]): HandCard[] | null {
  if (!hand) return hand;
  const next = [...hand];
  for (const code of cards) {
    // A card the viewer never saw (a kitty card hidden by the filter) is not
    // in the list; skip it rather than drop a different card.
    for (let i = next.length - 1; i >= 0; i--) {
      if (next[i].code === code) {
        next.splice(i, 1);
        break;
      }
    }
  }
  return next;
}

function teamOf(seat: number): 0 | 1 {
  return (seat % 2) as 0 | 1;
}

function asPlayers(v: unknown, names: string[]): ReplayPlayer[] {
  const list = Array.isArray(v) ? (v as Partial<ReplayPlayer>[]) : [];
  return [0, 1, 2, 3].map((seat) => {
    const p = list.find((x) => x && x.seat === seat);
    return {
      seat,
      name: (p?.name as string | undefined) ?? names[seat] ?? `Seat ${seat + 1}`,
      is_bot: Boolean(p?.is_bot),
    };
  });
}

export function buildReplay(doc: RoundReplayDoc): Replay {
  const evs = doc.events;
  const seat = doc.seat;
  const rs = evs.find((e) => e.e === "round_start");
  const tr = evs.find((e) => e.e === "trump");
  const end = evs.find((e) => e.e === "round_end") as unknown as RoundEndRecord | undefined;

  const trumpRank = String(tr?.rank ?? rs?.trump_rank ?? "2");
  const trumpSuit = tr && typeof tr.suit === "string" ? tr.suit : null;
  const banker = typeof tr?.banker === "number" ? tr.banker
    : typeof rs?.banker === "number" ? rs.banker : null;
  const declarations = evs.filter((e) => e.e === "declare")
    .map((e) => ({ seat: Number(e.seat), cards: cardList(e.cards) ?? [] }));
  const levelsRaw = Array.isArray(rs?.levels) ? (rs.levels as string[]) : ["2", "2"];
  const order = (a: HandCard, b: HandCard) => compareCards(a.code, b.code, trumpSuit, trumpRank);

  // The deal: deck position i goes to seat i % 4; ids are deck positions so
  // they stay stable as the hand shrinks.
  const deck = Array.isArray(rs?.deck) ? (rs.deck as unknown[]) : null;
  const hands: Hands = [null, null, null, null];
  for (let s = 0; s < 4; s++) {
    if (!deck) continue;
    const mine: HandCard[] = [];
    let complete = true;
    for (let i = s; i < Math.min(DEALT, deck.length); i += 4) {
      const code = deck[i];
      if (known(code)) mine.push({ id: i, code });
      else complete = false;
    }
    if (mine.length === 0) continue;
    // Another seat's hand is shown only when every card of it is known; the
    // viewer's own partial hand still beats none.
    if (complete || s === seat) hands[s] = mine;
  }
  const ownList = cardList(rs?.hand);
  if (!hands[seat] && ownList) hands[seat] = ownList.map((code, i) => ({ id: 1000 + i, code }));
  let kitty: string[] | null = null;
  if (deck && deck.length >= DEALT + 8) {
    const k = deck.slice(DEALT, DEALT + 8);
    if (k.every(known)) kitty = k as string[];
  }
  if (!kitty) kitty = cardList(rs?.kitty);

  const sortAll = (hs: Hands): Hands => hs.map((h) => (h ? [...h].sort(order) : null));
  const cardsLeft = [HAND_SIZE, HAND_SIZE, HAND_SIZE, HAND_SIZE];
  const frames: ReplayFrame[] = [];
  const snapshot = (partial: Omit<ReplayFrame, "hand" | "hands" | "cardsLeft">, hs: Hands): ReplayFrame => {
    const sorted = sortAll(hs);
    return { ...partial, hands: sorted, hand: sorted[seat] ?? [], cardsLeft: [...cardsLeft] };
  };

  let current: Hands = hands.map((h) => (h ? [...h] : null));
  frames.push(snapshot({ kind: "deal", trickNo: 0, playNo: -1, trick: null, winner: null,
                         trickPoints: null, attackerPoints: 0, turn: null, result: null }, current));

  // The banker picks up the kitty and buries eight.
  const buryEv = evs.find((e) => e.e === "bury");
  const buried = cardList(buryEv?.cards);
  const ownBury = buried && banker === seat ? buried : null;
  if (banker !== null) {
    if (kitty && current[banker]) {
      current[banker] = [...current[banker]!, ...kitty.map((code, i) => ({ id: DEALT + i, code }))];
    }
    if (buried) current[banker] = removeCards(current[banker], buried);
    else if (banker !== seat) current[banker] = null;   // the kept cards are unknown
  }
  frames.push(snapshot({ kind: "start", trickNo: 0, playNo: -1, trick: null, winner: null,
                         trickPoints: null, attackerPoints: 0, turn: banker, result: null }, current));

  let trick: Trick | null = null;
  let trickDone = false;
  let trickNo = 0;
  let attackerPoints = 0;
  for (const ev of evs) {
    if (ev.e === "play") {
      const s = Number(ev.seat);
      const cards = cardList(ev.cards) ?? [];
      if (trick === null || trickDone) {
        trick = { leader: s, plays: [] };
        trickDone = false;
        trickNo += 1;
      }
      trick = { ...trick, plays: [...trick.plays, { seat: s, cards }] };
      current = current.map((h, i) => (i === s ? removeCards(h, cards) : h));
      cardsLeft[s] = Math.max(0, cardsLeft[s] - cards.length);
      frames.push(snapshot({ kind: "play", trickNo, playNo: trick.plays.length - 1, trick,
                             winner: null, trickPoints: null, attackerPoints,
                             turn: trick.plays.length < 4 ? (s + 1) % 4 : null, result: null }, current));
    } else if (ev.e === "trick" && trick && !trickDone) {
      trickDone = true;
      const winner = Number(ev.winner);
      const points = Number(ev.points) || 0;
      if (banker !== null && teamOf(winner) !== teamOf(banker)) attackerPoints += points;
      const last = frames[frames.length - 1];
      frames[frames.length - 1] = { ...last, winner, trickPoints: points, attackerPoints, turn: winner };
    } else if (ev.e === "round_end") {
      const result = ev as unknown as RoundEndRecord;
      frames.push(snapshot({ kind: "end", trickNo, playNo: -1, trick,
                             winner: frames[frames.length - 1].winner,
                             trickPoints: frames[frames.length - 1].trickPoints,
                             attackerPoints: Number(result.attacker_points) || attackerPoints,
                             turn: null, result }, current));
    }
  }

  return {
    setup: {
      seat,
      players: asPlayers(rs?.players, doc.players),
      trumpRank,
      trumpSuit,
      banker,
      trumpDeclared: Boolean(tr?.declared ?? declarations.length > 0),
      declarations,
      levels: [String(levelsRaw[0]), String(levelsRaw[1])],
      ownBury,
      kitty: kitty ?? cardList(end?.kitty),
      finished: doc.finished && end !== undefined,
    },
    frames,
    trickCount: trickNo,
    complete: end !== undefined,
  };
}

/** First frame of trick `n` (1-based), or the last frame when out of range. */
export function frameOfTrick(replay: Replay, n: number): number {
  const i = replay.frames.findIndex((f) => f.kind === "play" && f.trickNo === n && f.playNo === 0);
  return i >= 0 ? i : replay.frames.length - 1;
}

/** Step to the previous / next trick boundary: back goes to the start of the
 *  current trick (or of the previous one if already there); forward goes to
 *  the last play of the current trick (or of the next one if already there). */
export function stepTrick(replay: Replay, at: number, dir: -1 | 1): number {
  const frames = replay.frames;
  const last = frames.length - 1;
  if (dir === 1) {
    for (let i = at + 1; i <= last; i++) {
      const f = frames[i];
      const next = frames[i + 1];
      if (f.kind === "end") return i;
      if (f.kind === "play" && (!next || next.kind !== "play" || next.trickNo !== f.trickNo)) return i;
    }
    return last;
  }
  for (let i = at - 1; i >= 0; i--) {
    const f = frames[i];
    if (f.kind === "start" || (f.kind === "play" && f.playNo === 0)) return i;
  }
  return 0;
}
