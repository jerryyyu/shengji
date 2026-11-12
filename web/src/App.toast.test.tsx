// An error toast is keyed by its showing, not its text: the same error twice
// (Play tapped again with the same wrong card) shows twice, and the fade and
// the unmount end together.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const haptics = vi.hoisted(() => [] as string[]);
vi.mock("./native", async (load) => ({
  ...(await load<typeof import("./native")>()),
  haptic: (kind: string) => { haptics.push(kind); },
}));

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
  cards_left: 25, is_banker: seat === 1, takeover_in: null, controller: seat ? "bot" : "human",
  reserved_for: null, reserved_secs: null,
});
const playing = {
  type: "state", room: "ABCD", you: 0, phase: "play",
  players: [0, 1, 2, 3].map(player),
  hand: [{ id: 1, code: "S6" }, { id: 2, code: "D9" }], levels: ["2", "2"], games_won: [0, 0], banker: 1,
  trump: { suit: "H", rank: "2", declarer: 1 }, turn: 0, declare_options: [],
  current_declaration: null, passed: [], trick: { leader: 1, plays: [{ seat: 1, cards: ["DA"] }] },
  last_trick: null, attacker_points: 0, kitty_count: 8, message: null, notice: null, round_result: null,
};
const followSuit = { type: "error", message: "You must follow suit." };

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
beforeEach(() => {
  vi.useFakeTimers();
  FakeWS.all = [];
  localStorage.clear();
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
  vi.useRealTimers();
});

it("shows the same error again on a repeat, as a new element, and drops it when its fade ends", async () => {
  const { default: App } = await import("./App");
  const { TOAST_MS } = await import("./toast");
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  act(() => root.render(<App />));
  const ws = FakeWS.all[0];
  act(() => ws.onopen?.());
  act(() => ws.deliver(playing));
  expect(host.querySelector(".table-screen")).not.toBeNull();

  act(() => ws.deliver(followSuit));
  const first = host.querySelector<HTMLElement>(".table-screen > .toast");
  expect(first?.textContent).toBe("You must follow suit.");
  // the CSS fade reads the same duration as the timer that unmounts it
  expect(first!.style.getPropertyValue("--toast-ms")).toBe(`${TOAST_MS}ms`);

  // the same error 3.7 s later, when the first one's fade has begun
  act(() => { vi.advanceTimersByTime(3700); });
  act(() => ws.deliver(followSuit));
  const second = host.querySelector<HTMLElement>(".table-screen > .toast");
  expect(second?.textContent).toBe("You must follow suit.");
  expect(second).not.toBe(first);           // remounted: its animation starts over
  expect(first!.isConnected).toBe(false);

  // it stays up for the whole of its own showing, then goes
  act(() => { vi.advanceTimersByTime(TOAST_MS - 1); });
  expect(host.querySelector(".toast")).toBe(second);
  act(() => { vi.advanceTimersByTime(1); });
  expect(host.querySelector(".toast")).toBeNull();
});

it("plays the error haptic, not a selection tick, for an error toast", async () => {
  const { default: App } = await import("./App");
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  act(() => root.render(<App />));
  const ws = FakeWS.all[0];
  act(() => ws.onopen?.());
  act(() => ws.deliver(playing));
  haptics.length = 0;
  act(() => ws.deliver(followSuit));
  expect(haptics).toEqual(["error"]);
});
