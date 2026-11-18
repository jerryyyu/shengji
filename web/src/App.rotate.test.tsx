// The game is always played sideways. A phone browser held upright at the
// table draws the table turned a quarter turn (the phone layout applies to it
// through the root's class), never a "rotate your phone" card; the lobby and
// the room stay upright.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PHONE_CLASS, PORTRAIT_PHONE, SHORT_VIEWPORT, TABLET_CLASS, TABLET_SCREEN, phoneLayout } from "./phoneLayout";

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

/** A viewport answering the layout queries as `portrait` / `short` / `touch`. */
function viewport({ portrait, short, touch = false }: { portrait: boolean; short: boolean; touch?: boolean }) {
  window.matchMedia = ((q: string) => ({
    matches: q === PORTRAIT_PHONE ? portrait : q === SHORT_VIEWPORT ? short : q === TABLET_SCREEN ? touch : false,
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
  document.documentElement.classList.remove(PHONE_CLASS, TABLET_CLASS);
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

    // the table left, back on Play: upright again
    act(() => ws.deliver({ type: "left" }));
    expect(host.querySelector(".lobby-panel")).not.toBeNull();
    expect(app().classList.contains("rotated")).toBe(false);
    expect(document.documentElement.classList.contains(PHONE_CLASS)).toBe(false);
  });
});

describe("a phone held sideways, a desktop", () => {
  it("draws the table unturned with the phone class; the lobby keeps the portrait column", async () => {
    viewport({ portrait: false, short: true });
    const ws = await mountApp();
    expect(document.documentElement.classList.contains(PHONE_CLASS)).toBe(false);
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
    expect(document.documentElement.classList.contains(TABLET_CLASS)).toBe(false);
  });
});

describe("a tablet", () => {
  it("draws the table with the tablet class, and the lobby without it", async () => {
    viewport({ portrait: false, short: false, touch: true });
    const ws = await mountApp();
    expect(document.documentElement.classList.contains(TABLET_CLASS)).toBe(false);
    act(() => ws.deliver(playing));
    expect(document.documentElement.classList.contains(TABLET_CLASS)).toBe(true);
    expect(document.documentElement.classList.contains(PHONE_CLASS)).toBe(false);
    expect(host.querySelector(".app")!.classList.contains("rotated")).toBe(false);
    act(() => ws.deliver({ type: "left" }));
    expect(document.documentElement.classList.contains(TABLET_CLASS)).toBe(false);
  });

  it("leaves a phone, which is a touch screen too, on the phone table", async () => {
    viewport({ portrait: false, short: true, touch: true });
    const ws = await mountApp();
    act(() => ws.deliver(playing));
    expect(document.documentElement.classList.contains(PHONE_CLASS)).toBe(true);
    expect(document.documentElement.classList.contains(TABLET_CLASS)).toBe(false);
  });
});

it("turns only the table, and only on a portrait phone", () => {
  expect(phoneLayout(false, true, true)).toEqual({ phone: true, rotated: true, tablet: false });
  expect(phoneLayout(false, true, false)).toEqual({ phone: false, rotated: false, tablet: false });
  expect(phoneLayout(true, false, true)).toEqual({ phone: true, rotated: false, tablet: false });
  // a sideways phone in the lobby keeps the portrait column: no phone class
  expect(phoneLayout(true, false, false)).toEqual({ phone: false, rotated: false, tablet: false });
  expect(phoneLayout(false, false, true)).toEqual({ phone: false, rotated: false, tablet: false });
});

it("sizes the table to the screen only on a touch screen large enough for the tablet table", () => {
  expect(phoneLayout(false, false, true, true)).toEqual({ phone: false, rotated: false, tablet: true });
  // a mouse-driven browser, or a touch window under 810x740, keeps the wide table's fixed sizes
  expect(phoneLayout(false, false, true, false).tablet).toBe(false);
  // below 740px tall or 810px wide the cross cannot keep a six-card trick at 52px cards
  expect(TABLET_SCREEN).toBe("(pointer: coarse) and (min-width: 810px) and (min-height: 740px)");
  // a sideways touch window under that height takes the phone table, which fits a short screen
  expect(SHORT_VIEWPORT).toBe("(max-height: 500px), (pointer: coarse) and (orientation: landscape) and (max-height: 739px)");
  // the phone table and the turned table are touch screens that are not tablets
  expect(phoneLayout(true, false, true, true).tablet).toBe(false);
  expect(phoneLayout(false, true, true, true).tablet).toBe(false);
  // the lobby has one design
  expect(phoneLayout(false, false, false, true).tablet).toBe(false);
});
