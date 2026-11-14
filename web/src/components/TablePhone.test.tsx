import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeAll, beforeEach, describe, expect, it, onTestFinished, vi } from "vitest";
import type { GameState, HandCard, StatePlayer } from "../protocol";

const haptics: string[] = [];
vi.mock("../native", () => ({ haptic: (k: string) => { haptics.push(k); } }));
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
const serverSays = (m: unknown) => act(() => { for (const fn of link.listeners) fn(m); });

const { default: Table } = await import("./Table");
const { default: Hand } = await import("./Hand");

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
  // these tests are about the table, not the newcomer coach
  localStorage.setItem("shengji.coach", "off");
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  localStorage.removeItem("shengji.coach");
});
const render = (s: GameState) => act(() => root.render(<Table state={s} />));

describe("phone turn cue and haptics", () => {
  it("marks the table my-turn and ticks once when your play comes round", () => {
    render(state({ turn: 1 }));
    expect(host.querySelector(".table-screen")!.classList.contains("my-turn")).toBe(false);
    render(state({ turn: 0 }));
    expect(host.querySelector(".table-screen")!.classList.contains("my-turn")).toBe(true);
    render(state({ turn: 0, attacker_points: 5 }));     // same turn, new state: no repeat
    expect(haptics).toEqual(["turn"]);
  });

  it("cues the banker's bury but not another seat's", () => {
    render(state({ phase: "bury", turn: 0, players: [player(0, { is_banker: true }), player(1), player(2), player(3)] }));
    expect(host.querySelector(".table-screen")!.classList.contains("my-turn")).toBe(true);
    render(state({ phase: "bury", turn: 1 }));
    expect(host.querySelector(".table-screen")!.classList.contains("my-turn")).toBe(false);
  });

  it("ticks when a declare option appears", () => {
    render(state({ phase: "deal", turn: null, hand: cards(10) }));
    render(state({ phase: "deal", turn: null, hand: cards(11), declare_options: [[1]] }));
    render(state({ phase: "deal", turn: null, hand: cards(12), declare_options: [[1]] }));
    expect(haptics).toEqual(["declare"]);
  });

  it("ticks on select only: your own play and a won trick are silent", () => {
    render(state({ turn: 0, trick: { leader: 1, plays: [{ seat: 1, cards: ["H3"] }] } }));
    haptics.length = 0;
    const card = host.querySelector<HTMLButtonElement>(".hand .card.clickable")!;
    act(() => card.click());
    act(() => host.querySelector<HTMLButtonElement>(".action-bar .btn.primary")!.click());
    expect(haptics).toEqual(["select"]);
    expect(sent).toEqual([{ type: "play", card_ids: [1] }]);
    haptics.length = 0;
    // the trick resets and you (team 0) won it
    render(state({ turn: 0, hand: cards(24), trick: { leader: 0, plays: [] },
      last_trick: { leader: 1, plays: [], winner: 2, points: 10 } }));
    expect(haptics).toEqual([]);
  });

  it("plays one success when your team takes the round, and none for the other team", () => {
    const proto = HTMLDialogElement.prototype as unknown as Record<string, unknown>;
    const saved = { showModal: proto.showModal, close: proto.close };
    proto.showModal = function (this: HTMLDialogElement) { this.setAttribute("open", ""); };
    proto.close = function (this: HTMLDialogElement) { this.removeAttribute("open"); };
    onTestFinished(() => { proto.showModal = saved.showModal; proto.close = saved.close; });
    render(state({ phase: "play", turn: 1 }));
    haptics.length = 0;
    const result = (winner_team: 0 | 1): GameState["round_result"] => ({
      attacker_points: 40, kitty_points: 0, kitty_cards: [], winner_team, level_change: 1, next_banker: 1,
      new_levels: ["3", "2"], games_won: [0, 0], point_scored: false, game_over: false });
    render(state({ phase: "round_end", turn: null, round_result: result(0) }));
    render(state({ phase: "round_end", turn: null, round_result: result(0), attacker_points: 5 }));
    expect(haptics).toEqual(["won"]);
    haptics.length = 0;
    render(state({ phase: "round_end", turn: null, round_result: result(1) }));
    expect(haptics).toEqual([]);
  });

  it("labels the trick's cards for VoiceOver and the hand as one group", () => {
    render(state({ turn: 0, hand: cards(3), trick: { leader: 1, plays: [{ seat: 1, cards: ["H3", "BJ"] }] } }));
    const played = [...host.querySelectorAll<HTMLElement>(".trick-cards .card")];
    expect(played.map((c) => [c.getAttribute("role"), c.getAttribute("aria-label")])).toEqual([
      ["img", "3 of hearts"], ["img", "Big joker"]]);
    expect(host.querySelector(".hand")!.getAttribute("role")).toBe("group");
    expect(host.querySelector(".hand")!.getAttribute("aria-label")).toBe("Your hand, 3 cards");
  });

  it("draws the deal's deck with your share so far", () => {
    render(state({ phase: "deal", turn: null, hand: cards(12) }));
    const deck = host.querySelector<HTMLElement>(".deal-deck")!;
    expect(deck.textContent).toBe("12 / 25");
    expect(deck.style.getPropertyValue("--dealt")).toBe("0.48");
    render(state({ phase: "declare", turn: null }));
    expect(host.querySelector(".deal-deck")).toBeNull();
  });
});

describe("bury hand size", () => {
  const renderHand = (n: number) => act(() => root.render(
    <Hand hand={cards(n)} selected={new Set()} selectable onToggle={() => {}} />));

  it("keeps up to 25 cards at full size", () => {
    renderHand(25);
    const hand = host.querySelector<HTMLElement>(".hand")!;
    expect(hand.classList.contains("small-cards")).toBe(false);
    expect(hand.style.getPropertyValue("--n")).toBe("25");
  });

  it("draws 33 cards smaller in one row, in sort order, and returns to full size at 25", () => {
    renderHand(33);
    const hand = host.querySelector<HTMLElement>(".hand")!;
    expect(hand.classList.contains("small-cards")).toBe(true);
    expect(hand.style.getPropertyValue("--n")).toBe("33");
    const ids = [...host.querySelectorAll<HTMLElement>(".hand-slot")].map((el) => Number(el.dataset.id));
    expect(ids).toEqual(cards(33).map((c) => c.id));
    renderHand(25);
    expect(host.querySelector<HTMLElement>(".hand")!.classList.contains("small-cards")).toBe(false);
  });
});

it("keeps a long-pressed name visible after pointer release and its click", () => {
  vi.useFakeTimers();
  try {
    render(state());
    const seat = host.querySelector<HTMLElement>(".opponent.pos-left")!;
    act(() => seat.dispatchEvent(new Event("pointerdown", { bubbles: true })));
    act(() => vi.advanceTimersByTime(450));
    expect(seat.querySelector(".opp-fullname")).not.toBeNull();
    act(() => seat.dispatchEvent(new Event("pointerup", { bubbles: true })));
    act(() => seat.click());
    expect(seat.querySelector(".opp-fullname")).not.toBeNull();
    act(() => vi.advanceTimersByTime(2499));
    expect(seat.querySelector(".opp-fullname")).not.toBeNull();
    act(() => vi.advanceTimersByTime(1));
    expect(seat.querySelector(".opp-fullname")).toBeNull();
    act(() => seat.dispatchEvent(new Event("pointerdown", { bubbles: true })));
    act(() => seat.dispatchEvent(new Event("pointerup", { bubbles: true })));
    act(() => seat.click());
    expect(seat.querySelector(".opp-fullname")).not.toBeNull();
    act(() => seat.click());
    expect(seat.querySelector(".opp-fullname")).toBeNull();
  } finally { vi.useRealTimers(); }
});

describe("sending a play", () => {
  const myTurn = (over: Partial<GameState> = {}) =>
    state({ turn: 0, trick: { leader: 0, plays: [] }, ...over });
  const pick = (n: number) => act(() => host.querySelectorAll<HTMLButtonElement>(".hand .card.clickable")[n].click());
  const play = () => host.querySelector<HTMLButtonElement>(".action-bar .btn.primary")!;
  const selectedCount = () => host.querySelectorAll(".hand .card.selected").length;

  it("clears the whole selection once the server answers, even cards a failed throw hands back", () => {
    render(myTurn());
    pick(0); pick(1); pick(2);
    act(() => play().click());
    expect(sent).toEqual([{ type: "play", card_ids: [1, 2, 3] }]);
    // the throw failed: the server forced card 1 and handed 2 and 3 back
    render(myTurn({ hand: cards(25).filter((c) => c.id !== 1), turn: 1,
      trick: { leader: 0, plays: [{ seat: 0, cards: ["S2"] }] } }));
    expect(selectedCount()).toBe(0);
    render(myTurn({ hand: cards(25).filter((c) => c.id !== 1) }));
    expect(selectedCount()).toBe(0);
  });

  it("waits after one send: a second tap sends nothing until the server answers", () => {
    render(myTurn());
    pick(4);
    act(() => play().click());
    expect(play().disabled).toBe(true);
    act(() => play().click());
    expect(sent).toHaveLength(1);
    expect(host.querySelector<HTMLButtonElement>(".action-bar .btn.subtle")!.disabled).toBe(true);
    // an illegal play comes back as an error: the selection stays to be fixed
    serverSays({ type: "error", code: "illegal", message: "You must follow suit." });
    expect(play().disabled).toBe(false);
    expect(selectedCount()).toBe(1);
  });

  it("does not send, buzz or wait while the connection is down", () => {
    link.status = "closed";
    render(myTurn());
    pick(4);
    haptics.length = 0;
    expect(play().disabled).toBe(true);
    act(() => play().click());
    expect(sent).toEqual([]);
    expect(haptics).toEqual([]);
  });
});


it("recovers an unanswered play after reconnecting to the unchanged authoritative state", () => {
  const unchanged = state({ turn: 0, trick: { leader: 0, plays: [] } });
  render(unchanged);
  act(() => host.querySelectorAll<HTMLButtonElement>(".hand .card.clickable")[0].click());
  const play = () => host.querySelector<HTMLButtonElement>(".action-bar .btn.primary")!;
  act(() => play().click());
  expect(sent).toHaveLength(1);
  for (const status of ["closed", "connecting", "open"]) {
    act(() => { link.status = status; for (const fn of link.statusListeners) fn(status); });
  }
  serverSays({ ...unchanged, type: "state" });
  render({ ...unchanged });
  expect(play().disabled).toBe(false);
});

describe("a pending action across a reconnect", () => {
  const reconnect = () => {
    for (const status of ["closed", "connecting", "open"]) {
      act(() => { link.status = status; for (const fn of link.statusListeners) fn(status); });
    }
  };
  const pick = (n: number) => act(() => host.querySelectorAll<HTMLButtonElement>(".hand .card.clickable")[n].click());
  const primary = () => host.querySelector<HTMLButtonElement>(".action-bar .btn.primary")!;
  const selected = () => [...host.querySelectorAll<HTMLElement>(".hand-slot")]
    .filter((slot) => slot.querySelector(".card.selected")).map((slot) => Number(slot.dataset.id));

  const playing = (over: Partial<GameState> = {}) => state({ turn: 0, trick: { leader: 0, plays: [] }, ...over });
  const burying = (over: Partial<GameState> = {}) => state({
    phase: "bury", turn: 0, hand: cards(33), banker: 0,
    players: [player(0, { is_banker: true, cards_left: 33 }), player(1), player(2), player(3)], ...over });

  it("play that never committed: Play waits through the reconnect, then the same state frees it with the selection kept", () => {
    render(playing());
    pick(2); pick(3);
    act(() => primary().click());
    expect(sent).toEqual([{ type: "play", card_ids: [3, 4] }]);
    reconnect();
    // open alone settles nothing: still waiting for the server's state
    expect(primary().disabled).toBe(true);
    render(playing());
    expect(primary().disabled).toBe(false);
    expect(selected()).toEqual([3, 4]);
  });

  it("play that committed: the first state after the reconnect shows it, and the selection clears", () => {
    render(playing());
    pick(2); pick(3);
    act(() => primary().click());
    reconnect();
    render(playing({ hand: cards(25).filter((c) => c.id !== 3 && c.id !== 4), turn: 1,
      trick: { leader: 0, plays: [{ seat: 0, cards: ["S4", "S5"] }] } }));
    expect(selected()).toEqual([]);
    render(playing({ hand: cards(25).filter((c) => c.id !== 3 && c.id !== 4) }));
    expect(primary().disabled).toBe(true);    // nothing selected, nothing pending
    expect(selected()).toEqual([]);
  });

  it("bury that never committed: Bury waits through the reconnect, then the same state frees it with the eight kept", () => {
    render(burying());
    for (let i = 0; i < 8; i++) pick(i);
    act(() => primary().click());
    expect(sent).toEqual([{ type: "bury", card_ids: [1, 2, 3, 4, 5, 6, 7, 8] }]);
    reconnect();
    expect(primary().disabled).toBe(true);
    render(burying());
    expect(primary().disabled).toBe(false);
    expect(selected()).toEqual([1, 2, 3, 4, 5, 6, 7, 8]);
  });

  it("bury that committed: the first state after the reconnect is play, and nothing stays selected", () => {
    render(burying());
    for (let i = 0; i < 8; i++) pick(i);
    act(() => primary().click());
    reconnect();
    render(playing({ hand: cards(33).slice(8), banker: 0,
      players: [player(0, { is_banker: true, cards_left: 25 }), player(1), player(2), player(3)] }));
    expect(selected()).toEqual([]);
  });

  it("a same-hand broadcast on the same connection does not free a pending play", () => {
    render(playing());
    pick(2);
    act(() => primary().click());
    render(playing({ attacker_points: 5 }));
    expect(primary().disabled).toBe(true);
    expect(sent).toHaveLength(1);
  });
});

describe("whose turn on a seat's label", () => {
  it("marks only the seat on turn with the turn class and its …, and gives every seat its team dot", () => {
    render(state({ turn: 2, players: [0, 1, 2, 3].map((s) => player(s, s === 3 ? { is_bot: false, controller: "human" } : {})) }));
    const opp = (seat: number) => host.querySelectorAll<HTMLElement>(".opponent")[seat - 1];
    expect(opp(2).classList.contains("on-turn")).toBe(true);
    expect(opp(2).querySelector(".opp-name .turn-dots.shown")?.textContent).toBe("…");
    for (const s of [1, 3]) {
      expect(opp(s).classList.contains("on-turn")).toBe(false);
      // drawn unseen, so the label keeps its width when the turn comes
      expect(opp(s).querySelector(".turn-dots")).not.toBeNull();
      expect(opp(s).querySelector(".turn-dots.shown")).toBeNull();
    }
    for (const s of [1, 2, 3]) expect(opp(s).querySelector(`.opp-name .seat-dot.t${s % 2}`)).not.toBeNull();
    // a human on turn gets the same mark
    render(state({ turn: 3, players: [0, 1, 2, 3].map((s) => player(s, s === 3 ? { is_bot: false, controller: "human" } : {})) }));
    expect(opp(3).querySelector(".turn-dots.shown")).not.toBeNull();
    // outside bury and play nobody is on turn
    render(state({ phase: "declare", turn: 2 }));
    expect(host.querySelector(".turn-dots.shown")).toBeNull();
  });
});

describe("Your turn on a lead", () => {
  it("carries no hint line under the button", () => {
    render(state({ turn: 0 }));
    expect(host.querySelector(".lead-hint")).toBeNull();
    expect(host.textContent).not.toContain("Tap cards, then Play");
  });
});


it("draws the error toast inside the table, where its rows are", () => {
  act(() => root.render(<Table state={state({ turn: 0 })} toast={{ id: 1, text: "You must follow suit." }} />));
  expect(host.querySelector(".table-screen > .toast")?.textContent).toBe("You must follow suit.");
  act(() => root.render(<Table state={state({ turn: 0 })} toast={null} />));
  expect(host.querySelector(".toast")).toBeNull();
});

describe("following a lead", () => {
  const SPADES_7 = { suit: "S", rank: "7", declarer: 1 };
  const followHand: HandCard[] = [
    { id: 1, code: "D9" }, { id: 2, code: "D9" }, { id: 3, code: "DJ" }, { id: 4, code: "S3" },
  ];
  const pairLed = (over: Partial<GameState> = {}) => state({
    turn: 0, hand: followHand, trump: SPADES_7,
    trick: { leader: 1, plays: [{ seat: 1, cards: ["DQ", "DQ"] }] }, ...over,
  });
  const slot = (id: number) => host.querySelector<HTMLButtonElement>(`.hand-slot[data-id="${id}"] .card`)!;
  const primary = () => host.querySelector<HTMLButtonElement>(".action-bar .btn.primary")!;

  it("keeps Play off until the selection is as many cards as the lead, and says the count", () => {
    render(pairLed());
    act(() => slot(1).click());
    expect(primary().disabled).toBe(true);
    expect(primary().querySelector(".play-text")?.textContent).toBe("Play (1/2)");
    act(() => slot(2).click());
    expect(primary().disabled).toBe(false);
    expect(primary().querySelector(".play-text")?.textContent).toBe("Play (2/2)");
    act(() => primary().click());
    expect(sent).toEqual([{ type: "play", card_ids: [1, 2] }]);
  });

  it("leading, any count may go", () => {
    render(state({ turn: 0, hand: followHand, trump: SPADES_7, trick: { leader: 0, plays: [] } }));
    act(() => slot(3).click());
    expect(primary().disabled).toBe(false);
    expect(primary().querySelector(".play-text")?.textContent).toBe("Play (1)");
  });
});

describe("Play and Bury say they are sending", () => {
  const pick = (n: number) => act(() => host.querySelectorAll<HTMLButtonElement>(".hand .card.clickable")[n].click());
  const primary = () => host.querySelector<HTMLButtonElement>(".action-bar .btn.primary")!;
  const label = () => (primary().querySelector(".play-text") ?? primary()).textContent;
  const handIds = () => [...host.querySelectorAll<HTMLElement>(".hand-slot")].map((slot) => Number(slot.dataset.id));
  const selected = () => [...host.querySelectorAll<HTMLElement>(".hand-slot")]
    .filter((slot) => slot.querySelector(".card.selected")).map((slot) => Number(slot.dataset.id));
  const setStatus = (s: string) => act(() => { link.status = s; for (const fn of link.statusListeners) fn(s); });
  const playing = (over: Partial<GameState> = {}) => state({ turn: 0, trick: { leader: 0, plays: [] }, ...over });
  const burying = (over: Partial<GameState> = {}) => state({
    phase: "bury", turn: 0, hand: cards(33), banker: 0,
    players: [player(0, { is_banker: true, cards_left: 33 }), player(1), player(2), player(3)], ...over });

  it("a delayed play: Sending… and aria-busy at once, the cards stay in the hand, one send", () => {
    render(playing());
    pick(0);
    expect(label()).toBe("Play (1)");
    expect(primary().getAttribute("aria-busy")).toBeNull();
    act(() => primary().click());
    expect(label()).toBe("Sending…");
    expect(primary().getAttribute("aria-busy")).toBe("true");
    expect(handIds()).toHaveLength(25);          // nothing leaves before the server says so
    expect(selected()).toEqual([1]);
    act(() => primary().click());
    expect(sent).toHaveLength(1);
    setStatus("closed");                         // the connection drops meanwhile
    expect(label()).toBe("Reconnecting…");
    expect(primary().getAttribute("aria-busy")).toBe("true");
    setStatus("connecting");
    setStatus("open");
    render(playing({ hand: cards(25).slice(1), turn: 1, trick: { leader: 0, plays: [{ seat: 0, cards: ["S2"] }] } }));
    expect(host.querySelector(".action-bar .btn.primary")?.getAttribute("aria-busy") ?? null).toBeNull();
  });

  it("a rejected play: the label and selection come back, nothing resent", () => {
    render(playing());
    pick(0); pick(1);
    act(() => primary().click());
    expect(label()).toBe("Sending…");
    serverSays({ type: "error", code: "illegal", message: "Not a legal play." });
    expect(label()).toBe("Play (2)");
    expect(primary().getAttribute("aria-busy")).toBeNull();
    expect(selected()).toEqual([1, 2]);
    expect(sent).toHaveLength(1);
  });

  it("a delayed bury: Sending… and aria-busy, the eight stay, one send", () => {
    render(burying());
    for (let i = 0; i < 8; i++) pick(i);
    expect(label()).toBe("Bury 8 cards (8/8)");
    act(() => primary().click());
    expect(label()).toBe("Sending…");
    expect(primary().getAttribute("aria-busy")).toBe("true");
    act(() => primary().click());
    expect(sent).toHaveLength(1);
    expect(handIds()).toHaveLength(33);
    expect(selected()).toEqual([1, 2, 3, 4, 5, 6, 7, 8]);
  });

  it("a rejected bury: Bury comes back with the eight still chosen", () => {
    render(burying());
    for (let i = 0; i < 8; i++) pick(i);
    act(() => primary().click());
    serverSays({ type: "error", code: "illegal", message: "Bury exactly 8 cards." });
    expect(label()).toBe("Bury 8 cards (8/8)");
    expect(primary().getAttribute("aria-busy")).toBeNull();
    expect(primary().disabled).toBe(false);
    expect(selected()).toEqual([1, 2, 3, 4, 5, 6, 7, 8]);
    expect(sent).toHaveLength(1);
  });
});

describe("following", () => {
  // you hold S2..S10 twice over plus a heart; Bot 1 led a spade pair
  const mixed: HandCard[] = [...cards(24), { id: 25, code: "HA" }];
  const following = (over: Partial<GameState> = {}) => state({
    turn: 0, hand: mixed, trump: { suit: "H", rank: "J", declarer: 1 },
    trick: { leader: 1, plays: [{ seat: 1, cards: ["SK", "SK"] }] }, ...over });
  const wrap = () => host.querySelector<HTMLElement>(".play-wrap")!;

  it("a tap on a Play that cannot go says what the follow needs and buzzes", () => {
    render(following());
    act(() => host.querySelectorAll<HTMLButtonElement>(".hand .card.clickable")[0].click());
    haptics.length = 0;
    expect(host.querySelector<HTMLButtonElement>(".action-bar .btn.primary")!.disabled).toBe(true);
    act(() => wrap().click());
    expect(host.querySelector(".follow-hint")?.textContent).toBe("Follow ♠: play 2 cards");
    expect(haptics).toEqual(["error"]);
    expect(sent).toEqual([]);
    // choosing another card clears it
    act(() => host.querySelectorAll<HTMLButtonElement>(".hand .card.clickable")[1].click());
    expect(host.querySelector(".follow-hint")).toBeNull();
  });

  it("an enabled Play sends without a hint, and a hint fades on its own", () => {
    vi.useFakeTimers();
    try {
      render(following());
      act(() => wrap().click());
      expect(host.querySelector(".follow-hint")).not.toBeNull();
      act(() => { vi.advanceTimersByTime(3000); });
      expect(host.querySelector(".follow-hint")).toBeNull();
      act(() => host.querySelectorAll<HTMLButtonElement>(".hand .card.clickable")[0].click());
      act(() => host.querySelectorAll<HTMLButtonElement>(".hand .card.clickable")[9].click());
      haptics.length = 0;
      act(() => host.querySelector<HTMLButtonElement>(".action-bar .btn.primary")!.click());
      expect(sent).toHaveLength(1);
      expect(host.querySelector(".follow-hint")).toBeNull();
      expect(haptics).not.toContain("error");
    } finally { vi.useRealTimers(); }
  });

  it("leading, a tap on an empty Play asks for cards", () => {
    render(state({ turn: 0, trick: { leader: 0, plays: [] } }));
    act(() => wrap().click());
    expect(host.querySelector(".follow-hint")?.textContent).toBe("Choose the cards to lead");
  });
});

describe("a stalled connection at the table", () => {
  it("offers Retry after the lobby's wait, and Retry reconnects at once", () => {
    vi.useFakeTimers();
    try {
      link.reconnects = 0;
      render(state());
      act(() => { link.status = "closed"; for (const fn of link.statusListeners) fn("closed"); });
      act(() => { vi.advanceTimersByTime(3900); });
      expect(host.querySelector(".table-stalled")).toBeNull();
      act(() => { vi.advanceTimersByTime(200); });
      const retry = host.querySelector<HTMLButtonElement>(".table-stalled .conn-retry")!;
      expect(retry.textContent).toBe("Retry");
      act(() => retry.click());
      expect(link.reconnects).toBe(1);
      // the wait starts over
      expect(host.querySelector(".table-stalled")).toBeNull();
      act(() => { link.status = "open"; for (const fn of link.statusListeners) fn("open"); });
      act(() => { vi.advanceTimersByTime(5000); });
      expect(host.querySelector(".table-stalled")).toBeNull();
    } finally { vi.useRealTimers(); }
  });
});

describe("move timer", () => {
  const mine = (over: Partial<StatePlayer>) =>
    [player(0, over), player(1), player(2), player(3)];
  afterEach(() => { vi.useRealTimers(); });

  it("shows your ring from the first second, with the seconds counting down, red in the last ten", () => {
    vi.useFakeTimers();
    render(state({ turn: 0, players: mine({ turn_deadline: 60 }) }));
    const ring = () => host.querySelector(".action-bar .timer-ring");
    expect(ring()).not.toBeNull();
    expect(ring()!.getAttribute("role")).toBe("timer");
    expect(ring()!.textContent).toBe("60");
    expect(ring()!.getAttribute("aria-label")).toBe("60 seconds left");
    expect(ring()!.getAttribute("style")).toContain("--ring-deg: 360deg");
    expect(ring()!.className).not.toContain("thin");
    expect(ring()!.className).not.toContain("low");
    act(() => { vi.advanceTimersByTime(2500); });
    expect(ring()!.textContent).toBe("58");
    act(() => { vi.advanceTimersByTime(27_500); });
    expect(ring()!.textContent).toBe("30");
    expect(ring()!.getAttribute("style")).toContain("--ring-deg: 180deg");
    expect(host.querySelector(".action-bar")!.classList.contains("clock-low")).toBe(false);
    act(() => { vi.advanceTimersByTime(20_000); });
    expect(ring()!.textContent).toBe("10");
    expect(ring()!.className).toContain("low");
    expect(host.querySelector(".action-bar")!.classList.contains("clock-low")).toBe(true);
    act(() => { vi.advanceTimersByTime(3000); });
    expect(ring()!.textContent).toBe("7");
    // your own clock is never drawn on an opponent's pill
    expect(host.querySelector(".opponent .timer-ring")).toBeNull();
  });

  it("shows a thin ring with the seconds on the deciding seat's pill, and none on yours", () => {
    vi.useFakeTimers();
    const li = { is_bot: false, controller: "human" as const, turn_deadline: 42 };
    render(state({ turn: 1, players: [player(0), player(1, li), player(2), player(3)] }));
    const rings = () => [...host.querySelectorAll(".opponent .timer-ring")];
    expect(rings()).toHaveLength(1);
    const ring = rings()[0];
    expect(ring.closest(".opponent")!.className).toContain("on-turn");
    expect(ring.className).toContain("thin");
    expect(ring.textContent).toBe("42");
    expect(host.querySelector(".action-bar .timer-ring")).toBeNull();
    haptics.length = 0;
    act(() => { vi.advanceTimersByTime(3000); });
    expect(rings()[0].textContent).toBe("39");
    act(() => { vi.advanceTimersByTime(35_000); });
    expect(rings()[0].textContent).toBe("4");
    expect(rings()[0].className).toContain("low");
    // another seat's clock never buzzes your phone
    expect(haptics).toEqual([]);
    // the turn moves on: the next state carries no clock for that seat
    render(state({ turn: 2, players: [player(0), player(1, { ...li, turn_deadline: null }), player(2), player(3)] }));
    expect(rings()).toHaveLength(0);
  });

  it("buzzes once at five seconds and not before", () => {
    vi.useFakeTimers();
    render(state({ turn: 0, players: mine({ turn_deadline: 7 }) }));
    haptics.length = 0;
    act(() => { vi.advanceTimersByTime(1500); });
    expect(haptics).toEqual([]);
    act(() => { vi.advanceTimersByTime(750); });
    expect(haptics).toEqual(["clock"]);
    // a fresh state for the same decision does not buzz again
    render(state({ turn: 0, attacker_points: 5, players: mine({ turn_deadline: 4 }) }));
    act(() => { vi.advanceTimersByTime(2000); });
    expect(haptics).toEqual(["clock"]);
  });

  it("draws no ring and no buzz without a clock (casual tables, offline)", () => {
    vi.useFakeTimers();
    render(state({ turn: 0 }));
    haptics.length = 0;
    act(() => { vi.advanceTimersByTime(70_000); });
    expect(host.querySelector(".timer-ring")).toBeNull();
    expect(haptics).toEqual([]);
  });

  it("shows the away pill, and I'm back sends im_back", () => {
    render(state({ turn: 1, players: mine({ away: true }) }));
    const pill = host.querySelector(".away-pill")!;
    expect(pill.textContent).toContain("Away");
    expect(pill.textContent).toContain("The bot is playing for you");
    const back = pill.querySelector<HTMLButtonElement>("button")!;
    expect(back.textContent).toContain("I’m back");
    act(() => back.click());
    expect(sent).toEqual([{ type: "im_back" }]);
    render(state({ turn: 1, players: mine({ away: false }) }));
    expect(host.querySelector(".away-pill")).toBeNull();
  });

  it("tags another player's seat Away and nothing else", () => {
    render(state({ turn: 1, players: [player(0), player(1, { is_bot: false, controller: "human", away: true }),
      player(2), player(3)] }));
    const tags = [...host.querySelectorAll(".away-tag")].map((t) => t.textContent);
    expect(tags).toEqual(["Away"]);
    expect(host.querySelector(".away-pill")).toBeNull();
  });
});


describe("review: turn telemetry producer", () => {
  it("finishes a last-follower turn when its winner immediately leads", async () => {
    const { telemetry } = await import("../telemetry");
    const done = vi.spyOn(telemetry, "turnDone");
    try {
      render(state({ turn: 0, trick: { leader: 1, plays: [
        { seat: 1, cards: ["S2"] }, { seat: 2, cards: ["S3"] }, { seat: 3, cards: ["S4"] },
      ] } }));
      render(state({ turn: 0, hand: cards(24), trick: { leader: 0, plays: [] },
        last_trick: { leader: 1, plays: [
          { seat: 1, cards: ["S2"] }, { seat: 2, cards: ["S3"] },
          { seat: 3, cards: ["S4"] }, { seat: 0, cards: ["S5"] },
        ], winner: 0, points: 5 } }));
      expect(done).toHaveBeenCalledTimes(1);
    } finally { done.mockRestore(); }
  });
  it("does not call an unfinished turn timer-completed on leaving the table", async () => {
    const { telemetry } = await import("../telemetry");
    const done = vi.spyOn(telemetry, "turnDone");
    try {
      render(state({ turn: 0, trick: { leader: 0, plays: [] } }));
      act(() => root.render(null));
      expect(done).not.toHaveBeenCalled();
    } finally { done.mockRestore(); }
  });
});

describe("turn telemetry: a decision is reported once, when the game moves past it", () => {
  const pickAndPlay = () => {
    act(() => host.querySelectorAll<HTMLButtonElement>(".hand .card.clickable")[0].click());
    act(() => host.querySelector<HTMLButtonElement>(".action-bar .btn.primary")!.click());
  };

  it("reports a submitted lead as yours, with its selection", async () => {
    const { telemetry } = await import("../telemetry");
    const done = vi.spyOn(telemetry, "turnDone");
    try {
      render(state({ room: "SUB", turn: 0, trick: { leader: 0, plays: [] } }));
      pickAndPlay();
      expect(sent).toContainEqual(expect.objectContaining({ type: "play" }));
      render(state({ room: "SUB", turn: 1, hand: cards(24),
                     trick: { leader: 0, plays: [{ seat: 0, cards: ["S2"] }] } }));
      expect(done).toHaveBeenCalledTimes(1);
      expect(done.mock.calls[0][0]).toMatchObject({ phase: "play", by: "you", sel_changes: 1, need: 0 });
    } finally { done.mockRestore(); }
  });

  it("treats broadcasts that leave the decision in place as the same turn", async () => {
    const { telemetry } = await import("../telemetry");
    const done = vi.spyOn(telemetry, "turnDone");
    try {
      const trick = { leader: 1, plays: [{ seat: 1, cards: ["S2"] }] };
      render(state({ room: "SAME", turn: 0, trick }));
      render(state({ room: "SAME", turn: 0, trick, attacker_points: 10 }));
      render(state({ room: "SAME", turn: 0, trick, players: [0, 1, 2, 3].map((s) => player(s, { connected: s !== 2 })) }));
      expect(done).not.toHaveBeenCalled();
      render(state({ room: "SAME", turn: 1, hand: cards(24),
                     trick: { leader: 1, plays: [...trick.plays, { seat: 0, cards: ["S3"] }] } }));
      expect(done).toHaveBeenCalledTimes(1);
      expect(done.mock.calls[0][0]).toMatchObject({ by: "timer", lead: "single", need: 1 });
    } finally { done.mockRestore(); }
  });

  it("keeps the turn across a remount and reports it once when it ends", async () => {
    const { telemetry } = await import("../telemetry");
    const done = vi.spyOn(telemetry, "turnDone");
    try {
      const mine = state({ room: "REMOUNT", turn: 0, trick: { leader: 0, plays: [] } });
      render(mine);
      act(() => root.render(null));      // How to play replaces the table
      render(mine);                       // and back
      expect(done).not.toHaveBeenCalled();
      pickAndPlay();
      render(state({ room: "REMOUNT", turn: 1, hand: cards(24),
                     trick: { leader: 0, plays: [{ seat: 0, cards: ["S2"] }] } }));
      expect(done).toHaveBeenCalledTimes(1);
      expect(done.mock.calls[0][0]).toMatchObject({ by: "you", nth_turn: expect.any(Number) });
    } finally { done.mockRestore(); }
  });
});

describe("Play waits on an off-suit follow", () => {
  // hearts and jacks are trump; the lead is a pair of spade kings
  const hand: HandCard[] = ["S3", "S7", "C4", "C9", "D5", "HA", "SJ"].map((code, i) => ({ id: i + 1, code }));
  const following = () => state({
    turn: 0, hand, trump: { suit: "H", rank: "J", declarer: 1 },
    trick: { leader: 1, plays: [{ seat: 1, cards: ["SK", "SK"] }] } });
  const choose = (...ids: number[]) => {
    for (const id of ids) act(() => host.querySelector<HTMLElement>(`.hand-slot[data-id="${id}"] .card`)!.click());
  };
  const play = () => host.querySelector<HTMLButtonElement>(".action-bar .btn.primary")!;

  it("an off-suit selection of the right count keeps Play disabled and shows the follow hint", () => {
    render(following());
    choose(1, 3);
    expect(play().disabled).toBe(true);
    const hint = host.querySelector(".follow-hint");
    expect(hint?.textContent).toBe("Follow ♠: play 2 cards");
    // the hint stands outside your row, so it cannot push the action bar
    expect(hint!.closest(".you-row")).toBeNull();
    expect(hint!.parentElement!.classList.contains("you-area")).toBe(true);
    // the trump-rank jack of spades is trump, not a spade
    act(() => host.querySelector<HTMLElement>(`.hand-slot[data-id="3"] .card`)!.click());
    choose(7);
    expect(play().disabled).toBe(true);
  });

  it("a legal follow enables Play with no hint", () => {
    render(following());
    choose(1, 2);
    expect(play().disabled).toBe(false);
    expect(host.querySelector(".follow-hint")).toBeNull();
    act(() => play().click());
    expect(sent).toHaveLength(1);
  });

  it("a hand short of the suit may play every spade it holds and anything else", () => {
    render(state({ turn: 0, hand: hand.filter((c) => c.code !== "S7"), trump: { suit: "H", rank: "J", declarer: 1 },
      trick: { leader: 1, plays: [{ seat: 1, cards: ["SK", "SK"] }] } }));
    choose(1, 7);
    expect(play().disabled).toBe(false);
    expect(host.querySelector(".follow-hint")).toBeNull();
  });

  it("a tap on the waiting Play still counts as a disabled-Play tap", async () => {
    const { telemetry } = await import("../telemetry");
    const done = vi.spyOn(telemetry, "turnDone");
    const notice = vi.spyOn(telemetry, "notice");
    try {
      render(following());
      choose(1, 3);
      act(() => host.querySelector<HTMLElement>(".play-wrap")!.click());
      expect(notice).toHaveBeenCalledWith("follow_hint", "table");
      expect(host.querySelectorAll(".follow-hint")).toHaveLength(1);
      render(state({ turn: 1, hand: hand.slice(2), trump: { suit: "H", rank: "J", declarer: 1 },
        trick: { leader: 1, plays: [{ seat: 1, cards: ["SK", "SK"] }, { seat: 0, cards: ["S3", "S7"] }] } }));
      expect(done).toHaveBeenCalledTimes(1);
      expect(done.mock.calls[0][0]).toMatchObject({ disabled_play_taps: 1 });
    } finally { done.mockRestore(); notice.mockRestore(); }
  });
});
