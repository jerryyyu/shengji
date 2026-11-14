// Back from the room screen (the browser's back, or the iOS app's edge swipe,
// which walks the same history) opens the leave sheet as its Leave button
// does; Leave lands on Play, whatever page came before the room, and Stay
// keeps the room. A page opened over the
// room still steps back to the room, and the table keeps its own way out.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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

const roomMsg = {
  type: "room", room: "ABCD", you: 0, host: 0, start_level: "2",
  players: [{ seat: 0, name: "Me", is_bot: false, connected: true }],
};
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
  window.history.replaceState(null, "", "/");
});

const flush = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });

/** A step back through the real history, waiting for its popstate. */
async function back() {
  await act(async () => {
    const popped = new Promise((r) => window.addEventListener("popstate", r, { once: true }));
    window.history.back();
    await popped;
    await new Promise((r) => setTimeout(r, 0));
  });
}

/** The app on Play, after a visit to Me, with the socket open. */
async function mountFromMe() {
  const { default: App } = await import("./App");
  const { openTab } = await import("./home/route");
  const { saveName } = await import("./ws");
  saveName("Me");
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  act(() => root.render(<App />));
  const ws = FakeWS.all[0];
  act(() => ws.onopen?.());
  await flush();
  act(() => openTab("me"));
  await flush();
  expect(host.querySelector(".me-page")).not.toBeNull();
  act(() => openTab("play"));
  await flush();
  expect(host.querySelector(".lobby-panel")).not.toBeNull();
  return ws;
}

const sheet = () => host.querySelector<HTMLDialogElement>("[role='alertdialog']");
const sheetText = () => `${sheet()!.querySelector("h2")!.textContent} / ${sheet()!.querySelector("p")!.textContent}`;
const tapIn = (cls: string) => act(() => sheet()!.querySelector<HTMLButtonElement>(cls)!.click());

describe("back from the room screen", () => {
  it("asks through the leave sheet; Leave leaves the room and lands on Play, not Me", async () => {
    const ws = await mountFromMe();
    act(() => ws.deliver(roomMsg));
    await flush();
    expect(host.querySelector(".room-screen")).not.toBeNull();
    const before = ws.sent.length;

    await back();

    expect(ws.sent.slice(before)).toEqual([]);
    expect(host.querySelector(".room-screen")).not.toBeNull();
    expect(sheetText()).toBe("Leave the room? / Free. The room closes.");
    tapIn(".leave-sheet-leave");
    expect(ws.sent.slice(before).map((m) => m.type)).toEqual(["leave_room"]);
    expect(window.location.hash).toBe("");
    expect(host.querySelector(".me-page")).toBeNull();
    expect([...host.querySelectorAll("button")].some((b) => b.textContent === "Back to game")).toBe(false);
    act(() => ws.deliver({ type: "left" }));
    await flush();
    expect(host.querySelector(".room-screen")).toBeNull();
    expect(host.querySelector(".lobby-panel")).not.toBeNull();
  });

  it("lands on Play when the step back reaches Me directly", async () => {
    const ws = await mountFromMe();
    act(() => ws.deliver(roomMsg));
    await flush();
    const before = ws.sent.length;

    // the entry before the room is Me's
    await act(async () => {
      window.history.replaceState(null, "", "/#/me");
      window.dispatchEvent(new PopStateEvent("popstate", { state: null }));
      await new Promise((r) => setTimeout(r, 0));
    });

    expect(host.querySelector(".me-page")).toBeNull();
    expect(sheetText()).toBe("Leave the room? / Free. The room closes.");
    tapIn(".leave-sheet-leave");
    expect(ws.sent.slice(before).map((m) => m.type)).toEqual(["leave_room"]);
    expect(window.location.hash).toBe("");
    act(() => ws.deliver({ type: "left" }));
    await flush();
    expect(host.querySelector(".lobby-panel")).not.toBeNull();
    expect(host.querySelector(".me-page")).toBeNull();
  });

  it("Stay keeps the room, and the next back asks again", async () => {
    const ws = await mountFromMe();
    act(() => ws.deliver({ ...roomMsg, players: [...roomMsg.players,
      { seat: 2, name: "Alice", is_bot: false, connected: true }] }));
    await flush();
    const before = ws.sent.length;

    await back();
    expect(sheetText()).toBe("Leave the room? / Free. The table stays open; Alice can start it.");
    tapIn(".leave-sheet-stay");
    expect(sheet()).toBeNull();
    expect(host.querySelector(".room-screen")).not.toBeNull();
    expect(host.querySelector(".me-page")).toBeNull();

    await back();
    expect(sheet()).not.toBeNull();
    expect(host.querySelector(".room-screen")).not.toBeNull();
    expect(ws.sent.slice(before)).toEqual([]);
  });

  it("a page opened over the room steps back to the room, still in it", async () => {
    const ws = await mountFromMe();
    act(() => ws.deliver(roomMsg));
    await flush();
    const { openTab } = await import("./home/route");
    act(() => openTab("leaderboard"));
    await flush();
    expect(host.querySelector(".room-screen")).toBeNull();
    const before = ws.sent.length;

    await back();

    expect(ws.sent.slice(before)).toEqual([]);
    expect(host.querySelector(".room-screen")).not.toBeNull();
  });

  it("does not leave a game in progress", async () => {
    const ws = await mountFromMe();
    act(() => ws.deliver(roomMsg));
    await flush();
    act(() => ws.deliver(playing));
    await flush();
    expect(host.querySelector(".table-screen")).not.toBeNull();
    const before = ws.sent.length;

    await back();

    expect(ws.sent.slice(before).map((m) => m.type)).not.toContain("leave_room");
    expect(host.querySelector(".table-screen")).not.toBeNull();
  });
});
