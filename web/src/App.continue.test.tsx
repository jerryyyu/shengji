// Continue a saved game: the game page's Continue sends one `create_room` with
// `resume_from` and `start`, leaves the saved-games route, and lands on the
// table at the saved levels when the server starts the filled room.
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

const GAME = {
  id: "g1", room_code: "SDGE", started_at: 1790000000, ended_at: 1790001800, seat: 2,
  players: ["Bot 1", "Bot 2", "Jerry", "Bot 3"], rounds: [1, 2], final_levels: ["5", "3"],
  games_won: [0, 0], incomplete: false,
};
const player = (seat: number) => ({
  seat, name: seat === 2 ? "Jerry" : `Bot ${seat + 1}`, is_bot: seat !== 2, connected: true, team: seat % 2,
  cards_left: 25, is_banker: seat === 1, takeover_in: null, controller: seat === 2 ? "human" : "bot",
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
    const body = url === "/api/auth/config" ? { google_client_id: "cid" }
      : url === "/api/me" ? { name: "Jerry Yu", email: "j@x", picture: null, display_name: null, name_shown: "Jerry" }
      : url.startsWith("/api/me/games?") ? { games: [GAME], next_before: null }
      : url === "/api/me/games/g1" ? { ...GAME, round_results: [] }
      : null;
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

it("Continue sends one create_room with resume_from and start, then lands on the table", async () => {
  window.history.replaceState(null, "", "/#/games/g1");
  const { saveName } = await import("./ws");
  saveName("Jerry");
  const { default: App } = await import("./App");
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => { root.render(<App />); });
  await settle();
  const cont = () => host.querySelector<HTMLButtonElement>(".games-actions .games-continue")!;
  // no socket yet: Continue waits for one
  expect(cont().disabled).toBe(true);
  const ws = FakeWS.all[0];
  act(() => ws.onopen?.());
  expect(cont().disabled).toBe(false);

  await act(async () => { cont().click(); await new Promise((r) => setTimeout(r, 0)); });
  const sends = () => ws.sent.filter((m) => m.type !== "ping");
  expect(sends()).toEqual([{ type: "create_room", name: "Jerry", resume_from: "g1", start: true }]);
  expect(window.location.hash).toBe("");

  // the server made the room with the account in its seat and bots around it
  act(() => ws.deliver({ type: "room", room: "WXYZ", you: 2, host: 2, start_level: "2",
                         players: [0, 1, 2, 3].map((s) => ({ seat: s, name: player(s).name,
                                                             is_bot: s !== 2, connected: true })) }));
  // the server starts it: the client sends nothing more
  expect(sends()).toHaveLength(1);

  act(() => ws.deliver({
    type: "state", room: "WXYZ", you: 2, phase: "deal", players: [0, 1, 2, 3].map(player),
    hand: [], levels: ["5", "3"], games_won: [0, 0], banker: 1, trump: null, turn: null,
    declare_options: [], current_declaration: null, passed: [], trick: null, last_trick: null,
    attacker_points: 0, kitty_count: 8, message: null, notice: null, round_result: null,
  }));
  await settle();
  expect(host.querySelector(".table-screen")).not.toBeNull();
  expect(host.querySelector(".tabbar")).toBeNull();
  expect(localStorage.getItem("shengji.room")).toBe("WXYZ");
});

it("a refused Continue says so and stays off the table", async () => {
  window.history.replaceState(null, "", "/#/games/g1");
  const { default: App } = await import("./App");
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => { root.render(<App />); });
  await settle();
  const ws = FakeWS.all[0];
  act(() => ws.onopen?.());
  await act(async () => {
    host.querySelector<HTMLButtonElement>(".games-continue")!.click();
    await new Promise((r) => setTimeout(r, 0));
  });
  act(() => ws.deliver({ type: "error", code: "resume_unavailable", message: "That game can't be continued." }));
  await settle();
  expect(host.textContent).toContain("That game can't be continued.");
  expect(host.querySelector(".table-screen")).toBeNull();
});
