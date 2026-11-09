import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import type { GameState, HandCard, StatePlayer } from "../protocol";

const haptics: string[] = [];
vi.mock("../native", () => ({ haptic: (k: string) => { haptics.push(k); } }));
const sent: unknown[] = [];
// a stand-in connection: open unless a test says otherwise, and able to
// deliver a server message to whoever subscribed
const link = vi.hoisted(() => ({
  status: "open" as string,
  listeners: new Set<(m: unknown) => void>(),
}));
vi.mock("../ws", () => ({
  conn: {
    get status() { return link.status; },
    send: (m: unknown) => {
      if (link.status !== "open") return false;
      sent.push(m);
      return true;
    },
    subscribe: (fn: (m: unknown) => void) => { link.listeners.add(fn); return () => link.listeners.delete(fn); },
    subscribeStatus: (fn: (s: string) => void) => { fn(link.status); return () => {}; },
    chatHistory: () => [],
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
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
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

  it("taps on select and on Play, and a success when your team takes the trick", () => {
    render(state({ turn: 0, trick: { leader: 1, plays: [{ seat: 1, cards: ["H3"] }] } }));
    haptics.length = 0;
    const card = host.querySelector<HTMLButtonElement>(".hand .card.clickable")!;
    act(() => card.click());
    act(() => host.querySelector<HTMLButtonElement>(".action-bar .btn.primary")!.click());
    expect(haptics).toEqual(["select", "play"]);
    expect(sent).toEqual([{ type: "play", card_ids: [1] }]);
    haptics.length = 0;
    // the trick resets and you (team 0) won it
    render(state({ turn: 0, hand: cards(24), trick: { leader: 0, plays: [] },
      last_trick: { leader: 1, plays: [], winner: 2, points: 10 } }));
    expect(haptics).toEqual(["won"]);
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
