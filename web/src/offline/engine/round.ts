// One round of Sheng Ji: deal, declare, bury, tricks, scoring. A port of
// server/shengji/engine/round.py. The state is a plain JSON-serializable
// object; functions mutate it in place (clone with structuredClone to explore
// alternatives). The deck order is an input: callers own the shuffle.
import {
  BJ,
  type Card,
  type EffSuit,
  LJ,
  type Ordering,
  type TrumpSuit,
  cardRank,
  cardSuit,
  isJoker,
  naturalCompare,
  orderingFor,
  totalPoints,
} from "./cards";
import { counter, decompose } from "./combos";
import {
  EngineAssertion,
  IllegalPlay,
  beats,
  checkInHand,
  countLeadCandidates,
  countSubmultisets,
  leadCandidates,
  submultisets,
  uniformSuit,
  validateFollow,
  validateLead,
} from "./legal";

export const KITTY_SIZE = 8;
export const HAND_SIZE = 25;
/** The last-trick kitty bonus is the buried points x 2 x the lead's card count. */
export const KITTY_MULTIPLIER = 2;
/** A failed-throw notice outlives this many further accepted plays. */
export const NOTICE_PLAYS = 8;

export type Phase = "deal" | "declare" | "bury" | "play" | "round_end";

export interface TrickPlay {
  seat: number;
  cards: Card[];
}

export interface Trick {
  leader: number;
  plays: TrickPlay[];
  winner: number | null;
  points: number;
}

export interface Declaration {
  seat: number;
  cards: Card[];
  /** 1 single rank card, 2 rank pair, 3 little-joker pair, 4 big-joker pair. */
  strength: number;
}

export interface FailedThrowNotice {
  id: number;
  kind: "failed_throw";
  seat: number;
  attempted: Card[];
  forced: Card[];
}

export interface RoundState {
  deck: Card[];
  hands: Card[][];
  kitty: Card[];
  dealPos: number;
  trumpRank: string;
  /** null only on a game's first round until the declare window closes. */
  banker: number | null;
  firstRound: boolean;
  phase: Phase;
  turn: number | null;
  declaration: Declaration | null;
  passed: number[];
  trumpSuit: TrumpSuit;
  trumpIsNt: boolean;
  buried: Card[];
  trick: Trick | null;
  lastTrick: Trick | null;
  history: Trick[];
  attackerPoints: number;
  kittyBonus: number;
  lastTrickWinner: number | null;
  message: string | null;
  notice: FailedThrowNotice | null;
  noticePlaysLeft: number;
  noticeSeq: number;
}

/** A new round in the deal phase. `deck` is the 108-card order to deal. */
export function newRound(deck: readonly Card[], trumpRank: string, banker: number | null): RoundState {
  if (deck.length !== 4 * HAND_SIZE + KITTY_SIZE) throw new Error(`deck must have 108 cards, got ${deck.length}`);
  return {
    deck: [...deck],
    hands: [[], [], [], []],
    kitty: deck.slice(4 * HAND_SIZE),
    dealPos: 0,
    trumpRank,
    banker,
    firstRound: banker === null,
    phase: "deal",
    turn: null,
    declaration: null,
    passed: [],
    trumpSuit: null,
    trumpIsNt: false,
    buried: [],
    trick: null,
    lastTrick: null,
    history: [],
    attackerPoints: 0,
    kittyBonus: 0,
    lastTrickWinner: null,
    message: null,
    notice: null,
    noticePlaysLeft: 0,
    noticeSeq: 0,
  };
}

/** The round's Ordering; defined once the declare window has closed. */
export function roundOrdering(state: RoundState): Ordering {
  if (state.phase === "deal" || state.phase === "declare") throw new EngineAssertion("trump is not fixed yet");
  return orderingFor(state.trumpSuit, state.trumpRank);
}

export function isAttacker(state: RoundState, seat: number): boolean {
  if (state.banker === null) throw new EngineAssertion("no banker");
  return seat % 2 !== state.banker % 2;
}

// ------------------------------------------------------------------ deal

/** Deal one card round-robin; returns [seat, deckIndex, code]. */
export function dealNext(state: RoundState): [number, number, Card] {
  if (state.phase !== "deal") throw new EngineAssertion("not dealing");
  const idx = state.dealPos;
  const seat = idx % 4;
  const code = state.deck[idx];
  state.hands[seat].push(code);
  state.dealPos += 1;
  if (state.dealPos === 4 * HAND_SIZE) state.phase = "declare";
  return [seat, idx, code];
}

/** Deal every remaining card (no declarations in between). */
export function dealAll(state: RoundState): void {
  while (state.phase === "deal") dealNext(state);
}

// --------------------------------------------------------------- declare

export function declarationStrength(state: RoundState, cards: readonly Card[]): number | null {
  if (cards.length === 1 && cardRank(cards[0]) === state.trumpRank) return 1;
  if (cards.length === 2 && counter(cards).size === 1) {
    const code = cards[0];
    if (cardRank(code) === state.trumpRank) return 2;
    if (code === LJ) return 3;
    if (code === BJ) return 4;
  }
  return null;
}

/** Declarations `seat` could make now that beat the current one. */
export function declareOptions(state: RoundState, seat: number): Card[][] {
  if (state.phase !== "deal" && state.phase !== "declare") return [];
  const current = state.declaration ? state.declaration.strength : 0;
  const hand = counter(state.hands[seat]);
  const options: Card[][] = [];
  for (const code of [...hand.keys()].sort()) {
    const n = hand.get(code)!;
    if (cardRank(code) === state.trumpRank) {
      if (current < 1) options.push([code]);
      if (n >= 2 && current < 2) options.push([code, code]);
    }
    if (code === LJ && n >= 2 && current < 3) options.push([code, code]);
    if (code === BJ && n >= 2 && current < 4) options.push([code, code]);
  }
  return options;
}

export function declare(state: RoundState, seat: number, cards: readonly Card[]): void {
  if (state.phase !== "deal" && state.phase !== "declare") throw new IllegalPlay("Declarations are closed.");
  checkInHand(state.hands[seat], cards);
  const strength = declarationStrength(state, cards);
  const current = state.declaration ? state.declaration.strength : 0;
  if (strength === null || strength <= current) throw new IllegalPlay("Not a valid (stronger) declaration.");
  state.declaration = { seat, cards: [...cards], strength };
  state.passed = [];
  const nt = isJoker(cards[0]);
  const label = nt ? "NT" : `${cardSuit(cards[0])}${state.trumpRank}`;
  state.message = `Seat ${seat} declared ${label}` + (cards.length === 2 ? " (pair)" : "");
}

export function passDeclare(state: RoundState, seat: number): void {
  if (state.phase !== "declare") throw new IllegalPlay("Nothing to pass on.");
  if (!state.passed.includes(seat)) state.passed.push(seat);
}

/**
 * Close the declare window: fix trump (the declaration, else the kitty's
 * first non-joker, else no trump), settle a first-round banker, and hand the
 * kitty to the banker.
 */
export function finalizeDeclare(state: RoundState): void {
  if (state.phase !== "declare") throw new EngineAssertion("not in the declare window");
  if (state.declaration) {
    const code = state.declaration.cards[0];
    state.trumpIsNt = isJoker(code);
    state.trumpSuit = state.trumpIsNt ? null : (cardSuit(code) as TrumpSuit);
    if (state.banker === null) state.banker = state.declaration.seat;
  } else {
    const flipped = state.kitty.find((c) => !isJoker(c)) ?? null;
    state.trumpSuit = flipped ? (cardSuit(flipped) as TrumpSuit) : null;
    state.trumpIsNt = flipped === null;
    if (state.banker === null) state.banker = 0;
    state.message = "No declaration — trump flipped from the kitty: " + (state.trumpSuit || "NT");
  }
  state.hands[state.banker].push(...state.kitty);
  state.phase = "bury";
  state.turn = state.banker;
}

// ------------------------------------------------------------------ bury

function requireTurn(state: RoundState, seat: number, phase: Phase): void {
  if (state.phase !== phase) throw new IllegalPlay(`Not in ${phase} phase.`);
  if (state.turn !== seat) throw new IllegalPlay("Not your turn.");
}

function removeCards(state: RoundState, seat: number, cards: readonly Card[]): void {
  const hand = state.hands[seat];
  for (const c of cards) {
    const i = hand.indexOf(c);
    if (i < 0) throw new EngineAssertion(`${c} not in hand`);
    hand.splice(i, 1);
  }
}

export function bury(state: RoundState, seat: number, cards: readonly Card[]): void {
  requireTurn(state, seat, "bury");
  if (cards.length !== KITTY_SIZE) throw new IllegalPlay(`Bury exactly ${KITTY_SIZE} cards.`);
  checkInHand(state.hands[seat], cards);
  removeCards(state, seat, cards);
  state.buried = [...cards];
  state.phase = "play";
  state.trick = { leader: seat, plays: [], winner: null, points: 0 };
  state.turn = seat;
}

// ------------------------------------------------------------------ play

export type PlayCheck =
  | { ok: true; actual: Card[]; message: string | null }
  | { ok: false; error: string };

/**
 * What playing `cards` would do, without changing the state: the cards that
 * would be recorded (a failed throw's forced component) or the IllegalPlay
 * message.
 */
export function checkPlay(state: RoundState, seat: number, cards: readonly Card[]): PlayCheck {
  try {
    requireTurn(state, seat, "play");
    const o = roundOrdering(state);
    const trick = state.trick!;
    if (!trick.plays.length) {
      const others = [0, 1, 2, 3].filter((s) => s !== seat).map((s) => state.hands[s]);
      const v = validateLead(cards, state.hands[seat], others, o);
      return { ok: true, actual: v.actual, message: v.message };
    }
    validateFollow(cards, state.hands[seat], trick.plays[0].cards, o);
    return { ok: true, actual: [...cards], message: null };
  } catch (e) {
    if (e instanceof IllegalPlay) return { ok: false, error: e.message };
    throw e;
  }
}

/** True when the engine accepts `cards` from `seat` (a failing throw is accepted). */
export function isLegal(state: RoundState, seat: number, cards: readonly Card[]): boolean {
  return checkPlay(state, seat, cards).ok;
}

/**
 * Every play `seat` may attempt now, or null when there are more than
 * `limit` candidates to examine. Leads: every non-empty single-suit
 * sub-multiset (multi-component throws may come back forced). Follows: every
 * legal sub-multiset of the lead's size. Canonical order; see legal.ts.
 */
export function legalPlays(state: RoundState, seat: number, limit = 20000): Card[][] | null {
  if (state.phase !== "play" || state.turn !== seat) return [];
  const o = roundOrdering(state);
  const hand = state.hands[seat];
  const trick = state.trick!;
  if (!trick.plays.length) {
    if (countLeadCandidates(hand, o) > limit) return null;
    return leadCandidates(hand, o);
  }
  const lead = trick.plays[0].cards;
  if (countSubmultisets(hand, lead.length) > limit) return null;
  return submultisets(hand, lead.length).filter((p) => {
    try {
      validateFollow(p, hand, lead, o);
      return true;
    } catch (e) {
      if (e instanceof IllegalPlay) return false;
      throw e;
    }
  });
}

function ageNotice(state: RoundState): void {
  if (state.notice === null) return;
  state.noticePlaysLeft -= 1;
  if (state.noticePlaysLeft <= 0) state.notice = null;
}

/**
 * Play `cards` for `seat`. Throws IllegalPlay (state unchanged) when illegal.
 * Returns the cards actually recorded: a failed throw is replaced by its
 * forced component and `state.message` says so.
 */
export function applyPlay(state: RoundState, seat: number, cards: readonly Card[]): Card[] {
  requireTurn(state, seat, "play");
  const o = roundOrdering(state);
  const trick = state.trick!;
  state.message = null;
  let actual: Card[] = [...cards];
  let pendingNotice: [number, Card[], Card[]] | null = null;
  if (!trick.plays.length) {
    const others = [0, 1, 2, 3].filter((s) => s !== seat).map((s) => state.hands[s]);
    const v = validateLead(cards, state.hands[seat], others, o);
    actual = v.actual;
    state.message = v.message;
    const same = actual.length === cards.length && actual.every((c, i) => c === cards[i]);
    if (v.message !== null && !same) pendingNotice = [seat, [...cards], [...actual]];
  } else {
    validateFollow(cards, state.hands[seat], trick.plays[0].cards, o);
  }
  removeCards(state, seat, actual);
  ageNotice(state);
  if (pendingNotice) {
    state.noticeSeq += 1;
    const [s, attempted, forced] = pendingNotice;
    state.notice = { id: state.noticeSeq, kind: "failed_throw", seat: s, attempted, forced };
    state.noticePlaysLeft = NOTICE_PLAYS;
  }
  trick.plays.push({ seat, cards: [...actual] });
  if (trick.plays.length === 4) resolveTrick(state);
  else state.turn = (seat + 1) % 4;
  return actual;
}

/** The winning seat and its comparison level for a trick's plays so far. */
export function trickWinner(plays: readonly TrickPlay[], ordering: Ordering): { seat: number; suit: EffSuit; top: number } {
  const lead = plays[0].cards;
  let incSuit = uniformSuit(lead, ordering);
  if (incSuit === null) throw new EngineAssertion("lead is not one effective suit");
  let incTop = decompose(lead, ordering).topLevel();
  let winner = plays[0].seat;
  for (const tp of plays.slice(1)) {
    const [won, top] = beats(tp.cards, lead, incSuit, incTop, ordering);
    if (won) {
      winner = tp.seat;
      incTop = top;
      incSuit = ordering.effSuit(tp.cards[0]);
    }
  }
  return { seat: winner, suit: incSuit, top: incTop };
}

export function trickPoints(plays: readonly TrickPlay[]): number {
  return totalPoints(plays.flatMap((p) => p.cards));
}

/** The kitty bonus when the attackers take the last trick led with `lead`. */
export function kittyBonus(buried: readonly Card[], lead: readonly Card[]): number {
  return totalPoints(buried) * KITTY_MULTIPLIER * lead.length;
}

function resolveTrick(state: RoundState): void {
  const trick = state.trick!;
  const o = roundOrdering(state);
  const winner = trickWinner(trick.plays, o).seat;
  const pts = trickPoints(trick.plays);
  trick.winner = winner;
  trick.points = pts;
  if (isAttacker(state, winner)) state.attackerPoints += pts;
  state.lastTrick = trick;
  state.history.push(trick);
  if (state.hands.every((h) => h.length === 0)) {
    state.lastTrickWinner = winner;
    if (isAttacker(state, winner)) {
      state.kittyBonus = kittyBonus(state.buried, trick.plays[0].cards);
      state.attackerPoints += state.kittyBonus;
    }
    state.phase = "round_end";
    state.turn = null;
    state.trick = null;
  } else {
    state.trick = { leader: winner, plays: [], winner: null, points: 0 };
    state.turn = winner;
  }
}

/** A seat's hand in display order (natural order before trump is fixed). */
export function sortedHand(state: RoundState, seat: number): Card[] {
  const hand = [...state.hands[seat]];
  if (state.phase === "deal" || state.phase === "declare") return hand.sort(naturalCompare);
  const o = roundOrdering(state);
  return hand.sort((a, b) => o.compare(a, b));
}
