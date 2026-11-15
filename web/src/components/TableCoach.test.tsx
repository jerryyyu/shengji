import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
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
const serverSays = (m: unknown) => act(() => { for (const fn of link.listeners) fn(m); });

const { default: Table } = await import("./Table");
const { TOAST_MS } = await import("../toast");
const { NUDGE_MS, PLAYS_KEY, COACH_PLAYS, COACH_KEY, NEWCOMER_ROUNDS, forgetSessionCoach } = await import("../firstTurns");
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


const cue = () => host.querySelector(".hand-line.coach");
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

  it("does not count a move the bot made for you while you were reconnecting", () => {
    const single = { leader: 3, plays: [{ seat: 3, cards: ["S9"] }] };
    render(firstFollow({ trick: single }));
    act(() => host.querySelector<HTMLElement>(".hand-slot .card")!.click());
    act(() => host.querySelector<HTMLButtonElement>(".action-bar .btn.primary")!.click());
    expect(sent).toHaveLength(1);
    // the send never arrived; the socket dropped and the bot played the seat
    act(() => { link.status = "closed"; for (const fn of link.statusListeners) fn(link.status); });
    act(() => { link.status = "open"; for (const fn of link.statusListeners) fn(link.status); });
    // the first state after the reconnect: a smaller hand, the turn moved on,
    // and the seat reports human again because you are connected
    render(firstFollow({ hand: clubHand.slice(1), turn: 1, trick: single }));
    expect(localStorage.getItem(PLAYS_KEY)).toBeNull();
    // the selection still clears and Play is free again
    render(firstFollow({ hand: clubHand.slice(1), trick: single }));
    expect(host.querySelectorAll(".card.selected").length).toBe(0);
    expect(cue()).not.toBeNull();
  });

  it("counts a play acknowledged on the connection it was sent on", () => {
    const single = { leader: 3, plays: [{ seat: 3, cards: ["S9"] }] };
    render(firstFollow({ trick: single }));
    act(() => host.querySelector<HTMLElement>(".hand-slot .card")!.click());
    act(() => host.querySelector<HTMLButtonElement>(".action-bar .btn.primary")!.click());
    render(firstFollow({ hand: clubHand.slice(1), turn: 1, trick: single }));
    expect(localStorage.getItem(PLAYS_KEY)).toBe("1");
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

  it("shares the one line above the hand: a refused Play's reason displaces the cue", () => {
    render(state({ turn: 0, trump: hearts2, hand: clubHand, trick: { leader: 0, plays: [] } }));
    expect(cue()).not.toBeNull();
    act(() => host.querySelector<HTMLElement>(".play-wrap")!.click());
    const lines = host.querySelectorAll(".hand-line");
    expect(lines).toHaveLength(1);
    expect(lines[0].textContent).toBe("Choose the cards to lead");
    expect(cue()).toBeNull();
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

  describe("signed in, on a fresh store", () => {
    afterEach(() => auth.reset());

    it("does not coach an account that has played, and the switch reads off", () => {
      signIn(40);
      render(firstFollow());
      expect(cue()).toBeNull();
      expect(dim()).toBe(0);
      openMenu();
      expect(coachRow()!.getAttribute("aria-checked")).toBe("false");
    });

    it("coaches a new account's first plays, and the switch reads on", () => {
      signIn(NEWCOMER_ROUNDS - 1);
      render(firstFollow());
      expect(cue()?.textContent).toBe("Your turn: tap 2 ♣ cards (lit up), then Play");
      openMenu();
      expect(coachRow()!.getAttribute("aria-checked")).toBe("true");
      act(() => root.unmount());
      root = createRoot(host);
      localStorage.setItem(PLAYS_KEY, String(COACH_PLAYS));
      render(firstFollow());
      expect(cue()).toBeNull();
    });

    it("stops coaching when the account's count arrives mid-turn", () => {
      signIn(0);
      render(firstFollow());
      expect(cue()).not.toBeNull();
      signIn(NEWCOMER_ROUNDS);
      expect(cue()).toBeNull();
    });

    it("leaves it to the browser when the server sends no count", () => {
      signIn(null);
      render(firstFollow());
      expect(cue()).not.toBeNull();
    });

    it("switched on, coaches a veteran account; switched off, a new one stays quiet", () => {
      signIn(40);
      localStorage.setItem(COACH_KEY, "on");
      render(firstFollow());
      expect(cue()).not.toBeNull();
      act(() => root.unmount());
      root = createRoot(host);
      signIn(0);
      localStorage.setItem(COACH_KEY, "off");
      render(firstFollow());
      expect(cue()).toBeNull();
    });

    it("flipping the menu row on a veteran account turns the coach on", () => {
      signIn(40);
      render(firstFollow());
      openMenu();
      act(() => coachRow()!.click());
      expect(localStorage.getItem(COACH_KEY)).toBe("on");
      expect(coachRow()!.getAttribute("aria-checked")).toBe("true");
      expect(cue()).not.toBeNull();
    });
  });

  it("coaches a guest on a fresh store", () => {
    act(() => auth.reset());
    render(firstFollow());
    expect(cue()).not.toBeNull();
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
    // a notice, not an error
    expect(host.querySelector(".toast")!.classList.contains("toast-info")).toBe(true);
    expect(host.querySelector(".toast")!.getAttribute("role")).toBe("status");
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

  it("the header has no Coach chip: the menu's Coach row is the one switch", () => {
    render(firstFollow());
    expect(host.querySelector(".coach-chip")).toBeNull();
    openMenu();
    expect(coachRow()!.getAttribute("aria-checked")).toBe("true");
    act(() => coachRow()!.click());
    expect(coachRow()!.getAttribute("aria-checked")).toBe("false");
    expect(localStorage.getItem(COACH_KEY)).toBe("off");
    expect(cue()).toBeNull();
    act(() => coachRow()!.click());
    expect(coachRow()!.getAttribute("aria-checked")).toBe("true");
    expect(cue()).not.toBeNull();
  });
});

describe("teaching text follows the coach", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => { localStorage.clear(); forgetSessionCoach(); });

  const help = () => host.querySelector(".hand-line.help")?.textContent ?? null;
  const declaring = () => state({ phase: "declare", banker: null, turn: null, trump: null,
    hand: [{ id: 1, code: "H2" }, { id: 2, code: "S5" }], declare_options: [[1]] });
  const burying = () => state({ phase: "bury", banker: 0, turn: 0, trump: hearts2, hand: cards(33),
    players: [0, 1, 2, 3].map((s) => player(s, { is_banker: s === 0 })) });
  const DECLARE = "Declaring picks trump and makes you banker. A pair outbids a single.";
  const BURY = "Pick 8 cards to hide. If the attackers win the last trick, these points count double for them (×4 on a pair lead).";

  it("a newcomer on auto gets the declare and bury help", () => {
    render(declaring());
    expect(help()).toBe(DECLARE);
    render(burying());
    expect(help()).toBe(BURY);
    expect(host.querySelector(".bury-points")!.textContent).toBe("Burying 0 points");
  });

  it("switched on, a player past the coach's plays still gets them", () => {
    localStorage.setItem(PLAYS_KEY, String(COACH_PLAYS));
    localStorage.setItem(COACH_KEY, "on");
    render(declaring());
    expect(help()).toBe(DECLARE);
    render(burying());
    expect(help()).toBe(BURY);
  });

  it("on auto past the coach's plays, declaring and burying show no help", () => {
    localStorage.setItem(PLAYS_KEY, String(COACH_PLAYS));
    render(declaring());
    expect(host.querySelector(".hand-line")).toBeNull();
    expect(host.querySelector(".action-bar .btn.gold")).not.toBeNull();
    render(burying());
    expect(host.querySelector(".hand-line")).toBeNull();
    // the count on Bury is feedback; the points chosen are teaching and follow the coach
    expect(host.querySelector(".action-bar .btn.primary")!.textContent).toBe("Bury (0/8)");
    expect(host.querySelector(".bury-points")).toBeNull();
  });

  it("an account past its newcomer rounds, on a fresh store, sees no help", () => {
    signIn(NEWCOMER_ROUNDS);
    render(declaring());
    expect(host.querySelector(".hand-line")).toBeNull();
    render(burying());
    expect(host.querySelector(".hand-line")).toBeNull();
    act(() => auth.reset());
  });

  it("switched off, a newcomer sees no help, and a refused Play still says why", () => {
    localStorage.setItem(COACH_KEY, "off");
    render(declaring());
    expect(host.querySelector(".hand-line")).toBeNull();
    render(burying());
    expect(host.querySelector(".hand-line")).toBeNull();
    render(state({ turn: 0, trump: hearts2, hand: clubHand, trick: { leader: 0, plays: [] } }));
    expect(host.querySelector(".hand-line")).toBeNull();
    act(() => host.querySelector<HTMLElement>(".play-wrap")!.click());
    expect(host.querySelector(".hand-line")?.textContent).toBe("Choose the cards to lead");
  });
});
