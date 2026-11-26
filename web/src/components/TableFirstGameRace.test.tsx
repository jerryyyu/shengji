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

const { default: Table } = await import("./Table");
const { forgetSessionCoach, setCoachSetting } = await import("../firstTurns");
const { auth } = await import("../auth");
const { telemetry } = await import("../telemetry");
const signIn = (rounds: number | null) => act(() => auth.signedIn({
  name: "Jerry Yu", email: "j@x", picture: null, display_name: null, name_shown: "Jerry", rounds_played: rounds }));
const { PRESELECT_MS } = await import("../firstGame");
const { forgetHintMemory, setHintLoader } = await import("./useFirstGameHint");
const realChunk = await import("../hintPick");
// the bot's chunk answers only when a test opens its gate
const gate = { open: () => {} };

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
const taps = () => telemetry.pending().filter((e) => e.e === "tap").map((e) => (e as { id: string }).id);
const hearts2 = { suit: "H", rank: "2", declarer: 1 };
const clubHand: HandCard[] = ["S3", "S4", "D3", "C6", "CK", "H4"].map((code, i) => ({ id: i + 1, code }));
const follow = (over: Partial<GameState> = {}) => state({
  turn: 0, trump: hearts2, hand: clubHand, trick: { leader: 3, plays: [{ seat: 3, cards: ["C9", "C9"] }] }, ...over });
async function flush() {
  await act(async () => { for (let i = 0; i < 20; i += 1) await Promise.resolve(); });
}
// the 15 s pass and the import starts, held at the gate
async function idleUntilImport() {
  await act(async () => { vi.advanceTimersByTime(PRESELECT_MS); });
  await flush();
  expect(selected()).toBe(0);
}
async function answer() {
  gate.open();
  await flush();
}

describe("a bot that answers after the turn's hint has ended chooses nothing", () => {
  beforeEach(() => {
    localStorage.clear();
    forgetHintMemory();
    telemetry.reset();
    let open = () => {};
    const wait = new Promise<void>((r) => { open = r; });
    gate.open = open;
    setHintLoader(() => wait.then(() => realChunk));
    vi.useFakeTimers();
  });
  afterEach(() => {
    localStorage.clear();
    forgetSessionCoach();
    forgetHintMemory();
    telemetry.reset();
    act(() => auth.reset());
    setHintLoader(null);
    vi.useRealTimers();
  });

  it("the control: an answer on a live turn selects the two clubs", async () => {
    render(follow());
    await idleUntilImport();
    await answer();
    expect(selected()).toBe(2);
    expect(taps()).toEqual(["hint_preselect"]);
  });

  it("the coach switched off on the same decision", async () => {
    render(follow());
    await idleUntilImport();
    act(() => setCoachSetting("off"));
    await answer();
    expect(selected()).toBe(0);
    expect(taps()).not.toContain("hint_preselect");
  });

  it("the first game no longer applies on the same decision", async () => {
    render(follow());
    await idleUntilImport();
    // sign-in settles: an account with rounds played, at a table it did not hold
    signIn(5);
    await answer();
    expect(selected()).toBe(0);
    expect(taps()).not.toContain("hint_preselect");
  });

  it("the table unmounted", async () => {
    render(follow());
    await idleUntilImport();
    act(() => root.unmount());
    root = createRoot(host);
    await answer();
    expect(taps()).not.toContain("hint_preselect");
  });

  it("the turn moved on", async () => {
    render(follow());
    await idleUntilImport();
    render(follow({ turn: 1, hand: clubHand.slice(0, 4),
      trick: { leader: 3, plays: [{ seat: 3, cards: ["C9", "C9"] }, { seat: 0, cards: ["CK", "S4"] }] } }));
    await answer();
    expect(selected()).toBe(0);
    expect(taps()).not.toContain("hint_preselect");
  });
});
