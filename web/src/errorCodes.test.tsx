// Who says each error the server sends, as a player sees it: the toast's
// final words and tone (or no toast), and what the error does to the screen.
// One row per route in errorCodes.ts; the app is rendered whole, with a fake
// socket, so all three listeners (codeJoin, App, the queue store) hear it.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { GUARD_MS } from "./queue/useKindGuard";
import { framer } from "./queue/testFrames";

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
const sent = () => FakeWS.all.flatMap((w) => w.sent);
const lastSent = () => sent()[sent().length - 1];
const nowSecs = () => Date.now() / 1000;

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
const realMatchMedia = window.matchMedia;
/** Every toast shown since the app rendered, in order. */
let shown: { text: string; sub?: string; info?: boolean }[];

beforeEach(() => {
  FakeWS.all = [];
  localStorage.clear();
  window.matchMedia = ((q: string) => ({
    matches: false, media: q, addEventListener() {}, removeEventListener() {},
  })) as unknown as typeof window.matchMedia;
  (globalThis as unknown as { WebSocket: unknown }).WebSocket = FakeWS;
  (window as unknown as { AudioContext: unknown }).AudioContext = class {
    state = "running";
    resume() { return Promise.resolve(); }
  };
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
  act(() => root.unmount());
  host.remove();
  window.matchMedia = realMatchMedia;
  window.history.replaceState(null, "", "/");
});

const settle = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });

async function renderApp() {
  const { default: App } = await import("./App");
  const toast = await import("./toast");
  shown = [];
  let last = -1;
  toast.subscribeToast(() => {
    const t = toast.currentToast();
    if (t && t.id !== last) { last = t.id; shown.push({ text: t.text, sub: t.sub, info: t.info }); }
  });
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => { root.render(<App />); });
  act(() => ws().onopen?.());
  await settle();
  await settle();
}

const q = (sel: string) => document.querySelector<HTMLElement>(sel);
const button = (text: string, scope: ParentNode = document) =>
  [...scope.querySelectorAll<HTMLButtonElement>("button")].find((b) => b.textContent === text);
const click = (b: HTMLElement | null | undefined) => {
  if (!b) throw new Error("no such button");
  act(() => b.click());
};
const findBtn = () => q(".q-find")!;
const pastGuard = () => act(async () => { await new Promise((r) => setTimeout(r, GUARD_MS + 20)); });
const joinPanel = () => q(".tp-join-code");

/** The toast on screen: its words (sub-line included) and whether it is an
 *  info notice or an error. */
function toastNow() {
  const t = q(".toast");
  return t ? { text: t.textContent, info: t.classList.contains("toast-info") } : null;
}

/** Searching alone: Play tapped, the queue holds you. */
async function queuedAlone() {
  await renderApp();
  await pastGuard();
  click(findBtn());
  const since = nowSecs();
  say({ type: "queue_state", queued: true, count: 3, since, front: false, party_id: null,
        leader: true, bots_at: since + 60 });
}

/** At a waiting table with Ann. */
async function atSharedTable() {
  await queuedAlone();
  const since = nowSecs();
  const person = (name: string, you = false) => ({
    name, you, ready: false, reconnecting: false, since: since - 30, sit: `sit-${name}`, pair: false, leader: true });
  say({ type: "queue_state", queued: true, count: 3, since, front: false, party_id: null, leader: true,
        bots_at: since + 60,
        table: { id: "t1", you: 0, seats: [person("Jerry", true), person("Ann"), null, null], timer: null,
                 ready: 0, of: 2, you_ready: false, waiting_for: ["Ann"] } });
}

/** A room code's Join panel, Join tapped: the panel is `joining`. */
async function joining() {
  window.history.replaceState(null, "", "/?code=wxyz");
  await renderApp();
  say({ type: "room_seats", room: "WXYZ", in_game: true, seats: [0, 1, 2, 3].map((seat) => ({
    seat, name: seat ? `Bot ${seat}` : "Mei", is_bot: seat > 0, connected: true, team: seat % 2,
    claimable: seat > 0, controller: seat ? "bot" : "human", reserved_secs: null })) });
  await settle();
  click(button("Join", joinPanel()!));
  expect(lastSent()).toMatchObject({ type: "table_join", code: "WXYZ", expect: "room" });
}

/** Opening the app with a saved room: the silent resume is in flight. */
async function resuming() {
  localStorage.setItem("shengji.name", "Me");
  localStorage.setItem("shengji.room", "ABCD");
  await renderApp();
  expect(sent()[0]).toMatchObject({ type: "table_join", code: "ABCD" });
}

const err = (code: string | undefined, message: string, extra: Record<string, unknown> = {}) =>
  ({ type: "error", ...(code ? { code } : {}), message, ...extra });

describe("error routes, as a player sees them", () => {
  it("a peek's refusal: the Join's own toast, in the server's words", async () => {
    window.history.replaceState(null, "", "/?code=zzzz");
    await renderApp();
    say(err("room_not_found", "No table has that code.", { peek: "ZZZZ" }));
    expect(toastNow()).toEqual({ text: "No table has that code.", info: false });
    expect(joinPanel()).toBeNull();
  });

  it("account_in_game: Play's place says it, no toast", async () => {
    await renderApp();
    await pastGuard();
    click(findBtn());
    say(err("account_in_game", "You are already in a game on another device."));
    expect(q(".play-in-game-line")?.textContent).toBe("You are already in a game on another device.");
    expect(toastNow()).toBeNull();
  });

  it.each(["not_in_party", "panel_changed"])("%s: silent", async (code) => {
    await atSharedTable();
    say(err(code, "server words"));
    expect(toastNow()).toBeNull();
    expect(document.body.textContent).not.toContain("server words");
  });

  it.each([
    ["pair_seats_fixed", "A Duo's seats stay together."],
    ["already_ready", "You tapped Start, so your seat is set."],
    ["seat_taken", "That seat was just taken.Pick another."],
    ["table_closed", "That table is no longer open."],
    ["no_offer", "That table is no longer open."],
    ["bad_seat", "Pick one of the open seats."],
  ])("%s: the queue's notice, in its own words", async (code, words) => {
    await atSharedTable();
    say(err(code, "server words"));
    expect(toastNow()).toEqual({ text: words, info: true });
  });

  it.each(["seat_taken", "table_closed", "no_offer", "bad_seat", "pair_seats_fixed", "already_ready"])(
    "%s is said once: the queue's words, with no toast of the server's before them", async (code) => {
      await atSharedTable();
      say(err(code, "server words"));
      expect(shown).toHaveLength(1);
      expect(shown[0].info).toBe(true);
      expect(shown[0].text).not.toBe("server words");
    });

  it("table_full while joining: the Join panel says Table is full, no toast", async () => {
    await joining();
    say(err("table_full", "That table is full."));
    expect(toastNow()).toBeNull();
    expect(joinPanel()?.querySelector(".tp-line")?.textContent).toBe("Table is full");
  });

  it("start_failed: back to Play, the server's words", async () => {
    await queuedAlone();
    say(err("start_failed", "The game could not start."));
    expect(toastNow()).toEqual({ text: "The game could not start.", info: false });
    expect(findBtn().textContent).toBe("Play");
  });

  it("room_not_found after a Join: That game has ended, the Join panel goes", async () => {
    await joining();
    say(err("room_not_found", "Room not found"));
    expect(toastNow()).toEqual({ text: "That game has ended.", info: false });
    expect(joinPanel()).toBeNull();
  });

  it("room_not_found answering a silent resume: no toast, the saved room forgotten", async () => {
    await resuming();
    say(err("room_not_found", "Room not found"));
    expect(toastNow()).toBeNull();
    expect(localStorage.getItem("shengji.room")).toBeNull();
    expect(q(".lobby-panel")).not.toBeNull();
  });

  it("ranked_queue_only answering a resume: Play, the saved room kept, sign in again", async () => {
    await resuming();
    say(err("ranked_queue_only", "Ranked games are joined through the queue."));
    expect(toastNow()).toEqual({ text: "Sign in again to return to your game.", info: false });
    expect(localStorage.getItem("shengji.room")).toBe("ABCD");
  });

  it("ranked_queue_only otherwise: the server's words", async () => {
    await renderApp();
    say(err("ranked_queue_only", "Ranked games are joined through the queue."));
    expect(toastNow()).toEqual({ text: "Ranked games are joined through the queue.", info: false });
  });

  it("cooldown: the server's words, and Play counts down", async () => {
    await renderApp();
    await pastGuard();
    click(findBtn());
    say(err("cooldown", "You left a table you joined. Play again in 4:59.", { cooldown_until: nowSecs() + 299 }));
    expect(toastNow()).toEqual({ text: "You left a table you joined. Play again in 4:59.", info: false });
    expect(findBtn().textContent).toBe("Play in 4:59");
  });

  it.each(["choose_seat", "seat_unavailable"])("%s while joining: the server's words, and the Join looks again",
    async (code) => {
      await joining();
      say(err(code, "That seat was just taken — pick another."));
      expect(toastNow()).toEqual({ text: "That seat was just taken — pick another.", info: false });
      expect(lastSent()).toEqual({ type: "table_peek", code: "WXYZ" });
    });

  it.each(["table_not_found", "own_table"])("%s while joining: the server's words, the Join panel goes",
    async (code) => {
      await joining();
      say(err(code, "No such table."));
      expect(toastNow()).toEqual({ text: "No such table.", info: false });
      expect(joinPanel()).toBeNull();
    });

  it.each(["room_full", "seat_changed", "retired", "rate_limited", "report_bot", undefined])(
    "%s: a toast in the server's words", async (code) => {
      await atSharedTable();
      say(err(code, "Server words."));
      expect(toastNow()).toEqual({ text: "Server words.", info: false });
    });

  it("a code no row names drops a Play in flight, as any other error does", async () => {
    await renderApp();
    await pastGuard();
    click(findBtn());
    expect(findBtn().getAttribute("aria-busy")).toBe("true");
    say(err("seat_changed", "That seat changed hands. Pick again."));
    expect(findBtn().getAttribute("aria-busy")).toBeNull();
    expect(lastSent()).toMatchObject({ type: "queue_status" });
  });
});
