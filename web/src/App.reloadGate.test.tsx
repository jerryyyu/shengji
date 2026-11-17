// The reload gate: a page of an older build reloads once, silently, when the
// server names a newer one and a reload drops nothing: off every table; never
// at a table (a round's end included), offline, over a draft or twice per build.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

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
const result = {
  attacker_points: 0, kitty_points: 0, kitty_cards: [], winner_team: 0, level_change: 1,
  next_banker: 2, new_levels: ["3", "2"], game_over: false, games_won: [0, 0], point_scored: false,
};
const roundEnd = { ...playing, phase: "round_end", trick: null, hand: [], round_result: result, ready: [] };

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
let meta: HTMLMetaElement;
const reload = vi.fn();
const realLocation = window.location;

beforeEach(() => {
  vi.useFakeTimers();
  FakeWS.all = [];
  localStorage.clear();
  sessionStorage.clear();
  reload.mockReset();
  meta = document.createElement("meta");
  meta.name = "shengji-build";
  meta.content = "old111";
  document.head.appendChild(meta);
  (globalThis as unknown as { WebSocket: unknown }).WebSocket = FakeWS;
  (window as unknown as { AudioContext: unknown }).AudioContext = class {
    state = "running";
    resume() { return Promise.resolve(); }
  };
  Object.defineProperty(window, "location", { configurable: true, value: { ...realLocation, reload, search: "" } });
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", { configurable: true, value() { (this as HTMLDialogElement).setAttribute("open", ""); } });
  Object.defineProperty(HTMLDialogElement.prototype, "close", { configurable: true, value() { (this as HTMLDialogElement).removeAttribute("open"); } });
  vi.resetModules();
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  meta.remove();
  Object.defineProperty(window, "location", { configurable: true, value: realLocation });
  vi.useRealTimers();
});

async function mount(): Promise<FakeWS> {
  const { default: App } = await import("./App");
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  act(() => root.render(<App />));
  const ws = FakeWS.all[0];
  act(() => ws.onopen?.());
  return ws;
}

it("reloads once on Play when the server serves a newer build, and not again for that build", async () => {
  const ws = await mount();
  act(() => ws.deliver({ type: "heartbeat_ready", build: "new222" }));
  expect(reload).toHaveBeenCalledTimes(1);
  // the reloaded page still differs (a machine not yet on the new build): it stays
  act(() => ws.deliver({ type: "heartbeat_ready", build: "new222" }));
  act(() => { document.dispatchEvent(new Event("visibilitychange")); });
  expect(reload).toHaveBeenCalledTimes(1);
});

it("never reloads when the server serves this page's build, or names none", async () => {
  const ws = await mount();
  act(() => ws.deliver({ type: "heartbeat_ready", build: "old111" }));
  act(() => ws.deliver({ type: "heartbeat_ready" }));
  act(() => { document.dispatchEvent(new Event("visibilitychange")); });
  expect(reload).not.toHaveBeenCalled();
});

it("waits through a live round and its unconfirmed end", async () => {
  const ws = await mount();
  act(() => ws.deliver(playing));
  act(() => ws.deliver({ type: "heartbeat_ready", build: "new222" }));
  act(() => { document.dispatchEvent(new Event("visibilitychange")); });
  expect(reload).not.toHaveBeenCalled();
  act(() => ws.deliver(roundEnd));
  act(() => { document.dispatchEvent(new Event("visibilitychange")); });
  expect(reload).not.toHaveBeenCalled();
});

it("does not reload at a round's end this player already confirmed", async () => {
  const ws = await mount();
  act(() => ws.deliver({ ...roundEnd, ready: [0] }));
  act(() => ws.deliver({ type: "heartbeat_ready", build: "new222" }));
  expect(reload).not.toHaveBeenCalled();
});

it("waits through a live round and reloads once the player has left the table", async () => {
  const ws = await mount();
  act(() => ws.deliver(playing));
  act(() => ws.deliver({ type: "heartbeat_ready", build: "new222" }));
  expect(reload).not.toHaveBeenCalled();
  act(() => ws.deliver({ type: "left" }));
  expect(reload).toHaveBeenCalledTimes(1);
});

it("never reloads offline", async () => {
  const ws = await mount();
  const { setOffline } = await import("./offlineMode");
  setOffline(true);
  act(() => ws.deliver({ type: "heartbeat_ready", build: "new222" }));
  act(() => { document.dispatchEvent(new Event("visibilitychange")); });
  expect(reload).not.toHaveBeenCalled();
  setOffline(false);
});

it("never reloads twice for one build in a tab", async () => {
  sessionStorage.setItem("shengji.reloadedFor", "new222");
  const ws = await mount();
  act(() => ws.deliver({ type: "heartbeat_ready", build: "new222" }));
  expect(reload).not.toHaveBeenCalled();
});

it("waits while a text field holds a draft, and reloads when the tab is back in view without it", async () => {
  const ws = await mount();
  const input = document.createElement("input");
  input.value = "AB";
  document.body.appendChild(input);
  act(() => ws.deliver({ type: "heartbeat_ready", build: "new222" }));
  expect(reload).not.toHaveBeenCalled();
  input.remove();
  act(() => { document.dispatchEvent(new Event("visibilitychange")); });
  expect(reload).toHaveBeenCalledTimes(1);
});

it("waits while a sheet is open", async () => {
  const ws = await mount();
  const sheet = document.createElement("div");
  sheet.setAttribute("aria-modal", "true");
  document.body.appendChild(sheet);
  act(() => ws.deliver({ type: "heartbeat_ready", build: "new222" }));
  expect(reload).not.toHaveBeenCalled();
  sheet.remove();
});
