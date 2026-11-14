// The iOS app's edge swipe back is off while a game is on the table, so a
// stray swipe never covers a live game with an earlier page, and on again
// everywhere else. Reaching the table adds no history entry, so a browser's
// own back (Safari's edge swipe) has nothing of the game's to undo.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

class FakeWS {
  static all: FakeWS[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  readyState = 1;
  constructor() { FakeWS.all.push(this); }
  send() {}
  close() { this.readyState = 3; this.onclose?.(); }
  deliver(msg: unknown) { this.onmessage?.({ data: JSON.stringify(msg) }); }
}

const player = (seat: number) => ({
  seat, name: seat ? `Bot ${seat}` : "Me", is_bot: seat !== 0, connected: true, team: seat % 2,
  cards_left: 3, is_banker: seat === 1, takeover_in: null, controller: seat ? "bot" : "human",
  reserved_for: null, reserved_secs: null,
});
const playing = {
  type: "state", room: "ABCD", you: 0, phase: "play",
  players: [0, 1, 2, 3].map(player),
  hand: [{ id: 1, code: "S5" }, { id: 2, code: "H7" }, { id: 3, code: "BJ" }],
  levels: ["2", "2"], games_won: [0, 0], banker: 1, trump: { suit: "S", rank: "2", declarer: 1 },
  turn: 0, declare_options: [], current_declaration: null, passed: [], trick: { leader: 0, plays: [] },
  last_trick: null, attacker_points: 0, kitty_count: 8, message: null, notice: null, round_result: null,
};

/** setGameMode's `on`, in call order, from the last fakeShell. */
let gameMode: boolean[] = [];

/** The app's shell, recording each setBackGesture call's `enabled`. */
function fakeShell(): boolean[] {
  const gesture: boolean[] = [];
  gameMode = [];
  const plugin = (name: string) => new Proxy({}, {
    get: (_t, method: string) => (opts?: { enabled?: boolean; on?: boolean }) => {
      if (name === "ShengjiShell" && method === "setBackGesture") gesture.push(opts!.enabled!);
      if (name === "ShengjiShell" && method === "setGameMode") gameMode.push(opts!.on!);
      return Promise.resolve(name === "ShengjiShell" && method === "idiom" ? { idiom: "phone" } : undefined);
    },
  });
  (window as unknown as { Capacitor: unknown }).Capacitor = {
    isNativePlatform: () => true,
    registerPlugin: plugin,
  };
  return gesture;
}

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
beforeEach(() => {
  FakeWS.all = [];
  localStorage.clear();
  window.history.replaceState(null, "", "/");
  (globalThis as unknown as { WebSocket: unknown }).WebSocket = FakeWS;
  (window as unknown as { AudioContext: unknown }).AudioContext = class {
    state = "running";
    resume() { return Promise.resolve(); }
  };
  vi.resetModules();
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  delete (window as unknown as { Capacitor?: unknown }).Capacitor;
});

const flush = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });

async function mountApp() {
  const { default: App } = await import("./App");
  const { saveRoom, saveName } = await import("./ws");
  saveName("Me");
  saveRoom("ABCD");
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  act(() => root.render(<App />));
  const ws = FakeWS.all[0];
  act(() => ws.onopen?.());
  await flush();
  return ws;
}

describe("the app's edge swipe back", () => {
  it("is off at the table and on over every other screen", async () => {
    const gesture = fakeShell();
    const ws = await mountApp();
    expect(gesture).toEqual([true]);          // the lobby

    const entries = window.history.length;
    act(() => ws.deliver(playing));
    await flush();
    expect(host.querySelector(".table-screen")).not.toBeNull();
    expect(gesture).toEqual([true, false]);
    expect(window.history.length).toBe(entries);

    // a page opened over the game turns it back on; back to the game, off
    await act(async () => { window.location.hash = "#/howto"; await new Promise((r) => setTimeout(r, 0)); });
    expect(host.querySelector(".table-screen")).toBeNull();
    expect(gesture).toEqual([true, false, true]);
    window.history.replaceState(null, "", "/");
    await act(async () => { window.dispatchEvent(new HashChangeEvent("hashchange")); await new Promise((r) => setTimeout(r, 0)); });
    expect(host.querySelector(".table-screen")).not.toBeNull();
    expect(gesture).toEqual([true, false, true, false]);

    // the game over, back in the room: on
    act(() => ws.deliver({ type: "room", room: "ABCD", you: 0, host: 0, start_level: "2",
                           players: [{ seat: 0, name: "Me", is_bot: false, connected: true }] }));
    await flush();
    expect(host.querySelector(".tp-room")).not.toBeNull();
    expect(gesture).toEqual([true, false, true, false, true]);
  });

  it("game mode (screen awake, deferred home edge) is on only at the table", async () => {
    fakeShell();
    const ws = await mountApp();
    expect(gameMode).toEqual([false]);
    act(() => ws.deliver(playing));
    await flush();
    expect(host.querySelector(".table-screen")).not.toBeNull();
    expect(gameMode).toEqual([false, true]);
    await act(async () => { window.location.hash = "#/howto"; await new Promise((r) => setTimeout(r, 0)); });
    expect(gameMode).toEqual([false, true, false]);
  });

  it("is never asked for in a browser", async () => {
    const ws = await mountApp();
    const entries = window.history.length;
    act(() => ws.deliver(playing));
    await flush();
    expect(host.querySelector(".table-screen")).not.toBeNull();
    expect(window.history.length).toBe(entries);
  });
});
