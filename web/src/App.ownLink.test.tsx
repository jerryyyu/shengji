// Your own table's link while this device holds its seat: the seat comes back
// by its resume, and a state-only answer (a game in progress sends no `room`
// frame) spends the link, so a later Leave opens no Join panel for the room
// just left.
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
  readyState = 1;
  sent: Record<string, unknown>[] = [];
  constructor() { FakeWS.all.push(this); }
  send(data: string) { this.sent.push(JSON.parse(data)); }
  close() { this.readyState = 3; this.onclose?.(); }
  deliver(msg: unknown) { this.onmessage?.({ data: JSON.stringify(msg) }); }
}

const player = (seat: number) => ({
  seat, name: seat === 2 ? "Jerry" : `Bot ${seat + 1}`, is_bot: seat !== 2, connected: true, team: seat % 2,
  cards_left: 25, is_banker: seat === 1, takeover_in: null, controller: seat === 2 ? "human" : "bot",
  reserved_for: null, reserved_secs: null,
});
const STATE = {
  type: "state", room: "WXYZ", you: 2, phase: "deal", players: [0, 1, 2, 3].map(player),
  hand: [], levels: ["5", "3"], games_won: [0, 0], banker: 1, trump: null, turn: null,
  declare_options: [], current_declaration: null, passed: [], trick: null, last_trick: null,
  attacker_points: 0, kitty_count: 8, message: null, notice: null, round_result: null,
};

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
beforeEach(() => {
  FakeWS.all = [];
  localStorage.clear();
  (globalThis as unknown as { WebSocket: unknown }).WebSocket = FakeWS;
  (window as unknown as { AudioContext: unknown }).AudioContext = class {
    state = "running";
    resume() { return Promise.resolve(); }
  };
  globalThis.fetch = vi.fn(async () => ({ status: 404, json: async () => ({}) }) as Response) as typeof fetch;
  vi.resetModules();
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  window.history.replaceState(null, "", "/");
});

const settle = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });

it("own link, a state-only resume, then Leave: the link is spent and no Join panel opens", async () => {
  window.history.replaceState(null, "", "/?code=WXYZ");
  const { saveName, saveRoom } = await import("./ws");
  saveName("Jerry");
  saveRoom("WXYZ");
  const { default: App } = await import("./App");
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => { root.render(<App />); });
  await settle();
  const ws = FakeWS.all[0];
  act(() => ws.onopen?.());
  await settle();
  const sends = () => ws.sent.filter((m) => m.type !== "ping" && m.type !== "client_event");
  expect(sends()).toEqual([{ type: "table_join", code: "WXYZ", name: "Jerry", expect: "room" }]);

  // a game in progress answers with its state alone
  act(() => ws.deliver(STATE));
  await settle();
  expect(host.querySelector(".table-screen")).not.toBeNull();
  expect(window.location.search).toBe("");

  // a deliberate Leave: back on Play, with no peek and no panel for the room just left
  act(() => ws.deliver({ type: "left" }));
  await settle();
  expect(host.querySelector(".table-screen")).toBeNull();
  expect(sends().filter((m) => m.type === "table_peek")).toEqual([]);
  expect(host.textContent).not.toContain("Not now");
  expect(host.querySelector(".tp-acts")).toBeNull();
  expect(window.location.search).toBe("");
});
