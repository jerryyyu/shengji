// "Back to lobby" after a finished game used to reload the whole page. It now
// resets in-app: the lobby must come back on the same socket, with the table
// (and its connection subscription) gone and no reload.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

class FakeWS {
  static OPEN = 1;
  static all: FakeWS[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  sent: { type: string }[] = [];
  readyState = 1;
  constructor() { FakeWS.all.push(this); }
  send(raw: string) { this.sent.push(JSON.parse(raw)); }
  close() { this.readyState = 3; this.onclose?.(); }
  deliver(msg: unknown) { this.onmessage?.({ data: JSON.stringify(msg) }); }
}

const player = (seat: number, name: string) => ({
  seat, name, is_bot: seat !== 0, connected: true, team: seat % 2, cards_left: 0,
  is_banker: seat === 0, takeover_in: null, controller: seat ? "bot" : "human",
  reserved_for: null, reserved_secs: null,
});
const gameOver = {
  type: "state", room: "ABCD", you: 0, phase: "game_over",
  players: [player(0, "Me"), player(1, "Bot 1"), player(2, "Bot 2"), player(3, "Bot 3")],
  hand: [], levels: ["A", "5"], games_won: [1, 0], banker: 0,
  trump: { suit: "S", rank: "A", declarer: 0 }, turn: null, declare_options: [],
  current_declaration: null, passed: [], trick: { leader: 0, plays: [] }, last_trick: null,
  attacker_points: 30, kitty_count: 8, message: null, notice: null,
  round_result: {
    attacker_points: 30, kitty_points: 0, kitty_cards: [], winner_team: 0, level_change: 3,
    next_banker: 2, new_levels: ["2", "2"], games_won: [1, 0], point_scored: true, game_over: true,
  },
};

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
const reload = vi.fn();
const realLocation = window.location;
beforeEach(() => {
  FakeWS.all = [];
  localStorage.clear();
  (globalThis as unknown as { WebSocket: unknown }).WebSocket = FakeWS;
  // The audio module unlocks on the first click; jsdom has no Web Audio.
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
  Object.defineProperty(window, "location", { configurable: true, value: realLocation });
});

it("Back to lobby returns to the lobby on the same socket without reloading", async () => {
  const { default: App } = await import("./App");
  const { saveRoom, saveName, getSavedRoom } = await import("./ws");
  saveName("Me");
  saveRoom("ABCD");
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  act(() => root.render(<App />));
  const ws = FakeWS.all[0];
  act(() => ws.onopen?.());
  expect(ws.sent.map((m) => m.type)).toEqual(["join_room"]);   // resumed the saved room
  act(() => ws.deliver(gameOver));
  const back = [...host.querySelectorAll("button")].find((b) => b.textContent === "Back to lobby");
  expect(back).toBeTruthy();

  act(() => back!.click());

  expect(reload).not.toHaveBeenCalled();
  expect(ws.sent.map((m) => m.type)).toEqual(["join_room", "leave_room"]);
  expect(getSavedRoom()).toBeNull();
  expect(host.querySelector(".lobby-panel")).not.toBeNull();
  expect(host.querySelector(".table-screen")).toBeNull();
  // A state the server sent before it processed leave_room must not bring
  // the finished table back.
  act(() => ws.deliver(gameOver));
  expect(host.querySelector(".table-screen")).toBeNull();
  act(() => ws.deliver({ type: "left" }));
  // The same socket serves the next room; no second connection was opened.
  act(() => ws.deliver({ type: "room", room: "WXYZ", you: 0, host: 0, start_level: "2",
                         players: [{ seat: 0, name: "Me", is_bot: false, connected: true }] }));
  expect(host.querySelector(".room-screen")).not.toBeNull();
  expect(FakeWS.all).toHaveLength(1);
  expect(ws.readyState).toBe(1);
});
