// The game is always played sideways. A phone browser held upright at the
// table draws the table turned a quarter turn (the phone layout applies to it
// through the root's class), never a "rotate your phone" card; the lobby and
// the room stay upright.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PHONE_CLASS, PORTRAIT_PHONE, SHORT_VIEWPORT, phoneLayout } from "./phoneLayout";

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

/** A viewport answering the two layout queries as `portrait` / `short`. */
function viewport({ portrait, short }: { portrait: boolean; short: boolean }) {
  window.matchMedia = ((q: string) => ({
    matches: q === PORTRAIT_PHONE ? portrait : q === SHORT_VIEWPORT ? short : false,
    media: q, addEventListener() {}, removeEventListener() {},
  })) as unknown as typeof window.matchMedia;
}

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
const realMatchMedia = window.matchMedia;
beforeEach(() => {
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
  window.matchMedia = realMatchMedia;
  document.documentElement.classList.remove(PHONE_CLASS);
});

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
  return ws;
}

describe("a phone held upright", () => {
  it("keeps the lobby upright, then turns the table sideways instead of asking to rotate", async () => {
    viewport({ portrait: true, short: false });
    const ws = await mountApp();
    const app = () => host.querySelector(".app")!;
    expect(app().classList.contains("rotated")).toBe(false);
    expect(document.documentElement.classList.contains(PHONE_CLASS)).toBe(false);

    act(() => ws.deliver(playing));
    expect(host.querySelector(".table-screen")).not.toBeNull();
    expect(app().classList.contains("rotated")).toBe(true);
    expect(document.documentElement.classList.contains(PHONE_CLASS)).toBe(true);
    expect(host.querySelector(".rotate-hint")).toBeNull();
    expect([...host.querySelectorAll("button")].some((b) => b.textContent === "Leave game")).toBe(false);

    // an error at the table passes inside the turned table
    act(() => ws.deliver({ type: "error", code: "illegal", message: "You must follow suit." }));
    expect(host.querySelector(".app.rotated .table-screen > .toast")?.textContent).toBe("You must follow suit.");
    expect(host.querySelectorAll(".toast")).toHaveLength(1);

    // back in a room: upright again
    act(() => ws.deliver({ type: "room", room: "ABCD", you: 0, host: 0, start_level: "2",
                           players: [{ seat: 0, name: "Me", is_bot: false, connected: true }] }));
    expect(host.querySelector(".tp-room")).not.toBeNull();
    expect(app().classList.contains("rotated")).toBe(false);
    expect(document.documentElement.classList.contains(PHONE_CLASS)).toBe(false);
  });
});

describe("a phone held sideways, a desktop", () => {
  it("draws the table unturned; the phone class follows the height alone", async () => {
    viewport({ portrait: false, short: true });
    const ws = await mountApp();
    expect(document.documentElement.classList.contains(PHONE_CLASS)).toBe(true);
    act(() => ws.deliver(playing));
    expect(host.querySelector(".app")!.classList.contains("rotated")).toBe(false);
    expect(document.documentElement.classList.contains(PHONE_CLASS)).toBe(true);
  });

  it("leaves a tall landscape screen without the phone class or a turn", async () => {
    viewport({ portrait: false, short: false });
    const ws = await mountApp();
    act(() => ws.deliver(playing));
    expect(host.querySelector(".app")!.classList.contains("rotated")).toBe(false);
    expect(document.documentElement.classList.contains(PHONE_CLASS)).toBe(false);
  });
});

it("turns only the table, and only on a portrait phone", () => {
  expect(phoneLayout(false, true, true)).toEqual({ phone: true, rotated: true });
  expect(phoneLayout(false, true, false)).toEqual({ phone: false, rotated: false });
  expect(phoneLayout(true, false, true)).toEqual({ phone: true, rotated: false });
  expect(phoneLayout(true, false, false)).toEqual({ phone: true, rotated: false });
  expect(phoneLayout(false, false, true)).toEqual({ phone: false, rotated: false });
});
