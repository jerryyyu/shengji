// How to play's last step deals a practice round: one create_room against
// Beginner bots with start, from outside every table, landing on the table
// when the server starts the filled room.
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
  seat, name: seat === 0 ? "Mei" : `Bot ${seat}`, is_bot: seat !== 0, connected: true, team: seat % 2,
  cards_left: 25, is_banker: seat === 1, takeover_in: null, controller: seat === 0 ? "human" : "bot",
  reserved_for: null, reserved_secs: null,
});

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
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    const body = url === "/api/auth/config" ? { google_client_id: "cid" } : null;
    return { status: body ? 200 : 404, json: async () => body ?? {} } as Response;
  }) as typeof fetch;
  vi.resetModules();
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  window.history.replaceState(null, "", "/");
});

const settle = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });

const practice = () => [...host.querySelectorAll<HTMLButtonElement>(".howto-nav button")]
  .find((b) => b.textContent === "Play a practice round");

async function openLastStep() {
  window.history.replaceState(null, "", "/#/howto/10");
  const { saveName } = await import("./ws");
  saveName("Mei");
  const { default: App } = await import("./App");
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => { root.render(<App />); });
  await settle();
  return FakeWS.all[0];
}

it("deals a Beginner round from the last step, then lands on the table", async () => {
  const ws = await openLastStep();
  // no socket yet: only Done
  expect(practice()).toBeUndefined();
  act(() => ws.onopen?.());
  await settle();
  const before = ws.sent.length;
  await act(async () => { practice()!.click(); await new Promise((r) => setTimeout(r, 0)); });
  const sends = ws.sent.slice(before).filter((m) => m.type !== "ping");
  expect(sends).toEqual([{ type: "create_room", name: "Mei", start: true, bot_level: "beginner" }]);
  expect(window.location.hash).toBe("");

  act(() => ws.deliver({ type: "room", room: "PRAC", you: 0, host: 0, start_level: "2", bot_level: "beginner",
                         players: [0, 1, 2, 3].map((s) => ({ seat: s, name: player(s).name,
                                                             is_bot: s !== 0, connected: true })) }));
  act(() => ws.deliver({
    type: "state", room: "PRAC", you: 0, phase: "deal", players: [0, 1, 2, 3].map(player),
    hand: [], levels: ["2", "2"], games_won: [0, 0], banker: 1, trump: null, turn: null,
    declare_options: [], current_declaration: null, passed: [], trick: null, last_trick: null,
    attacker_points: 0, kitty_count: 8, message: null, notice: null, round_result: null,
  }));
  await settle();
  expect(host.querySelector(".table-screen")).not.toBeNull();
});

it("offers no practice round while you sit in a game", async () => {
  const ws = await openLastStep();
  act(() => ws.onopen?.());
  act(() => ws.deliver({
    type: "state", room: "LIVE", you: 0, phase: "play", players: [0, 1, 2, 3].map(player),
    hand: [], levels: ["2", "2"], games_won: [0, 0], banker: 1, trump: null, turn: 1,
    declare_options: [], current_declaration: null, passed: [], trick: null, last_trick: null,
    attacker_points: 0, kitty_count: 8, message: null, notice: null, round_result: null,
  }));
  await settle();
  expect(host.querySelector(".howto-screen")).not.toBeNull();
  expect(practice()).toBeUndefined();
  const done = [...host.querySelectorAll<HTMLButtonElement>(".howto-nav button")].map((b) => b.textContent);
  expect(done).toEqual(["Done"]);
});
