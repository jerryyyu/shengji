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

// counts loads of the hint's bot chunk: its factory runs on the first import only
const loads = vi.hoisted(() => ({ n: 0 }));
vi.mock("../hintPick", async (load) => {
  loads.n += 1;
  return await load<typeof import("../hintPick")>();
});
const { default: Table } = await import("./Table");
const { forgetSessionCoach } = await import("../firstTurns");
const { PRESELECT_MS, FIRST_GAME_DONE_KEY } = await import("../firstGame");
const { forgetHintMemory } = await import("./useFirstGameHint");

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




const selected = () => host.querySelectorAll(".hand .card.selected").length;
const hearts2 = { suit: "H", rank: "2", declarer: 1 };
const clubHand: HandCard[] = ["S3", "S4", "D3", "C6", "CK", "H4"].map((code, i) => ({ id: i + 1, code }));
const follow = (over: Partial<GameState> = {}) => state({
  turn: 0, trump: hearts2, hand: clubHand, trick: { leader: 3, plays: [{ seat: 3, cards: ["C9", "C9"] }] }, ...over });
async function flush() {
  await act(async () => { for (let i = 0; i < 20; i += 1) await Promise.resolve(); });
}

// these run in order: the module registry is the file's, so the first load counts
describe("the hint's bot chunk", () => {
  beforeEach(() => { localStorage.clear(); forgetHintMemory(); vi.useFakeTimers(); });
  afterEach(() => { localStorage.clear(); forgetSessionCoach(); forgetHintMemory(); vi.useRealTimers(); });

  it("is never loaded for a player past their first game", async () => {
    localStorage.setItem(FIRST_GAME_DONE_KEY, "1");
    render(follow());
    await act(async () => { vi.advanceTimersByTime(PRESELECT_MS * 4); });
    await flush();
    expect(selected()).toBe(0);
    expect(loads.n).toBe(0);
  });

  it("is not loaded on a first game's turn before it sits idle, and is once it has", async () => {
    render(follow());
    await act(async () => { vi.advanceTimersByTime(PRESELECT_MS - 100); });
    await flush();
    expect(loads.n).toBe(0);
    await act(async () => { vi.advanceTimersByTime(100); });
    await vi.waitFor(() => { expect(selected()).toBe(2); });
    expect(loads.n).toBe(1);
  });
});
