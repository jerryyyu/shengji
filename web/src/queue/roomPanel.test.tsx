// Room links open the Join panel, and a link opened while seated elsewhere
// asks to leave first. Play tables have their rows: every one has a code
// with its Invite link and the chat row before its game, alone too.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { WIDE } from "../home/HomeShell";
import { SHORT_VIEWPORT } from "../phoneLayout";
import { framer } from "./testFrames";

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
  /** As the server sends it: a held queue_state, then its table frame. */
  private frames = framer();
  deliver(msg: unknown) { for (const m of this.frames(msg)) this.onmessage?.({ data: JSON.stringify(m) }); }
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

type P = { seat: number; name: string; is_bot?: boolean; connected?: boolean };
function room(over: Record<string, unknown> = {}, players: P[] = [{ seat: 0, name: "Jerry" }]) {
  return {
    type: "room", room: "WXYZ", you: 0, host: 0, opener: 0, start_level: "2", allow_joiners: true,
    players: players.map((p) => ({ is_bot: false, connected: true, ...p })),
    ...over,
  };
}

describe("a room whose game is starting", () => {
  it("holds Play still until the game's first state: no panel, Play and Duo off, the room's mode", async () => {
    await renderApp();
    expect(button("Play")?.disabled).toBe(false);
    say(room({ matched: true }));
    await settle();
    expect(q(".tp")).toBeNull();
    expect(button("Play")?.disabled).toBe(true);
    expect(button("Duo")?.disabled).toBe(true);
    const ranked = button("Ranked", q(".play-mode")!)!;
    expect(ranked.getAttribute("aria-pressed")).toBe("true");
    expect(ranked.disabled).toBe(true);
    expect(q("input[aria-label='Table code']")).toBeNull();
  });
});

describe("room links land in the panel", () => {
  it("a ?room= link opens the Join panel, and Join sends a room join", async () => {
    window.history.replaceState(null, "", "/?room=wxyz");
    await renderApp();
    // one step: the link's code is peeked, and its panel shows while the seats come
    expect(lastSent()).toEqual({ type: "table_peek", code: "WXYZ" });
    expect(q(".tp-join-code")).not.toBeNull();
    say({ type: "room_seats", room: "WXYZ", in_game: true, seats: [
      { seat: 0, name: "Mei", is_bot: false, connected: true, team: 0, claimable: false, controller: "human", reserved_secs: null },
      { seat: 1, name: "Bot 1", is_bot: true, connected: true, team: 1, claimable: true, controller: "bot", reserved_secs: null },
      { seat: 2, name: "Bot 2", is_bot: true, connected: true, team: 0, claimable: true, controller: "bot", reserved_secs: null },
      { seat: 3, name: "Bot 3", is_bot: true, connected: true, team: 1, claimable: true, controller: "bot", reserved_secs: null }] });
    await settle();
    expect(document.body.textContent).not.toContain("Take a seat");
    const join = q(".tp-join-code")!;
    expect(join.querySelector(".tp-title")?.textContent).toBe("Join Mei");
    expect(sentOf("table_join")).toHaveLength(0);
    // you glow in the first bot seat; Join names it
    expect(join.querySelector(".tp-seat.you.picked")).not.toBeNull();
    click(button("Join", join));
    expect(lastSent()).toMatchObject({ type: "table_join", code: "WXYZ", expect: "room", name: "Jerry", seat: 1 });
  });

  it("a link to another room while seated at a saved one asks to leave that table first", async () => {
    localStorage.setItem("shengji.room", "ABCD");
    window.history.replaceState(null, "", "/?room=WXYZ");
    await renderApp();
    // back to the seat first, not into the linked room
    expect(sentOf("table_join")).toHaveLength(1);
    expect(sentOf("table_join")[0]).toMatchObject({ code: "ABCD" });
    expect(sentOf("table_peek")).toHaveLength(0);
    say(room({ room: "ABCD" }));
    await settle();
    const alert = q("[role='alertdialog']")!;
    expect(alert.querySelector("h2")?.textContent).toBe("Leave to join WXYZ?");
    expect(sentOf("table_peek")).toHaveLength(0);
    click(button("Leave", alert));
    expect(lastSent()).toEqual({ type: "table_leave" });
    await settle();
    expect(q("[role='alertdialog']")).toBeNull();
    say({ type: "left" });
    await settle();
    // the seat is gone: the link's panel opens now
    expect(lastSent()).toEqual({ type: "table_peek", code: "WXYZ" });
    expect(q(".tp-join-code")).not.toBeNull();
    expect(sentOf("table_join")).toHaveLength(1);
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
    expect(sentOf("table_leave")).toHaveLength(0);
    say({ type: "left" });
    await settle();
    expect(sentOf("table_peek")).toHaveLength(0);
  });

  it("a room link found while at a Play table asks first, and Leave leaves the queue's table", async () => {
    window.history.replaceState(null, "", "/?code=WXYZ");
    await renderApp();
    expect(lastSent()).toEqual({ type: "table_peek", code: "WXYZ" });
    // the queue's table, back on this fresh page, holds this device first
    say({ type: "queue_state", queued: true, count: 2, since: nowSecs(), leader: true, bots_at: nowSecs() + 60,
          table: { id: "t1", you: 0, timer: null, ready: 0, of: 2, you_ready: false, waiting_for: ["Alice"],
                   seats: [{ name: "Jerry", you: true, ready: false, reconnecting: false, since: nowSecs(), pair: false, leader: true },
                           { name: "Alice", you: false, ready: false, reconnecting: false, since: nowSecs(), pair: false, leader: true },
                           null, null] } });
    await settle();
    const alert = q("[role='alertdialog']")!;
    expect(alert.querySelector("h2")?.textContent).toBe("Leave to join WXYZ?");
    expect(q(".tp-join-code")).toBeNull();
    click(button("Leave", alert));
    expect(lastSent()).toEqual({ type: "table_leave" });
    say({ type: "queue_state", queued: false, count: 0 });
    await settle();
    expect(lastSent()).toEqual({ type: "table_peek", code: "WXYZ" });
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
    const sheet = q(".q-sheet.chat-sheet")!;
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

  it("alone at your own table: the chat row sends table_chat, and lines with table null show", async () => {
    await renderApp();
    say({ type: "queue_state", queued: true, count: 1, since: nowSecs(), leader: true, bots_at: nowSecs() + 60 });
    const row = () => q(".tp-own .tp-chat")!;
    expect(row()).not.toBeNull();
    click(row());
    const sheet = q(".q-sheet.chat-sheet")!;
    const input = sheet.querySelector<HTMLInputElement>("input")!;
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
    act(() => { setter.call(input, "anyone?"); input.dispatchEvent(new Event("input", { bubbles: true })); });
    click(button("Send", sheet));
    expect(lastSent()).toEqual({ type: "table_chat", text: "anyone?" });
    say({ type: "table_chat", table: null, id: 1, seat: 0, name: "Jerry", text: "anyone?", t: nowSecs() });
    expect([...sheet.querySelectorAll(".chat-msg")].filter((m) => m.textContent?.includes("anyone?"))).toHaveLength(1);
    // a waiting table's line is not your own table's
    say({ type: "table_chat", table: "t9", id: 2, seat: 1, name: "Zed", text: "nope", t: nowSecs() });
    expect(sheet.textContent).not.toContain("nope");
  });

  it("sitting down: the merged history the server sends ahead of the new table's state shows", async () => {
    await renderApp();
    say({ type: "queue_state", queued: true, count: 1, since: nowSecs(), leader: true, bots_at: nowSecs() + 60 });
    say({ type: "table_chat", table: null, id: 1, seat: 0, name: "Jerry", text: "anyone?", t: nowSecs() });
    // the server sends the merged log as you sit, then the queue_state with the table
    say({ type: "table_chat_history", table: "t1", messages: [
      { id: 1, seat: 0, name: "Jerry", text: "anyone?", t: nowSecs() - 5 },
      { id: 2, seat: 1, name: "Alice", text: "me!", t: nowSecs() }] });
    say(table());
    expect(q(".tp-shared .tp-chat")!.textContent).toContain("Alice: me!");
  });

  it("a lone entry's log on a reconnect, sent before its queue_state, shows", async () => {
    await renderApp();
    say({ type: "table_chat_history", table: null, messages: [
      { id: 1, seat: 0, name: "Jerry", text: "back", t: nowSecs() }] });
    say({ type: "queue_state", queued: true, count: 1, since: nowSecs(), leader: true, bots_at: nowSecs() + 60 });
    expect(q(".tp-own .tp-chat")!.textContent).toContain("Jerry: back");
  });
});

describe("every Play table has a code", () => {
  const own = (over: Record<string, unknown> = {}) => ({
    type: "queue_state", queued: true, count: 1, since: nowSecs(), leader: true, bots_at: nowSecs() + 60,
    mode: "ranked", code: "4N5Z", allow_joiners: true, start_level: "2", opener: true, ...over,
  });
  const shared = (over: Record<string, unknown> = {}) => own({
    count: 2, code: "4N5Z", opener: false,
    table: { id: "t1", code: "4N5Z", opener: 0, you: 2, timer: null, ready: 0, of: 2, you_ready: false,
             waiting_for: ["Mei"],
             seats: [{ name: "Mei", you: false, ready: false, reconnecting: false, since: nowSecs(), pair: false, leader: true },
                     null,
                     { name: "Jerry", you: true, ready: false, reconnecting: false, since: nowSecs(), pair: false, leader: true },
                     null] },
    ...over,
  });

  it("a lone Play table shows the code as its Invite, and Allow joiners; a ranked one has no Starting level", async () => {
    await renderApp();
    say(own());
    const p = q(".tp-own")!;
    // your seat shows your own initial, not the first letters of "You"
    expect(p.querySelector(".tp-seat.you .tp-av")?.textContent).toBe("J");
    // the code and Invite are one control: a tap copies the link where there is no share sheet
    const invite = p.querySelector<HTMLButtonElement>("button.tp-invite")!;
    expect(invite.querySelector(".tp-code")?.textContent).toBe("4N5Z");
    expect(invite.textContent).toBe("4N5ZInvite");
    expect(invite.getAttribute("aria-label")).toBe("Invite, table code 4 N 5 Z");
    expect(p.querySelectorAll("button.tp-invite, .tp-code")).toHaveLength(2);
    click(invite);
    await settle();
    expect(clipboard).toEqual([`${window.location.origin}/?code=4N5Z`]);
    expect(invite.getAttribute("aria-label")).toBe("Link copied, table code 4 N 5 Z");
    // ranked starts at 2: no level row; Allow joiners and Wait for people
    // fold into Table settings, which shows no values (both are switches)
    expect(p.textContent).not.toContain("Starting level");
    expect(p.querySelector("select")).toBeNull();
    const settings = p.querySelector<HTMLButtonElement>("button.tp-settings")!;
    expect(settings.textContent).toBe("Table settings");
    expect(p.querySelectorAll("[role='switch']")).toHaveLength(0);
    click(settings);
    expect([...p.querySelectorAll("[role='switch']")].map((b) => [b.textContent, b.getAttribute("aria-checked")]))
      .toEqual([["Allow joiners", "true"], ["Wait for people", "false"]]);
    const joiners = [...p.querySelectorAll<HTMLButtonElement>("[role='switch']")]
      .find((b) => b.textContent === "Allow joiners")!;
    expect(joiners.getAttribute("aria-checked")).toBe("true");
    click(joiners);
    expect(lastSent()).toEqual({ type: "table_allow_joiners", on: false });
    // labels only, no sub-lines
    expect(p.querySelector(".tp-hint, .tp-kicker")).toBeNull();
    // the chat row is a row that opens, with the list chevron, not a text field
    expect(p.querySelector("button.tp-chat .tp-chev")).not.toBeNull();
  });

  /** The Table settings row of a panel, opened. */
  const openSettings = (p: Element) => {
    const row = p.querySelector<HTMLButtonElement>("button.tp-settings")!;
    if (row.getAttribute("aria-expanded") !== "true") click(row);
    return row;
  };

  it("a casual table folds its settings into one Table settings row, closed until tapped", async () => {
    await renderApp();
    say(own({ mode: "casual", start_level: "4", bot_level: "standard" }));
    const p = q(".tp-own")!;
    const row = p.querySelector<HTMLButtonElement>("button.tp-settings")!;
    expect(p.querySelectorAll("button.tp-settings")).toHaveLength(1);
    expect(row.getAttribute("aria-expanded")).toBe("false");
    expect(row.textContent).toBe("Table settingsLevel 4 · Standard");
    expect(row.getAttribute("aria-label")).toBe("Table settings, Level 4, Standard");
    // closed: none of the three setting rows
    expect(p.querySelector("select")).toBeNull();
    expect(p.querySelector(".tp-settings-body")).toBeNull();
    expect(p.textContent).not.toMatch(/Starting level|Allow joiners|Wait for people/);
    // every switch is behind the row: none drawn while it is closed
    expect(p.querySelectorAll("[role='switch']")).toHaveLength(0);
    click(row);
    expect(row.getAttribute("aria-expanded")).toBe("true");
    const body = p.querySelector(".tp-settings-body")!;
    expect(row.getAttribute("aria-controls")).toBe(body.id);
    expect([...body.querySelectorAll("select")].map((s) => s.getAttribute("aria-label"))).toEqual(["Starting level", "Bots"]);
    expect([...body.querySelectorAll("[role='switch']")].map((b) => b.textContent)).toEqual(["Allow joiners", "Wait for people"]);
    // a new frame keeps it open
    say(own({ mode: "casual", start_level: "5", bot_level: "standard" }));
    expect(row.getAttribute("aria-expanded")).toBe("true");
    expect(row.textContent).toBe("Table settingsLevel 5 · Standard");
    click(row);
    expect(row.getAttribute("aria-expanded")).toBe("false");
    expect(row.hasAttribute("aria-controls")).toBe(false);
    expect(p.querySelector(".tp-settings-body")).toBeNull();
    expect([...sentOf("table_start_level"), ...sentOf("table_allow_joiners")]).toEqual([]);
  });

  it("the opener changes each setting from inside Table settings", async () => {
    await renderApp();
    say(own({ mode: "casual", start_level: "2", bot_level: "standard" }));
    const body = () => q(".tp-own .tp-settings-body")!;
    openSettings(q(".tp-own")!);
    const pick = (label: string, value: string) => act(() => {
      const sel = body().querySelector<HTMLSelectElement>(`select[aria-label='${label}']`)!;
      sel.value = value;
      sel.dispatchEvent(new Event("change", { bubbles: true }));
    });
    pick("Starting level", "9");
    expect(lastSent()).toEqual({ type: "table_start_level", start_level: "9" });
    pick("Bots", "advanced");
    expect(lastSent()).toEqual({ type: "table_bot_level", level: "advanced" });
    click([...body().querySelectorAll<HTMLButtonElement>("[role='switch']")].find((b) => b.textContent === "Allow joiners"));
    expect(lastSent()).toEqual({ type: "table_allow_joiners", on: false });
  });

  it("a joiner's Table settings shows the values read-only, and no Allow joiners", async () => {
    await renderApp();
    say(shared({ mode: "casual", start_level: "7", bot_level: "advanced" }));
    const p = q(".tp-shared")!;
    const row = openSettings(p);
    expect(row.textContent).toBe("Table settingsLevel 7 · Advanced");
    const body = p.querySelector(".tp-settings-body")!;
    expect(body.querySelector("select")).toBeNull();
    expect(body.querySelector("[role='switch']")).toBeNull();
    expect([...body.querySelectorAll("[role='group']")].map((g) => g.getAttribute("aria-label")))
      .toEqual(["Starting level 7", "Bots Advanced"]);
  });

  it("a casual table's opener sets the Starting level; others read it", async () => {
    await renderApp();
    say(own({ mode: "casual", start_level: "4" }));
    openSettings(q(".tp-own")!);
    const level = q(".tp-own select[aria-label='Starting level']") as HTMLSelectElement;
    expect(level.value).toBe("4");
    act(() => {
      level.value = "7";
      level.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(lastSent()).toEqual({ type: "table_start_level", start_level: "7" });
    say(shared({ mode: "casual", start_level: "7" }));
    const p = q(".tp-shared")!;
    openSettings(p);
    expect(p.querySelector("select")).toBeNull();
    expect(p.querySelector(".tp-settings-body .tp-set-val")?.textContent).toBe("7");
    expect(p.querySelector(".tp-code")?.textContent).toBe("4N5Z");
  });

  it("Bots is a casual table's select, Standard by default: the opener picks it, others read it, ranked has none", async () => {
    const bots = (p: Element) => p.querySelector<HTMLSelectElement>("select[aria-label='Bots']");
    await renderApp();
    say(own());
    expect(bots(q(".tp-own")!)).toBeNull();
    expect(q(".tp-own")!.textContent).not.toContain("Bots");
    say(own({ mode: "casual", bot_level: "standard" }));
    openSettings(q(".tp-own")!);
    const select = bots(q(".tp-own")!)!;
    expect(select.value).toBe("standard");
    expect([...select.options].map((o) => [o.value, o.textContent])).toEqual(
      [["beginner", "Beginner"], ["standard", "Standard"], ["advanced", "Advanced"]]);
    act(() => {
      select.value = "advanced";
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(lastSent()).toEqual({ type: "table_bot_level", level: "advanced" });
    say(own({ mode: "casual", bot_level: "advanced" }));
    expect(bots(q(".tp-own")!)!.value).toBe("advanced");
    say(shared({ mode: "casual", bot_level: "standard" }));
    const theirs = q(".tp-shared")!;
    openSettings(theirs);
    expect(theirs.querySelector("select")).toBeNull();
    const row = theirs.querySelector("[role='group'][aria-label^='Bots']");
    expect(row?.getAttribute("aria-label")).toBe("Bots Standard");
    expect(row?.querySelector(".tp-set-val")?.textContent).toBe("Standard");
    say(shared({ mode: "casual", bot_level: "beginner" }));
    openSettings(q(".tp-shared")!);
    expect(q(".tp-shared")!.querySelector("[role='group'][aria-label^='Bots']")?.getAttribute("aria-label"))
      .toBe("Bots Beginner");
    say(shared({ bot_level: "advanced" }));
    expect(q(".tp-shared")!.textContent).not.toContain("Bots");
  });

  it("Allow joiners is the opener's switch: a non-opener sees none", async () => {
    const switches = (p: Element) => [...p.querySelectorAll("[role='switch']")]
      .filter((b) => b.textContent === "Allow joiners");
    const seat = (name: string, you: boolean, pair = false) =>
      ({ name, you, ready: false, reconnecting: false, since: nowSecs(), pair, leader: true });
    const table = (opener: number, mine = seat("Jerry", true)) =>
      ({ id: "t1", code: "4N5Z", opener, you: 2, timer: null, ready: 0, of: 2, you_ready: false,
         waiting_for: ["Mei"], seats: [seat("Mei", false), null, mine, null] });
    await renderApp();
    say(shared({ table: table(2), opener: true }));
    const mine = q(".tp-shared")!;
    expect(switches(mine)).toHaveLength(1);
    click(switches(mine)[0] as HTMLElement);
    expect(lastSent()).toEqual({ type: "table_allow_joiners", on: false });
    // a seated non-opener, a single or a pair's leader alike
    say(shared({ table: table(0) }));
    const theirs = q(".tp-shared")!;
    expect(switches(theirs)).toHaveLength(0);
    expect(theirs.textContent).not.toContain("Allow joiners");
    say(shared({ table: table(0, seat("Jerry", true, true)) }));
    expect(switches(q(".tp-shared")!)).toHaveLength(0);
  });

  it("a ranked shared table hides Starting level too", async () => {
    await renderApp();
    say(shared());
    const p = q(".tp-shared")!;
    expect(p.querySelector(".tp-code")?.textContent).toBe("4N5Z");
    expect(p.textContent).not.toContain("Starting level");
  });

  /** A queued table's peek answer (PROTOCOL.md "room_seats", table form). */
  const tableSeats = (over: Record<string, unknown> = {},
                      seats: [string, string | null, boolean?][] = [["taken", "Jerry", true], ["open", null], ["held", null], ["open", null]]) => ({
    type: "room_seats", room: "4N5Z", table: true, mode: "casual", in_game: false,
    allow_joiners: true, full: false, closed: false,
    seats: seats.map(([state, name, ready], seat) => ({ seat, team: seat % 2, state, name, ready: ready ?? false })),
    ...over,
  });
  const typeCode = (code: string) => {
    const input = q("input[aria-label='Table code']") as HTMLInputElement;
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
    act(() => { setter.call(input, code); input.dispatchEvent(new Event("input", { bubbles: true })); });
    click(button("Join"));
  };
  const seatNames = (p: HTMLElement) => [...p.querySelectorAll(".tp-seat")].map((el) => el.getAttribute("aria-label"));

  it("a table code from a link is looked up, opens its Join panel with its seats, and Join sends table_join {code}", async () => {
    window.history.replaceState(null, "", "/?code=4n5z");
    await renderApp();
    expect(lastSent()).toEqual({ type: "table_peek", code: "4N5Z" });
    await settle();
    say(tableSeats());
    await settle();
    const p = q(".tp-join-code")!;
    expect(p.querySelector(".tp-title")?.textContent).toBe("Join Jerry");
    // drawn from the held seat a Duo's code fills: Jerry across, the others open
    // you glow in the held seat a Duo's code fills: Jerry across, the others open
    expect(seatNames(p).sort()).toEqual(["Jerry, ready, your team", "Open seat, other team",
                                         "Open seat, other team", "You, your team"]);
    expect(p.querySelector(".tp-seat.you.picked .tp-seat-name")?.textContent).toBe("You");
    expect(p.querySelector(".tp-seat.person .tp-seat-name")?.textContent).toBe("Jerry ✓");
    expect(p.querySelectorAll(".tp-line")).toHaveLength(0);
    expect(sentOf("table_join")).toHaveLength(0);
    click(button("Join", p));
    expect(lastSent()).toEqual({ type: "table_join", code: "4N5Z", name: expect.any(String) });
    expect(window.location.search).toBe("");
  });

  it("the Join panel is a kind of the one panel: a casual table's tag, and Enter presses Join", async () => {
    window.history.replaceState(null, "", "/?code=4N5Z");
    await renderApp();
    await settle();
    say(tableSeats());
    await settle();
    const p = q(".tp-join-code")!;
    expect(p.querySelector(".tp-tag")?.textContent).toBe("Casual");
    expect(sentOf("table_join")).toHaveLength(0);
    act(() => { document.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true })); });
    expect(lastSent()).toEqual({ type: "table_join", code: "4N5Z", name: expect.any(String) });
  });

  it("a table code typed in the code box opens its seats, and Join joins that table", async () => {
    await renderApp();
    typeCode("4n5z");
    expect(lastSent()).toEqual({ type: "table_peek", code: "4N5Z" });
    await settle();
    say(tableSeats({}, [["taken", "Mei"], ["taken", "Li", true], ["open", null], ["open", null]]));
    await settle();
    const p = q(".tp-join-code")!;
    expect(p.querySelector(".tp-title")?.textContent).toBe("Join Mei");
    expect(seatNames(p).sort()).toEqual(["Li, ready, other team", "Mei, your team",
                                         "Open seat, other team", "You, your team"]);
    expect(sentOf("table_join")).toHaveLength(0);
    click(button("Join", p));
    expect(lastSent()).toEqual({ type: "table_join", code: "4N5Z", name: expect.any(String) });
  });

  it("a full table's seats show with Join disabled", async () => {
    await renderApp();
    typeCode("4N5Z");
    await settle();
    say(tableSeats({ full: true }, [["taken", "Mei"], ["taken", "Li"], ["taken", "Sam"], ["taken", "Ana"]]));
    await settle();
    const p = q(".tp-join-code")!;
    expect(p.querySelector(".tp-line")?.textContent).toBe("Table is full");
    expect(p.querySelectorAll(".tp-line, .tp-led, .tp-hint")).toHaveLength(1);
    expect(p.querySelectorAll(".tp-seat.person")).toHaveLength(4);
    expect(button("Join", p)?.disabled).toBe(true);
    click(button("Join", p));
    expect(sentOf("table_join")).toHaveLength(0);
  });

  it("a closed table (its host's Join in flight) opens no panel, as table_closed does", async () => {
    await renderApp();
    typeCode("4N5Z");
    await settle();
    say(tableSeats({ closed: true }));
    await settle();
    expect(q(".tp-join-code")).toBeNull();
    expect(sentOf("table_join")).toHaveLength(0);
  });

  it("a table that has started answers as a room: the room's seats and a room join", async () => {
    window.history.replaceState(null, "", "/?code=4N5Z");
    await renderApp();
    await settle();
    say({ type: "room_seats", room: "4N5Z", in_game: true, seats: [
      { seat: 0, name: "Jerry", is_bot: false, connected: true, team: 0, claimable: false, controller: "human", reserved_secs: null },
      { seat: 1, name: "Bot 1", is_bot: true, connected: true, team: 1, claimable: true, controller: "bot", reserved_secs: null },
      { seat: 2, name: "Mei", is_bot: false, connected: true, team: 0, claimable: false, controller: "human", reserved_secs: null },
      { seat: 3, name: "Bot 3", is_bot: true, connected: true, team: 1, claimable: true, controller: "bot", reserved_secs: null }] });
    await settle();
    const p = q(".tp-join-code")!;
    expect(p.querySelector(".tp-seat.you")).not.toBeNull();
    click(button("Join", p));
    expect(lastSent()).toMatchObject({ type: "table_join", code: "4N5Z", expect: "room" });
  });

  it("a refused table peek says so once, and a retry of the same code still shows its seats and joins", async () => {
    await renderApp();
    typeCode("4N5Z");
    await settle();
    // the server refuses the peek with room_not_found, echoing the code
    say({ type: "error", code: "room_not_found", peek: "4N5Z", message: "No table has that code." });
    await settle();
    expect(q(".tp-join-code")).toBeNull();
    expect(q(".toast")?.textContent).toBe("No table has that code.");
    typeCode("4N5Z");
    await settle();
    expect(sentOf("table_peek")).toHaveLength(2);
    say(tableSeats());
    await settle();
    const p = q(".tp-join-code")!;
    expect(p.querySelector(".tp-title")?.textContent).toBe("Join Jerry");
    click(button("Join", p));
    expect(lastSent()).toEqual({ type: "table_join", code: "4N5Z", name: expect.any(String) });
  });

  it("a table panel closed before its seats arrive ignores them, and the next ask gets its own", async () => {
    window.history.replaceState(null, "", "/?code=4N5Z");
    await renderApp();
    click(button("Not now", q(".tp-join-code")!));
    // the answer belongs to the closed panel
    say(tableSeats({}, [["taken", "Old"], ["open", null], ["open", null], ["open", null]]));
    await settle();
    expect(q(".tp-join-code")).toBeNull();
    typeCode("4N5Z");
    say(tableSeats());
    await settle();
    expect(q(".tp-join-code .tp-title")?.textContent).toBe("Join Jerry");
  });

  it("a table link opened while at another Play table asks to leave it first", async () => {
    window.history.replaceState(null, "", "/?code=4N5Z");
    await renderApp();
    say(own({ code: "ABCD" }));
    await settle();
    const alert = q("[role='alertdialog']")!;
    expect(alert.querySelector("h2")?.textContent).toBe("Leave to join 4N5Z?");
    expect(sentOf("table_join")).toHaveLength(0);
    click(button("Leave", alert));
    expect(lastSent()).toEqual({ type: "table_leave" });
    say({ type: "queue_state", queued: false, count: 0 });
    await settle();
    // the link goes on to its Join panel; nothing is joined unasked
    expect(lastSent()).toEqual({ type: "table_peek", code: "4N5Z" });
    say(tableSeats());
    await settle();
    expect(sentOf("table_join")).toHaveLength(0);
    click(button("Join", q(".tp-join-code")!));
    expect(lastSent()).toEqual({ type: "table_join", code: "4N5Z", name: expect.any(String) });
  });

  it("your own table's link opened at that table changes nothing", async () => {
    window.history.replaceState(null, "", "/?code=4N5Z");
    await renderApp();
    say(own());
    await settle();
    expect(q("[role='alertdialog']")).toBeNull();
    expect(sentOf("table_join")).toHaveLength(0);
  });
});

describe("a full room's dropped seats are taken only on purpose", () => {
  const seats = (inGame: boolean) => ({
    type: "room_seats", room: "WXYZ", in_game: inGame, seats: [
      { seat: 0, name: "Mei", is_bot: false, connected: true, team: 0, claimable: false, controller: "human", reserved_secs: null },
      { seat: 1, name: "Alice", is_bot: false, connected: false, team: 1, claimable: true, controller: "bot_cover", reserved_secs: null },
      { seat: 2, name: "Sam", is_bot: false, connected: true, team: 0, claimable: false, controller: "human", reserved_secs: null },
      { seat: 3, name: "Li", is_bot: false, connected: true, team: 1, claimable: false, controller: "human", reserved_secs: null }],
  });
  const joinBox = (code: string) => {
    const input = q("input[aria-label='Table code']") as HTMLInputElement;
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
    act(() => { setter.call(input, code); input.dispatchEvent(new Event("input", { bubbles: true })); });
    click(button("Join"));
  };

  const viaLink = async () => {
    window.history.replaceState(null, "", "/?code=WXYZ");
    await renderApp();
    expect(lastSent()).toEqual({ type: "table_peek", code: "WXYZ" });
  };

  it("the Join panel shows Alice (away) chosen; Join → confirm → table_join {seat}", async () => {
    await renderApp();
    joinBox("WXYZ");
    expect(lastSent()).toEqual({ type: "table_peek", code: "WXYZ" });
    say(seats(true));
    await settle();
    // nothing joined by itself
    expect(sentOf("table_join")).toHaveLength(0);
    const panelEl = q(".tp-join-code")!;
    expect(panelEl.querySelector(".tp-title")?.textContent).toBe("Join Mei");
    // no bot seat is left: the away seat is the one chosen, glowing, under its name
    expect(panelEl.querySelector(".tp-seat.picked .tp-seat-name")?.textContent).toBe("Alice (away)");
    expect(panelEl.querySelector(".tp-line")).toBeNull();
    click(button("Join", panelEl));
    const sheet = q("[role='alertdialog']")!;
    expect(sheet.querySelector("h2")?.textContent).toBe("Alice dropped out. Take their seat?");
    expect(sheet.querySelector("p")).toBeNull();
    // Cancel takes nothing
    click(button("Cancel", sheet));
    expect(q("[role='alertdialog']")).toBeNull();
    expect(sentOf("table_join")).toHaveLength(0);
    click(button("Join", q(".tp-join-code")!));
    click(button("Take seat", q("[role='alertdialog']")!));
    expect(lastSent()).toMatchObject({ type: "table_join", code: "WXYZ", expect: "room", seat: 1 });
  });

  it("from a link too: the away seat is taken only through its confirm", async () => {
    await viaLink();
    say(seats(true));
    await settle();
    expect(sentOf("table_join")).toHaveLength(0);
    click(button("Join", q(".tp-join-code")!));
    expect(sentOf("table_join")).toHaveLength(0);
    click(button("Take seat", q("[role='alertdialog']")!));
    expect(lastSent()).toMatchObject({ type: "table_join", code: "WXYZ", expect: "room", seat: 1 });
  });

  it("with a bot seat free, an away seat is a choice too, and choosing it still asks first", async () => {
    await viaLink();
    const withBot = seats(true);
    withBot.seats[3] = { ...withBot.seats[3], name: "Bot 3", is_bot: true, claimable: true, controller: "bot" };
    say(withBot);
    await settle();
    // the bot's seat is chosen; Alice's is not offered while a bot seat is free
    const p = q(".tp-join-code")!;
    expect(p.querySelector(".tp-seat.you.picked")).not.toBeNull();
    expect(button(/Alice \(away\)$/u, p)).toBeUndefined();
    click(button("Join", p));
    expect(q("[role='alertdialog']")).toBeNull();
    expect(lastSent()).toMatchObject({ type: "table_join", code: "WXYZ", expect: "room", seat: 3 });
  });

  it("a room link waits for its peek before it can send a plain Join", async () => {
    await viaLink();
    const join = button("Join", q(".tp-join-code")!);
    expect(join?.disabled).toBe(true);
    expect(sentOf("table_join")).toHaveLength(0);
  });

  it("a choose_seat answer looks again and offers the dropped seats; it never takes one unasked", async () => {
    await renderApp();
    joinBox("WXYZ");
    // a bot seat at the peek, gone by the join
    const withBot = seats(true);
    withBot.seats[3] = { ...withBot.seats[3], name: "Bot 3", is_bot: true, claimable: true, controller: "bot" };
    say(withBot);
    await settle();
    click(button("Join", q(".tp-join-code")!));
    expect(lastSent()).toMatchObject({ type: "table_join", code: "WXYZ", expect: "room", seat: 3 });
    say({ type: "error", code: "choose_seat", message: "Every seat is taken, but a player is offline." });
    expect(lastSent()).toEqual({ type: "table_peek", code: "WXYZ" });
    say(seats(true));
    await settle();
    expect(sentOf("table_join")).toHaveLength(1);
    const p = q(".tp-join-code")!;
    expect(p.querySelector(".tp-seat.picked .tp-seat-name")?.textContent).toBe("Alice (away)");
    click(button("Join", p));
    expect(q("[role='alertdialog']")).not.toBeNull();
    expect(sentOf("table_join")).toHaveLength(1);
  });

  it("a link's Join that the server answers seat_unavailable moves the glow in the same panel", async () => {
    await viaLink();
    const withBot = seats(true);
    withBot.seats[3] = { ...withBot.seats[3], name: "Bot 3", is_bot: true, claimable: true, controller: "bot" };
    say(withBot);
    await settle();
    click(button("Join", q(".tp-join-code")!));
    say({ type: "error", code: "seat_unavailable", message: "That seat was just taken — pick another." });
    expect(lastSent()).toEqual({ type: "table_peek", code: "WXYZ" });
    // the panel stays up while it looks again
    expect(q(".tp-join-code")).not.toBeNull();
    say(seats(true));
    await settle();
    expect(sentOf("table_join")).toHaveLength(1);
    expect(q(".tp-join-code .tp-seat.picked .tp-seat-name")?.textContent).toBe("Alice (away)");
  });

  it("a full table shows the same panel with Join disabled and Table is full", async () => {
    await viaLink();
    const full = seats(true);
    full.seats[1] = { ...full.seats[1], connected: true, claimable: false, controller: "human" };
    say(full);
    await settle();
    const p = q(".tp-join-code")!;
    expect(p.querySelector(".tp-line")?.textContent).toBe("Table is full");
    expect(p.querySelectorAll(".tp-line, .tp-led, .tp-hint")).toHaveLength(1);
    expect(button("Join", p)?.disabled).toBe(true);
    expect(q(".ranked-gate")).toBeNull();
  });

  it("a Play table's link that turns out full (table_full) disables Join in the same panel", async () => {
    window.history.replaceState(null, "", "/?code=4N5Z");
    await renderApp();
    await settle();
    say({ type: "room_seats", room: "4N5Z", table: true, mode: "casual", in_game: false, allow_joiners: true,
          full: false, closed: false,
          seats: [0, 1, 2, 3].map((seat) => ({ seat, team: seat % 2, state: seat ? "open" : "taken",
                                               name: seat ? null : "Jerry", ready: false })) });
    await settle();
    click(button("Join", q(".tp-join-code")!));
    say({ type: "error", code: "table_full", message: "That table is full." });
    await settle();
    const p = q(".tp-join-code")!;
    expect(p.querySelector(".tp-line")?.textContent).toBe("Table is full");
    expect(button("Join", p)?.disabled).toBe(true);
    // the panel says it once; no second line above it
    expect(document.body.textContent).not.toContain("That table is full.");
  });

  it("Not now puts Play back", async () => {
    await renderApp();
    joinBox("WXYZ");
    say(seats(false));
    await settle();
    click(button("Not now", q(".tp-join-code")!));
    expect(q(".tp-join-code")).toBeNull();
    expect(q("button.play-main")).not.toBeNull();
    expect(sentOf("table_join")).toHaveLength(0);
  });

  it("a cancelled peek's late answer does nothing, and the next ask for the same room takes its own", async () => {
    await viaLink();
    click(button("Not now", q(".tp-join-code")!));
    const away = seats(true);
    say(away);   // the cancelled panel's answer: nothing
    await settle();
    expect(q(".tp-join-code")).toBeNull();
    joinBox("WXYZ");
    expect(sentOf("table_peek")).toHaveLength(2);
    say(away);
    await settle();
    expect(sentOf("table_join")).toHaveLength(0);
    expect(q(".tp-join-code .tp-seat.picked .tp-seat-name")?.textContent).toBe("Alice (away)");
  });

  it("Not now ignores the room peek that was already in flight", async () => {
    await viaLink();
    click(button("Not now", q(".tp-join-code")!));
    say({ type: "room_seats", room: "WXYZ", in_game: false, seats: [
      { seat: 0, name: "Mei", is_bot: false, connected: true, team: 0, claimable: false,
        controller: "human", reserved_secs: null },
    ] });
    await settle();
    expect(q(".tp-join-code")).toBeNull();
    expect(sentOf("table_join")).toHaveLength(0);
  });
});
