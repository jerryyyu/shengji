// A room before its game is a kind of the Play tab's table panel: its code
// and Invite link, Starting level, Allow joiners, the chat row, seats you
// move between until your Start, and the opener's Start now. Room links land
// in it, and a link opened while seated elsewhere asks to leave first. Play
// tables get the same chat row before their game.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { WIDE } from "../home/HomeShell";
import { SHORT_VIEWPORT } from "../phoneLayout";

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

const ws = () => FakeWS.all[FakeWS.all.length - 1];
const say = (msg: unknown) => act(() => ws().deliver(msg));
const allSent = () => FakeWS.all.flatMap((w) => w.sent);
const lastSent = () => allSent().at(-1);
const sentOf = (type: string) => allSent().filter((m) => m.type === type);
const nowSecs = () => Date.now() / 1000;

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
const realMatchMedia = window.matchMedia;
let clipboard: string[] = [];

function viewport(wide: boolean) {
  window.matchMedia = ((q: string) => ({
    matches: q === WIDE ? wide : q === SHORT_VIEWPORT ? false : false,
    media: q, addEventListener() {}, removeEventListener() {},
  })) as unknown as typeof window.matchMedia;
}

beforeEach(() => {
  FakeWS.all = [];
  clipboard = [];
  localStorage.clear();
  viewport(false);
  (globalThis as unknown as { WebSocket: unknown }).WebSocket = FakeWS;
  (window as unknown as { AudioContext: unknown }).AudioContext = class {
    state = "running";
    resume() { return Promise.resolve(); }
  };
  Object.defineProperty(navigator, "share", { configurable: true, value: undefined });
  // jsdom has no layout: the chat log's scroll to its end is a no-op here
  Object.defineProperty(Element.prototype, "scrollIntoView", { configurable: true, value: () => {} });
  Object.defineProperty(navigator, "clipboard", { configurable: true,
    value: { writeText: (t: string) => { clipboard.push(t); return Promise.resolve(); } } });
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    const body = url === "/api/auth/config" ? { google_client_id: "cid" }
      : url === "/api/me" ? { name: "Jerry Yu", email: "j@x", picture: null, display_name: null, name_shown: "Jerry" }
      : null;
    return { status: body ? 200 : 404, json: async () => body ?? {} } as Response;
  }) as typeof fetch;
  vi.resetModules();
});
afterEach(() => {
  vi.useRealTimers();
  act(() => root.unmount());
  host.remove();
  window.matchMedia = realMatchMedia;
  window.history.replaceState(null, "", "/");
});

const settle = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });

async function renderApp() {
  const { default: App } = await import("../App");
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => { root.render(<App />); });
  act(() => ws().onopen?.());
  await settle();
  await settle();
}

const q = (sel: string) => document.querySelector<HTMLElement>(sel);
const button = (text: string | RegExp, scope: ParentNode = document) =>
  [...scope.querySelectorAll<HTMLButtonElement>("button")].find((b) => {
    const t = b.textContent ?? "";
    return typeof text === "string" ? t === text : text.test(t);
  });
const click = (b: HTMLElement | null | undefined) => {
  if (!b) throw new Error("no such button");
  act(() => b.click());
};
const panel = () => q(".tp-room");
const primary = () => panel()!.querySelector<HTMLButtonElement>(".tp-primary")!;

type P = { seat: number; name: string; is_bot?: boolean; connected?: boolean };
function room(over: Record<string, unknown> = {}, players: P[] = [{ seat: 0, name: "Jerry" }]) {
  return {
    type: "room", room: "WXYZ", you: 0, host: 0, opener: 0, start_level: "2", ready: [],
    allow_joiners: true,
    players: players.map((p) => ({ is_bot: false, connected: true, ...p })),
    ...over,
  };
}

describe("a room is a kind of the table panel on Play", () => {
  it("the opener's casual table: code, Invite link, Starting level, Allow joiners, chat; no room screen", async () => {
    await renderApp();
    say(room());
    await settle();
    const p = panel()!;
    expect(p).not.toBeNull();
    expect(q(".room-screen")).toBeNull();
    expect(p.querySelector(".tp-kicker")?.textContent).toBe("Casual");
    expect(p.querySelector(".tp-title")?.textContent).toBe("Your table");
    // alone there is no status line
    expect(p.querySelector(".tp-line")).toBeNull();
    expect(p.querySelector(".tp-code")?.textContent).toBe("WXYZ");
    click(button("Invite link", p));
    await settle();
    expect(clipboard).toEqual([`${window.location.origin}/?code=WXYZ`]);
    expect(button("Link copied", p)).toBeDefined();
    // the opener sets the level on a casual table
    const level = p.querySelector<HTMLSelectElement>("select[aria-label='Starting level']")!;
    act(() => {
      level.value = "5";
      level.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(lastSent()).toEqual({ type: "set_start_level", start_level: "5" });
    const joiners = p.querySelector<HTMLButtonElement>("[role='switch']")!;
    expect(joiners.textContent).toBe("Allow joiners");
    expect(joiners.getAttribute("aria-checked")).toBe("true");
    click(joiners);
    expect(lastSent()).toEqual({ type: "allow_joiners", on: false });
    // labels only: no sub-lines under the rows
    expect(p.querySelector(".room-ranked-note, .tp-hint")).toBeNull();
    expect(p.querySelector(".tp-chat")).not.toBeNull();
    // alone, Start fills the seats with bots
    expect(primary().textContent).toBe("Start with bots");
    click(primary());
    expect(lastSent()).toEqual({ type: "lobby_ready", on: true });
    click(button("Leave", p));
    expect(lastSent()).toEqual({ type: "leave_room" });
    // the Play tab around it: the mode switch shows the table's mode, held still; no code box
    const casual = button("Casual", q(".play-mode")!)!;
    expect(casual.getAttribute("aria-pressed")).toBe("true");
    expect(casual.disabled).toBe(true);
    expect(q("input[aria-label='Room or duo code']")).toBeNull();
  });

  it("a ranked table has no Starting level row: it starts at 2", async () => {
    await renderApp();
    say(room({ ranked: true }, [{ seat: 0, name: "Jerry" }, { seat: 2, name: "Alice" }]));
    const p = panel()!;
    expect(p.querySelector(".tp-kicker")?.textContent).toBe("Ranked");
    expect(p.querySelector("select")).toBeNull();
    expect(p.textContent).not.toContain("Starting level");
    expect(p.querySelector(".tp-code")?.textContent).toBe("WXYZ");
    expect(button("Ranked", q(".play-mode")!)!.getAttribute("aria-pressed")).toBe("true");
  });

  it("a joiner sees the level, moves to an empty seat until their Start, and waits for the others", async () => {
    await renderApp();
    const players = [{ seat: 0, name: "Jerry" }, { seat: 2, name: "Alice" }];
    say(room({ you: 2 }, players));
    let p = panel()!;
    expect(p.querySelector(".tp-title")?.textContent).toBe("You and Jerry");
    expect(p.querySelector("select")).toBeNull();
    expect(p.querySelector(".tp-set-val")?.textContent).toBe("2");
    // anyone seated may switch Allow joiners
    expect(p.querySelector("[role='switch']")?.textContent).toBe("Allow joiners");
    expect(p.querySelectorAll(".tp-line")).toHaveLength(1);
    expect(p.querySelector(".tp-line")?.textContent).toBe("0 of 2 ready");
    const open = [...p.querySelectorAll<HTMLButtonElement>("button.tp-seat")];
    expect(open.map((b) => b.getAttribute("aria-label")))
      .toEqual(["Open seat, other team. Move here", "Open seat, other team. Move here"]);
    click(open[0]);
    expect(lastSent()).toEqual({ type: "swap_seats", a: 2, b: 3, expect: [{ name: "Alice", is_bot: false }, null] });
    // no Start now for a joiner, even when the countdown is over
    say(room({ you: 2, start_now_in: 0 }, players));
    p = panel()!;
    expect(primary().textContent).toBe("Start");
    click(primary());
    expect(lastSent()).toEqual({ type: "lobby_ready", on: true });
    say(room({ you: 2, ready: [2], start_now_in: 0 }, players));
    p = panel()!;
    expect(p.querySelector(".tp-line")?.textContent).toBe("1 of 2 ready");
    expect(primary().textContent).toBe("Waiting for Jerry");
    expect(primary().disabled).toBe(true);
    // after the Start the seats hold still
    expect(p.querySelectorAll("button.tp-seat")).toHaveLength(0);
    expect(p.querySelector(".tp-seat.you .tp-tick")).not.toBeNull();
  });

  it("the opener gets Start now once start_now_in runs out, with the ring counting down", async () => {
    await renderApp();
    vi.useFakeTimers({ toFake: ["Date", "setTimeout", "clearTimeout", "setInterval", "clearInterval"] });
    const players = [{ seat: 0, name: "Jerry" }, { seat: 2, name: "Alice" }];
    say(room({ start_now_in: 30 }, players));
    expect(primary().textContent).toBe("Start");
    click(primary());
    expect(lastSent()).toEqual({ type: "lobby_ready", on: true });
    say(room({ ready: [0], start_now_in: 29 }, players));
    expect(primary().textContent).toContain("Start now");
    expect(primary().disabled).toBe(true);
    expect(primary().querySelector(".timer-ring")?.getAttribute("aria-label")).toBe("29 seconds left");
    act(() => { vi.advanceTimersByTime(29_500); });
    expect(primary().disabled).toBe(false);
    expect(primary().querySelector(".timer-ring")).toBeNull();
    click(primary());
    expect(lastSent()).toEqual({ type: "start_game" });
  });

  it("on a wide screen the room's seats sit round the mini table", async () => {
    viewport(true);
    await renderApp();
    say(room());
    expect(panel()!.classList.contains("tp-wide")).toBe(true);
    expect(panel()!.querySelector(".tp-clock")).not.toBeNull();
  });

  it("the chat row shows the room's chat, opens the chat sheet and sends room chat", async () => {
    await renderApp();
    say(room({}, [{ seat: 0, name: "Jerry" }, { seat: 2, name: "Alice" }]));
    say({ type: "chat_history", room: "WXYZ", messages: [
      { type: "chat", id: 1, room: "WXYZ", seat: 2, name: "Alice", text: "hi!", t: nowSecs() }] });
    const row = panel()!.querySelector<HTMLButtonElement>(".tp-chat")!;
    expect(row.textContent).toContain("Alice: hi!");
    click(row);
    const sheet = q(".chat-panel")!;
    expect(sheet.textContent).toContain("hi!");
    const input = sheet.querySelector<HTMLInputElement>("input")!;
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
    act(() => { setter.call(input, "hello"); input.dispatchEvent(new Event("input", { bubbles: true })); });
    click(button("Send", sheet));
    expect(lastSent()).toEqual({ type: "chat", text: "hello" });
  });
});

describe("room links land in the panel", () => {
  it("a ?room= link joins with no seat picker and shows the room's panel on Play", async () => {
    window.history.replaceState(null, "", "/?room=wxyz");
    await renderApp();
    expect(lastSent()).toEqual({ type: "peek_room", room: "WXYZ" });
    say({ type: "room_seats", room: "WXYZ", in_game: false, seats: [
      { seat: 0, name: "Mei", is_bot: false, connected: true, team: 0, claimable: false },
      { seat: 1, name: "", is_bot: false, connected: false, team: 1, claimable: true },
      { seat: 2, name: "", is_bot: false, connected: false, team: 0, claimable: true },
      { seat: 3, name: "", is_bot: false, connected: false, team: 1, claimable: true }] });
    expect(document.body.textContent).not.toContain("Take a seat");
    expect(lastSent()).toMatchObject({ type: "join_room", room: "WXYZ", name: "Jerry" });
    expect(lastSent()).not.toHaveProperty("seat");
    say(room({ you: 2, host: 0, opener: 0 }, [{ seat: 0, name: "Mei" }, { seat: 2, name: "Jerry" }]));
    await settle();
    expect(panel()?.querySelector(".tp-title")?.textContent).toBe("You and Mei");
    expect(q(".lobby-panel")).not.toBeNull();
  });

  it("a link to another room while seated at a saved one asks to leave that table first", async () => {
    localStorage.setItem("shengji.room", "ABCD");
    window.history.replaceState(null, "", "/?room=WXYZ");
    await renderApp();
    // back to the seat first, not into the linked room
    expect(sentOf("join_room")).toHaveLength(1);
    expect(sentOf("join_room")[0]).toMatchObject({ room: "ABCD" });
    expect(sentOf("peek_room")).toHaveLength(0);
    say(room({ room: "ABCD" }));
    await settle();
    const alert = q("[role='alertdialog']")!;
    expect(alert.querySelector("h2")?.textContent).toBe("Leave to join WXYZ?");
    expect(sentOf("peek_room")).toHaveLength(0);
    click(button("Leave", alert));
    expect(lastSent()).toEqual({ type: "leave_room" });
    await settle();
    expect(q("[role='alertdialog']")).toBeNull();
    say({ type: "left" });
    await settle();
    expect(lastSent()).toEqual({ type: "peek_room", room: "WXYZ" });
  });

  it("Stay keeps the table and drops the link", async () => {
    localStorage.setItem("shengji.room", "ABCD");
    window.history.replaceState(null, "", "/?room=WXYZ");
    await renderApp();
    say(room({ room: "ABCD" }));
    await settle();
    click(button("Stay", q("[role='alertdialog']")!));
    await settle();
    expect(q("[role='alertdialog']")).toBeNull();
    expect(window.location.search).toBe("");
    expect(panel()?.querySelector(".tp-code")?.textContent).toBe("ABCD");
    say({ type: "left" });
    await settle();
    expect(sentOf("peek_room")).toHaveLength(0);
  });

  it("a room link found while at a Play table asks first, and Leave leaves the queue's table", async () => {
    window.history.replaceState(null, "", "/?code=WXYZ");
    await renderApp();
    expect(lastSent()).toEqual({ type: "code_lookup", code: "WXYZ" });
    say({ type: "queue_state", queued: true, count: 2, since: nowSecs(), leader: true, bots_at: nowSecs() + 60,
          table: { id: "t1", you: 0, timer: null, ready: 0, of: 2, you_ready: false, waiting_for: ["Alice"],
                   seats: [{ name: "Jerry", you: true, ready: false, reconnecting: false, since: nowSecs(), pair: false, leader: true },
                           { name: "Alice", you: false, ready: false, reconnecting: false, since: nowSecs(), pair: false, leader: true },
                           null, null] } });
    say({ type: "code_kind", code: "WXYZ", kind: "room" });
    await settle();
    const alert = q("[role='alertdialog']")!;
    expect(alert.querySelector("h2")?.textContent).toBe("Leave to join WXYZ?");
    expect(sentOf("peek_room")).toHaveLength(0);
    click(button("Leave", alert));
    expect(lastSent()).toEqual({ type: "queue_leave" });
    say({ type: "queue_state", queued: false, count: 0 });
    await settle();
    expect(lastSent()).toEqual({ type: "peek_room", room: "WXYZ" });
  });
});

describe("a Play table's chat before the game", () => {
  const table = (over: Record<string, unknown> = {}) => ({
    type: "queue_state", queued: true, count: 2, since: nowSecs(), leader: true, bots_at: nowSecs() + 60,
    table: { id: "t1", you: 0, timer: null, ready: 0, of: 2, you_ready: false, waiting_for: ["Alice"],
             seats: [{ name: "Jerry", you: true, ready: false, reconnecting: false, since: nowSecs(), pair: false, leader: true },
                     { name: "Alice", you: false, ready: false, reconnecting: false, since: nowSecs(), pair: false, leader: true },
                     null, null], ...over },
  });

  it("shows the table's history, sends table_chat, and counts unread lines", async () => {
    await renderApp();
    say(table());
    const row = () => q(".tp-shared .tp-chat")!;
    expect(row()).not.toBeNull();
    say({ type: "table_chat_history", table: "t1", messages: [
      { id: 1, seat: 1, name: "Alice", text: "hi!", t: nowSecs() }] });
    expect(row().textContent).toContain("Alice: hi!");
    // a line from another table is not this one's
    say({ type: "table_chat", table: "t9", id: 7, seat: 1, name: "Zed", text: "nope", t: nowSecs() });
    expect(row().textContent).not.toContain("nope");
    say({ type: "table_chat", table: "t1", id: 2, seat: 1, name: "Alice", text: "ready?", t: nowSecs() });
    expect(row().querySelector(".tp-chat-badge")?.textContent).toBe("2");
    click(row());
    expect(row().querySelector(".tp-chat-badge")).toBeNull();
    const sheet = q(".chat-panel")!;
    expect(sheet.textContent).toContain("ready?");
    const input = sheet.querySelector<HTMLInputElement>("input")!;
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
    act(() => { setter.call(input, "yes"); input.dispatchEvent(new Event("input", { bubbles: true })); });
    click(button("Send", sheet));
    expect(lastSent()).toEqual({ type: "table_chat", text: "yes" });
    expect(sentOf("chat")).toHaveLength(0);
    // the echo lands in the log once
    say({ type: "table_chat", table: "t1", id: 3, seat: 0, name: "Jerry", text: "yes", t: nowSecs() });
    say({ type: "table_chat", table: "t1", id: 3, seat: 0, name: "Jerry", text: "yes", t: nowSecs() });
    expect([...sheet.querySelectorAll(".chat-msg")].filter((m) => m.textContent?.includes("yes"))).toHaveLength(1);
    // a new table starts an empty log
    say(table({ id: "t2" }));
    expect(row().textContent).not.toContain("Alice:");
  });

  it("your own table, alone, has no chat row: the server keeps no table for it", async () => {
    await renderApp();
    say({ type: "queue_state", queued: true, count: 1, since: nowSecs(), leader: true, bots_at: nowSecs() + 60 });
    expect(q(".tp-own")).not.toBeNull();
    expect(q(".tp-chat")).toBeNull();
  });
});
