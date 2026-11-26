import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeAll, beforeEach, describe, expect, it, onTestFinished, vi } from "vitest";
import type { GameState, HandCard, StatePlayer } from "../protocol";

const haptics: string[] = [];
vi.mock("../native", async (load) => ({
  ...(await load<typeof import("../native")>()),
  haptic: (k: string) => { haptics.push(k); },
}));
const sent: unknown[] = [];
// a stand-in connection: open unless a test says otherwise, and able to
// deliver a server message to whoever subscribed
// The connection's generation bumps on each transition to open, as the real
// socket's does.
const link = vi.hoisted(() => ({
  current: "open" as string,
  generation: 1,
  get status() { return this.current; },
  set status(v: string) {
    if (v === "open" && this.current !== "open") this.generation += 1;
    this.current = v;
  },
  reconnects: 0,
  statusListeners: new Set<(s: string) => void>(),
  listeners: new Set<(m: unknown) => void>(),
}));
vi.mock("../ws", () => ({
  conn: {
    get status() { return link.status; },
    get generation() { return link.generation; },
    send: (m: unknown) => {
      if (link.status !== "open") return false;
      sent.push(m);
      return true;
    },
    subscribe: (fn: (m: unknown) => void) => { link.listeners.add(fn); return () => link.listeners.delete(fn); },
    subscribeStatus: (fn: (s: string) => void) => { link.statusListeners.add(fn); fn(link.status); return () => link.statusListeners.delete(fn); },
    chatHistory: () => [],
    reconnect: () => { link.reconnects += 1; },
  },
}));

const { default: Table } = await import("./Table");
const { PLAYS_KEY, COACH_PLAYS, COACH_KEY, forgetSessionCoach } = await import("../firstTurns");
const { PRESELECT_MS, FIRST_GAME_DONE_KEY, FIRST_GAME_ROOM_KEY } = await import("../firstGame");
const { forgetHintMemory } = await import("./useFirstGameHint");
const { telemetry } = await import("../telemetry");
const { auth } = await import("../auth");
const signIn = (rounds: number | null) => act(() => auth.signedIn({
  name: "Jerry Yu", email: "j@x", picture: null, display_name: null, name_shown: "Jerry", rounds_played: rounds }));

function player(seat: number, over: Partial<StatePlayer> = {}): StatePlayer {
  return { seat, name: seat ? `Bot ${seat}` : "You", is_bot: seat !== 0, connected: true,
    team: (seat % 2) as 0 | 1, cards_left: 25, is_banker: false, takeover_in: null,
    controller: seat ? "bot" : "human", reserved_for: null, reserved_secs: null, ...over };
}
const cards = (n: number): HandCard[] => Array.from({ length: n }, (_, i) => ({ id: i + 1, code: `S${(i % 9) + 2}` }));

function state(over: Partial<GameState> = {}): GameState {
  return {
    type: "state", room: "T", you: 0, phase: "play", players: [0, 1, 2, 3].map((s) => player(s)),
    hand: cards(25), levels: ["2", "2"], games_won: [0, 0], banker: 1, trump: null, turn: 1,
    declare_options: [], current_declaration: null, passed: [], trick: null, last_trick: null,
    attacker_points: 0, kitty_count: 8, round_result: null, message: null, notice: null, ...over,
  };
}

// audio.ts unlocks an AudioContext on the first click; jsdom has none
beforeAll(() => {
  class SilentAudioContext { state = "running"; currentTime = 0; async resume() {} }
  (window as unknown as { AudioContext: unknown }).AudioContext = SilentAudioContext;
});

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
beforeEach(() => {
  haptics.length = 0;
  sent.length = 0;
  link.status = "open";
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
});
const render = (s: GameState) => act(() => root.render(<Table state={s} />));



const selectedIds = () => [...host.querySelectorAll<HTMLElement>(".hand .hand-slot")]
  .filter((s) => s.querySelector(".card")!.classList.contains("selected")).map((s) => Number(s.dataset.id));
const lit = () => [...host.querySelectorAll<HTMLElement>(".hand-slot.lit")].map((s) => Number(s.dataset.id));
const hinted = () => host.querySelector(".hand.hinted") !== null;
const taps = () => telemetry.pending().filter((e) => e.e === "tap").map((e) => (e as { id: string }).id);
const tap = (id: number) => act(() => host.querySelector<HTMLElement>(`.hand-slot[data-id='${id}'] .card`)!.click());
// what went to the server other than the page's telemetry batches
const moves = () => sent.filter((m) => (m as { type: string }).type !== "client_event");
const lines = () => [...host.querySelectorAll(".hand-line")].map((l) => l.textContent);

const hearts2 = { suit: "H", rank: "2", declarer: 1 };
// a pair of 9♣ is led to you; your two clubs are the only follow
const clubHand: HandCard[] = ["S3", "S4", "D3", "C6", "CK", "H4"].map((code, i) => ({ id: i + 1, code }));
const follow = (over: Partial<GameState> = {}) => state({
  turn: 0, trump: hearts2, hand: clubHand, trick: { leader: 3, plays: [{ seat: 3, cards: ["C9", "C9"] }] }, ...over });
// your lead, from a hand with a clear pick among many
const leadHand: HandCard[] = ["S3", "S4", "S6", "S7", "SA", "SA", "D3", "D5", "C6", "CK", "H4", "BJ"]
  .map((code, i) => ({ id: i + 1, code }));
const lead = (over: Partial<GameState> = {}) => state({
  turn: 0, banker: 0, trump: hearts2, hand: leadHand, trick: { leader: 0, plays: [] }, ...over,
  players: [0, 1, 2, 3].map((s) => player(s, { is_banker: s === 0 })) });
const bankerHand: HandCard[] = ["S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10", "SJ", "SQ", "SK", "SA",
  "H3", "H5", "H7", "H9", "HJ", "HK", "D3", "D4", "D6", "D8", "D10", "DQ", "DA", "C3", "C5", "C7", "C9", "CJ", "CA", "BJ"]
  .map((code, i) => ({ id: i + 1, code }));
const burying = (over: Partial<GameState> = {}) => state({
  phase: "bury", banker: 0, turn: 0, trump: hearts2, hand: bankerHand, kitty_count: 8,
  players: [0, 1, 2, 3].map((s) => player(s, { is_banker: s === 0 })), ...over });

// the timer fires, then the lazily loaded bot answers on later microtasks
async function idle(ms: number) {
  await act(async () => { vi.advanceTimersByTime(ms); });
  await act(async () => {
    await import("../hintPick");
    for (let i = 0; i < 10; i += 1) await Promise.resolve();
  });
}

describe("first game: an idle turn gets the bot's choice selected", () => {
  beforeEach(() => {
    localStorage.clear();
    forgetHintMemory();
    telemetry.reset();
    vi.useFakeTimers();
    // jsdom has no modal dialogs; the round end opens one
    const proto = HTMLDialogElement.prototype;
    const saved = { showModal: proto.showModal, close: proto.close };
    proto.showModal = function (this: HTMLDialogElement) { this.setAttribute("open", ""); };
    proto.close = function (this: HTMLDialogElement) { this.removeAttribute("open"); };
    onTestFinished(() => { proto.showModal = saved.showModal; proto.close = saved.close; });
  });
  afterEach(() => {
    localStorage.clear();
    forgetSessionCoach();
    forgetHintMemory();
    telemetry.reset();
    vi.useRealTimers();
  });

  it("after 15 s idle on a follow, selects the two clubs, lights them, and plays nothing", async () => {
    render(follow());
    await idle(PRESELECT_MS - 100);
    expect(selectedIds()).toEqual([]);
    await idle(100);
    expect(selectedIds()).toEqual([4, 5]);
    expect(lit()).toEqual([4, 5]);
    expect(hinted()).toBe(true);
    expect(host.querySelector(".play-wrap .btn")!.textContent).toContain("Play (2/2)");
    expect((host.querySelector(".play-wrap .btn") as HTMLButtonElement).disabled).toBe(false);
    // no move goes out: you still press Play
    expect(moves()).toEqual([]);
    expect(taps()).toEqual(["hint_preselect"]);
  });

  it("on a lead, selects the bot's lead, and only those cards are lit", async () => {
    render(lead());
    expect(lit()).toEqual([]);
    await idle(PRESELECT_MS);
    const chosen = selectedIds();
    expect(chosen.length).toBeGreaterThan(0);
    expect(lit()).toEqual(chosen);
    expect(moves()).toEqual([]);
  });

  it("a tap at 10 s means no preselect, even once cleared", async () => {
    render(follow());
    await idle(10_000);
    tap(4);
    tap(4);
    expect(selectedIds()).toEqual([]);
    await idle(PRESELECT_MS);
    expect(selectedIds()).toEqual([]);
    expect(hinted()).toBe(false);
    expect(taps()).toEqual([]);
  });

  it("leaves a selection made before the turn untouched", async () => {
    render(follow({ turn: 1, trick: { leader: 3, plays: [{ seat: 3, cards: ["C9", "C9"] }] } }));
    tap(1);
    render(follow());
    await idle(PRESELECT_MS * 2);
    expect(selectedIds()).toEqual([1]);
    expect(hinted()).toBe(false);
  });

  it("the turn ending before 15 s clears the timer; the next turn starts its own", async () => {
    render(follow());
    await idle(10_000);
    // the move timer or the bot moved for you: the trick goes on without you
    render(follow({ turn: 1, hand: clubHand.slice(0, 4),
      trick: { leader: 3, plays: [{ seat: 3, cards: ["C9", "C9"] }, { seat: 0, cards: ["CK", "S4"] }] } }));
    await idle(PRESELECT_MS);
    expect(selectedIds()).toEqual([]);
    expect(taps()).toEqual([]);
  });

  it("selects the bot's 8 cards on your bury", async () => {
    render(burying());
    await idle(PRESELECT_MS);
    expect(selectedIds()).toHaveLength(8);
    expect(lit()).toEqual(selectedIds());
    const bury = host.querySelector<HTMLButtonElement>(".bury-btn")!;
    expect(bury.disabled).toBe(false);
    expect(moves()).toEqual([]);
  });

  it("never on declare", async () => {
    render(state({ phase: "declare", banker: null, turn: null, trump: null,
      hand: [{ id: 1, code: "H2" }, { id: 2, code: "S5" }], declare_options: [[1]] }));
    await idle(PRESELECT_MS * 2);
    expect(selectedIds()).toEqual([]);
    expect(moves()).toEqual([]);
  });

  it("never on another player's turn", async () => {
    render(follow({ turn: 1 }));
    await idle(PRESELECT_MS * 2);
    expect(selectedIds()).toEqual([]);
  });

  it("adds no text: the hand line is the coach's own", async () => {
    render(follow());
    const before = lines();
    await idle(PRESELECT_MS);
    // the coach's cue steps aside once cards are chosen, as after a tap
    expect(lines().every((l) => before.includes(l))).toBe(true);
  });

  it("the game's end marks the first game done; the second game gets no preselect", async () => {
    render(follow());
    render(state({ phase: "round_end", turn: null, round_result: {
      winner_team: 0, defender_points: 0, attacker_points: 0, kitty_points: 0, kitty_multiplier: 1, kitty_cards: [],
      level_change: 1, next_banker: 0, new_levels: ["2", "2"], games_won: [1, 0], point_scored: true, game_over: false,
    } as unknown as GameState["round_result"] }));
    expect(localStorage.getItem(FIRST_GAME_DONE_KEY)).toBe("1");
    act(() => root.unmount());
    root = createRoot(host);
    render(follow({ room: "U" }));
    await idle(PRESELECT_MS * 2);
    expect(selectedIds()).toEqual([]);
  });

  it("an ordinary round's end keeps the first game going", async () => {
    render(state({ phase: "round_end", turn: null, round_result: {
      winner_team: 0, defender_points: 0, attacker_points: 0, kitty_points: 0, kitty_multiplier: 1, kitty_cards: [],
      level_change: 1, next_banker: 0, new_levels: ["3", "2"], games_won: [0, 0], point_scored: false, game_over: false,
    } as unknown as GameState["round_result"] }));
    expect(localStorage.getItem(FIRST_GAME_DONE_KEY)).toBeNull();
    // the coach's plays are behind it, and the first game still helps
    localStorage.setItem(PLAYS_KEY, String(COACH_PLAYS));
    render(follow());
    await idle(PRESELECT_MS);
    expect(selectedIds()).toEqual([4, 5]);
  });

  it("a browser that made the coach's plays before this table is past its first game", async () => {
    localStorage.setItem(PLAYS_KEY, String(COACH_PLAYS));
    render(follow());
    await idle(PRESELECT_MS * 2);
    expect(selectedIds()).toEqual([]);
    expect(localStorage.getItem(FIRST_GAME_DONE_KEY)).toBe("1");
  });

  it("an account with rounds played gets none; one with none does, and keeps it for that table", async () => {
    signIn(4);
    render(follow());
    await idle(PRESELECT_MS * 2);
    expect(selectedIds()).toEqual([]);
    act(() => auth.reset());
    act(() => root.unmount());
    root = createRoot(host);
    signIn(0);
    render(follow({ room: "V" }));
    expect(localStorage.getItem(FIRST_GAME_ROOM_KEY)).toBe("V");
    // the account's first round lands: the table stays its first game
    signIn(1);
    render(follow({ room: "V", hand: [...clubHand] }));
    await idle(PRESELECT_MS);
    expect(selectedIds()).toEqual([4, 5]);
    act(() => auth.reset());
  });

  it("the coach switched off means no preselect", async () => {
    localStorage.setItem(COACH_KEY, "off");
    render(follow());
    await idle(PRESELECT_MS * 2);
    expect(selectedIds()).toEqual([]);
  });
});
