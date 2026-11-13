import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
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
const { TOAST_MS } = await import("../toast");
const { NUDGE_MS, PLAYS_KEY, COACH_PLAYS, COACH_KEY, forgetSessionCoach } = await import("../firstTurns");

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


const cue = () => host.querySelector(".coach-cue");
const lit = () => [...host.querySelectorAll(".hand-slot.lit")].map((s) => Number((s as HTMLElement).dataset.id));
const dim = () => host.querySelectorAll(".hand-slot.dim").length;
const hearts2 = { suit: "H", rank: "2", declarer: 1 };
const clubHand: HandCard[] = ["S3", "S4", "D3", "C6", "CK", "H4"].map((code, i) => ({ id: i + 1, code }));
const firstFollow = (over: Partial<GameState> = {}) => state({
  turn: 0, trump: hearts2, hand: clubHand, trick: { leader: 3, plays: [{ seat: 3, cards: ["C9", "C9"] }] }, ...over });

describe("newcomer coach", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => { localStorage.clear(); forgetSessionCoach(); vi.restoreAllMocks(); vi.useRealTimers(); });

  it("tells a newcomer what to tap on their first follow and lights the clubs", () => {
    render(firstFollow());
    expect(cue()?.textContent).toBe("Your turn: tap 2 ♣ cards (lit up), then Play");
    expect(lit()).toEqual([4, 5]);
    expect(dim()).toBe(4);
  });

  it("is quiet when it is not your turn", () => {
    render(firstFollow({ turn: 1 }));
    expect(cue()).toBeNull();
    expect(dim()).toBe(0);
  });

  it("never shows for a player who has made the coach's plays", () => {
    localStorage.setItem(PLAYS_KEY, String(COACH_PLAYS));
    render(firstFollow());
    expect(cue()).toBeNull();
    expect(dim()).toBe(0);
  });

  it("steps aside while cards are chosen and comes back when they are cleared", () => {
    render(firstFollow());
    act(() => host.querySelector<HTMLElement>(".hand-slot[data-id='4'] .card")!.click());
    expect(cue()).toBeNull();
    act(() => host.querySelector<HTMLElement>(".hand-slot[data-id='4'] .card")!.click());
    expect(cue()).not.toBeNull();
  });

  it("counts committed plays and stops after the coach's limit", () => {
    let hand = clubHand;
    const single = { leader: 3, plays: [{ seat: 3, cards: ["S9"] }] };
    for (let i = 0; i < COACH_PLAYS; i++) {
      render(firstFollow({ hand, trick: single }));
      expect(cue()).not.toBeNull();
      act(() => host.querySelector<HTMLElement>(".hand-slot .card")!.click());
      act(() => host.querySelector<HTMLButtonElement>(".action-bar .btn.primary")!.click());
      expect(cue()).toBeNull();          // sending: no coach over "Sending…"
      hand = hand.slice(1);
      // the play committed: your hand shrank and the turn moved on
      render(firstFollow({ hand, turn: 1, trick: single }));
    }
    expect(sent).toHaveLength(COACH_PLAYS);
    expect(localStorage.getItem(PLAYS_KEY)).toBe(String(COACH_PLAYS));
    render(firstFollow({ hand }));
    expect(cue()).toBeNull();
  });

  it("does not count a play that was refused", () => {
    render(firstFollow());
    act(() => host.querySelector<HTMLElement>(".hand-slot[data-id='4'] .card")!.click());
    act(() => host.querySelector<HTMLElement>(".hand-slot[data-id='5'] .card")!.click());
    act(() => host.querySelector<HTMLButtonElement>(".action-bar .btn.primary")!.click());
    serverSays({ type: "error", code: "illegal_play", message: "no" });
    expect(localStorage.getItem(PLAYS_KEY)).toBeNull();
  });

  it("nudges after an idle stretch with nothing chosen, and not before", () => {
    vi.useFakeTimers();
    render(firstFollow());
    expect(cue()!.classList.contains("nudge")).toBe(false);
    act(() => { vi.advanceTimersByTime(NUDGE_MS - 100); });
    expect(cue()!.classList.contains("nudge")).toBe(false);
    act(() => { vi.advanceTimersByTime(200); });
    expect(cue()!.classList.contains("nudge")).toBe(true);
  });

  it("explains a lead without lighting anything", () => {
    render(state({ turn: 0, trump: hearts2, hand: clubHand, trick: { leader: 0, plays: [] } }));
    expect(cue()?.textContent).toBe("Your lead: tap a card, then Play");
    expect(dim()).toBe(0);
  });

  const coachRow = () => host.querySelector<HTMLButtonElement>(".hud-menu-row.coach-row");
  const openMenu = () => act(() => host.querySelector<HTMLButtonElement>(".hud-more-btn")!.click());
  const toastText = () => host.querySelector(".toast")?.textContent ?? null;

  it("shows the switch in the menu, on for a newcomer and off after the coach's plays", () => {
    render(firstFollow());
    openMenu();
    expect(coachRow()!.getAttribute("aria-checked")).toBe("true");
    act(() => root.unmount());
    root = createRoot(host);
    localStorage.setItem(PLAYS_KEY, String(COACH_PLAYS));
    render(firstFollow());
    openMenu();
    expect(coachRow()!.getAttribute("aria-checked")).toBe("false");
  });

  it("switched on, coaches a player past the coach's plays", () => {
    localStorage.setItem(PLAYS_KEY, String(COACH_PLAYS));
    localStorage.setItem(COACH_KEY, "on");
    render(firstFollow());
    expect(cue()?.textContent).toBe("Your turn: tap 2 ♣ cards (lit up), then Play");
    expect(lit()).toEqual([4, 5]);
  });

  it("switched off, stays quiet on a newcomer's first turn", () => {
    localStorage.setItem(COACH_KEY, "off");
    render(firstFollow());
    expect(cue()).toBeNull();
    expect(dim()).toBe(0);
  });

  it("flips from the menu row, keeps the choice and says so in a toast", () => {
    localStorage.setItem(PLAYS_KEY, String(COACH_PLAYS));
    render(firstFollow());
    expect(cue()).toBeNull();
    openMenu();
    act(() => coachRow()!.click());
    expect(localStorage.getItem(COACH_KEY)).toBe("on");
    expect(coachRow()!.getAttribute("aria-checked")).toBe("true");
    expect(cue()).not.toBeNull();
    expect(toastText()).toBe("Coach on");
    act(() => coachRow()!.click());
    expect(localStorage.getItem(COACH_KEY)).toBe("off");
    expect(coachRow()!.getAttribute("aria-checked")).toBe("false");
    expect(cue()).toBeNull();
    expect(toastText()).toBe("Coach off");
  });

  it("keeps the switch for the session when storage refuses the write", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("full"); });
    render(firstFollow());
    openMenu();
    act(() => coachRow()!.click());
    expect(coachRow()!.getAttribute("aria-checked")).toBe("false");
    expect(cue()).toBeNull();
    expect(toastText()).toBe("Coach off");
  });

  it("the toast goes after its time", () => {
    vi.useFakeTimers();
    render(firstFollow());
    openMenu();
    act(() => coachRow()!.click());
    expect(toastText()).toBe("Coach off");
    act(() => { vi.advanceTimersByTime(TOAST_MS + 50); });
    expect(toastText()).toBeNull();
  });
});
