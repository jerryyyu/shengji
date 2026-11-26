// An invite link through the whole app: the page opens from the link, its
// Join takes a seat, and the table the server confirms for that code settles
// the invite as seated, once, though the lobby that held the Join is gone.
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

const TOKEN = "0123456789ab";
const human = (seat: number) => seat === 0 || seat === 1;
const player = (seat: number) => ({
  seat, name: seat === 0 ? "Mei" : seat === 1 ? "Me" : `Bot ${seat}`, is_bot: !human(seat), connected: true,
  team: seat % 2, cards_left: 25, is_banker: seat === 0, takeover_in: null,
  controller: human(seat) ? "human" : "bot", reserved_for: null, reserved_secs: null,
});
const SEATS = {
  type: "room_seats", room: "WXYZ", in_game: true, seats: [0, 1, 2, 3].map((seat) => ({
    seat, name: seat ? `Bot ${seat}` : "Mei", is_bot: seat > 0, connected: true, team: seat % 2,
    claimable: seat > 0, controller: seat ? "bot" : "human", reserved_secs: null })),
};
const state = (room: string, over: Record<string, unknown> = {}) => ({
  type: "state", room, you: 1, phase: "deal", players: [0, 1, 2, 3].map(player),
  hand: [], levels: ["2", "2"], games_won: [0, 0], banker: 0, trump: null, turn: null,
  declare_options: [], current_declaration: null, passed: [], trick: null, last_trick: null,
  attacker_points: 0, kitty_count: 8, message: null, notice: null, round_result: null, ...over,
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
  globalThis.fetch = vi.fn(async () => ({ status: 404, json: async () => ({}) }) as Response) as typeof fetch;
  vi.resetModules();
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  window.history.replaceState(null, "", "/");
});

const settle = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });

/** The app opened from an invite link to WXYZ, its Join sent; the steps reported so far. */
async function joinFromLink(): Promise<{ ws: FakeWS; steps: unknown[][] }> {
  window.history.replaceState(null, "", `/?code=WXYZ&h=${TOKEN}`);
  const { default: App } = await import("./App");
  const { saveName } = await import("./ws");
  const { setInviteReporter } = await import("./codes");
  saveName("Me");
  const steps: unknown[][] = [];
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => { root.render(<App />); });
  setInviteReporter((...args) => { steps.push(args); });
  const ws = FakeWS.all[0];
  act(() => ws.onopen?.());
  expect(ws.sent.filter((m) => m.type !== "ping").at(-1)).toEqual({ type: "table_peek", code: "WXYZ" });
  act(() => ws.deliver(SEATS));
  act(() => [...host.querySelectorAll<HTMLButtonElement>(".tp-join-code button")]
    .find((b) => b.textContent === "Join")!.click());
  await settle();
  expect(ws.sent.filter((m) => m.type !== "ping").at(-1)).toMatchObject({ type: "table_join", code: "WXYZ", seat: 1 });
  return { ws, steps };
}

it("the link's Join is seated once the server confirms the link's table", async () => {
  const { ws, steps } = await joinFromLink();
  act(() => ws.deliver({ type: "resume", token: "t1", gen: 1 }));
  act(() => ws.deliver(state("WXYZ")));
  await settle();
  expect(host.querySelector(".table-screen")).not.toBeNull();
  expect(steps).toEqual([["opened", undefined, TOKEN], ["seated", undefined, TOKEN]]);
  // later states of the same table say nothing more
  act(() => ws.deliver(state("WXYZ", { phase: "play" })));
  expect(steps).toHaveLength(2);
});

it("a handover's waiting state is not the seat yet; the state that follows it is", async () => {
  const { ws, steps } = await joinFromLink();
  act(() => ws.deliver(state("WXYZ", { joining_you: true })));
  await settle();
  expect(steps).toEqual([["opened", undefined, TOKEN]]);
  act(() => ws.deliver(state("WXYZ")));
  expect(steps).toEqual([["opened", undefined, TOKEN], ["seated", undefined, TOKEN]]);
});

it("another table's state is not the invite's seat", async () => {
  const { ws, steps } = await joinFromLink();
  act(() => ws.deliver(state("ABCD")));
  await settle();
  expect(steps).toEqual([["opened", undefined, TOKEN]]);
});

it("an ordinary resume of a saved seat at the link's table settles nothing without the link's Join", async () => {
  window.history.replaceState(null, "", "/");
  const { default: App } = await import("./App");
  const { saveName, saveRoom } = await import("./ws");
  const { setInviteReporter } = await import("./codes");
  saveName("Me");
  saveRoom("WXYZ");
  const steps: unknown[][] = [];
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => { root.render(<App />); });
  setInviteReporter((...args) => { steps.push(args); });
  const ws = FakeWS.all[0];
  act(() => ws.onopen?.());
  act(() => ws.deliver({ type: "resume", token: "t1", gen: 1 }));
  act(() => ws.deliver(state("WXYZ")));
  await settle();
  expect(steps).toEqual([]);
});

/** Type `code` in the Play box, Join its panel's seat. */
async function typedJoin(ws: FakeWS, code: string): Promise<void> {
  const input = host.querySelector<HTMLInputElement>(".room-input")!;
  act(() => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, code);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  act(() => host.querySelector<HTMLButtonElement>(".join-row button")!.click());
  expect(ws.sent.filter((m) => m.type !== "ping").at(-1)).toEqual({ type: "table_peek", code });
  act(() => ws.deliver({ ...SEATS, room: code }));
  act(() => [...host.querySelectorAll<HTMLButtonElement>(".tp-join-code button")]
    .find((b) => b.textContent === "Join")!.click());
  await settle();
  expect(ws.sent.filter((m) => m.type !== "ping").at(-1)).toMatchObject({ type: "table_join", code });
}

it("a refused link Join, then the same code typed and joined, is not the invite's seat", async () => {
  const { ws, steps } = await joinFromLink();
  act(() => ws.deliver({ type: "error", code: "table_closed", message: "That table has closed." }));
  await settle();
  await typedJoin(ws, "WXYZ");
  act(() => ws.deliver({ type: "resume", token: "t1", gen: 1 }));
  act(() => ws.deliver(state("WXYZ")));
  await settle();
  expect(host.querySelector(".table-screen")).not.toBeNull();
  expect(steps).toEqual([["opened", undefined, TOKEN]]);
});

it("Not now after a link Join, then the code typed and joined, is not the invite's seat", async () => {
  const { ws, steps } = await joinFromLink();
  // a refusal that hands the panel back
  act(() => ws.deliver({ type: "error", code: "rate_limited", message: "Too many requests; wait a minute." }));
  act(() => [...host.querySelectorAll<HTMLButtonElement>(".tp-join-code button")]
    .find((b) => b.textContent === "Not now")!.click());
  await settle();
  await typedJoin(ws, "WXYZ");
  act(() => ws.deliver(state("WXYZ")));
  await settle();
  expect(steps).toEqual([["opened", undefined, TOKEN]]);
});

it("a search started after the link's Join supersedes it", async () => {
  const { ws, steps } = await joinFromLink();
  const { queue } = await import("./queue/store");
  act(() => queue.join());
  expect(ws.sent.filter((m) => m.type !== "ping").at(-1)).toMatchObject({ type: "queue_join" });
  act(() => ws.deliver(state("WXYZ")));
  await settle();
  expect(steps).toEqual([["opened", undefined, TOKEN]]);
});

/** A waiting table at WXYZ: its host at 0, seats 1 to 3 open. */
const TABLE_SEATS = {
  type: "room_seats", room: "WXYZ", table: true, mode: "casual", in_game: false, allow_joiners: true,
  full: false, closed: false,
  seats: [{ seat: 0, team: 0, state: "taken", name: "Mei", ready: false },
          { seat: 1, team: 1, state: "open", name: null, ready: false },
          { seat: 2, team: 0, state: "open", name: null, ready: false },
          { seat: 3, team: 1, state: "open", name: null, ready: false }],
};
const sitter = (name: string, you: boolean) => ({ name, you, ready: false, reconnecting: false,
  since: Math.floor(Date.now() / 1000) - 5, sit: `sit-${name}`, pair: false, leader: true });

/** The app opened from an invite link to the waiting table WXYZ, its Join
 *  sent, and the server's queue_state and table frame seating you at 1. */
async function sitFromLink(): Promise<{ ws: FakeWS; steps: unknown[][] }> {
  window.history.replaceState(null, "", `/?code=WXYZ&h=${TOKEN}`);
  const { default: App } = await import("./App");
  const { saveName } = await import("./ws");
  const { setInviteReporter } = await import("./codes");
  const { tableFrameFor } = await import("./queue/testFrames");
  saveName("Me");
  const steps: unknown[][] = [];
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => { root.render(<App />); });
  setInviteReporter((...args) => { steps.push(args); });
  const ws = FakeWS.all[0];
  act(() => ws.onopen?.());
  act(() => ws.deliver(TABLE_SEATS));
  act(() => [...host.querySelectorAll<HTMLButtonElement>(".tp-join-code button")]
    .find((b) => b.textContent === "Join")!.click());
  await settle();
  expect(ws.sent.filter((m) => m.type !== "ping").at(-1)).toMatchObject({ type: "table_join", code: "WXYZ" });
  const since = Math.floor(Date.now() / 1000);
  const qs = { type: "queue_state", queued: true, count: 2, since, front: false, party_id: null, leader: true,
               mode: "casual", code: "WXYZ", opener: false,
               table: { id: "t1", code: "WXYZ", opener: 0, you: 1, seats: [sitter("Mei", false), sitter("Me", true), null, null],
                        timer: null, ready: 0, of: 2, you_ready: false, waiting_for: [] } };
  act(() => ws.deliver(qs));
  act(() => ws.deliver(tableFrameFor(qs)));
  await settle();
  expect(host.querySelector(".tp-join-code")).toBeNull();
  return { ws, steps };
}

it("a link Join seated at a waiting table counts once, though its game never starts", async () => {
  const { ws, steps } = await sitFromLink();
  expect(steps).toEqual([["opened", undefined, TOKEN], ["seated", undefined, TOKEN]]);
  // the friend leaves before play: still one seat
  act(() => ws.deliver({ type: "queue_state", queued: false, count: 1 }));
  await settle();
  expect(steps).toHaveLength(2);
});

it("a waiting table's seat and its later game start count once", async () => {
  const { ws, steps } = await sitFromLink();
  act(() => ws.deliver({ type: "match_started" }));
  act(() => ws.deliver(state("WXYZ")));
  await settle();
  expect(host.querySelector(".table-screen")).not.toBeNull();
  expect(steps).toEqual([["opened", undefined, TOKEN], ["seated", undefined, TOKEN]]);
});
