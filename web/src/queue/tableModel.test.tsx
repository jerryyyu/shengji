// The table panel's DOM and sends, fixture by fixture: every queue state
// the panel tests put on screen, rendered through the whole app on a fixed
// clock. For each state the snapshot holds the panel's markup, then for
// every enabled control a fresh replay that taps it, with the frames it sent
// and how the markup changed.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { WIDE } from "../home/HomeShell";
import { SHORT_VIEWPORT } from "../phoneLayout";
import { GUARD_MS } from "./useKindGuard";
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

/** The fixed instant every fixture is rendered at. */
const T0 = Date.UTC(2026, 10, 15, 12, 0, 0);
const nowSecs = () => Date.now() / 1000;
const allSent = () => FakeWS.all.flatMap((w) => w.sent);
const tell = (msg: unknown) => act(() => { for (const w of FakeWS.all) w.deliver(msg); });
const settle = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });
const flush = () => act(async () => { await Promise.resolve(); await Promise.resolve(); });
const tick = (ms: number) => act(() => { vi.advanceTimersByTime(ms); });

let host: HTMLDivElement | null = null;
let root: ReturnType<typeof createRoot> | null = null;
const realMatchMedia = window.matchMedia;

function viewport(wide: boolean) {
  window.matchMedia = ((q: string) => ({
    matches: q === WIDE ? wide : q === SHORT_VIEWPORT ? false : false,
    media: q, addEventListener() {}, removeEventListener() {},
  })) as unknown as typeof window.matchMedia;
}

function teardown() {
  vi.useRealTimers();
  if (root) act(() => root!.unmount());
  host?.remove();
  root = null;
  host = null;
  window.matchMedia = realMatchMedia;
  window.history.replaceState(null, "", "/");
}
afterEach(teardown);

/** One fixture: frames delivered at T0, then scripted steps, on a phone
 *  unless `wide`; `guest` signs nobody in. */
type Step =
  | { tap: string }                 // a control, by its text or aria-label, in the panel or an open sheet
  | { say: string }                 // typed into the chat sheet's field, then Send
  | { frames: () => unknown[] }     // more frames
  | { wait: number };               // ms on the fake clock
interface Fixture {
  name: string; frames: () => unknown[]; steps?: Step[]; wide?: boolean; guest?: boolean;
  /** The page's address at load, for a link's Join panel. */
  link?: string;
}

async function boot(f: Fixture) {
  teardown();
  FakeWS.all = [];
  localStorage.clear();
  viewport(!!f.wide);
  if (f.link) window.history.replaceState(null, "", f.link);
  (globalThis as unknown as { WebSocket: unknown }).WebSocket = FakeWS;
  (window as unknown as { AudioContext: unknown }).AudioContext = class {
    state = "running";
    resume() { return Promise.resolve(); }
  };
  Object.defineProperty(navigator, "share", { configurable: true, value: undefined });
  Object.defineProperty(Element.prototype, "scrollIntoView", { configurable: true, value: () => {} });
  Object.defineProperty(navigator, "clipboard", { configurable: true,
    value: { writeText: () => Promise.resolve() } });
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if ((url === "/api/me" || url.startsWith("/api/me/")) && f.guest) {
      return { status: 401, json: async () => ({}) } as Response;
    }
    const body = url === "/api/auth/config" ? { google_client_id: "cid" }
      : url === "/api/me" ? { name: "Jerry Yu", email: "j@x", picture: null, display_name: null, name_shown: "Jerry" }
      : null;
    return { status: body ? 200 : 404, json: async () => body ?? {} } as Response;
  }) as typeof fetch;
  vi.resetModules();
  if (f.guest) (await import("../ws")).saveName("Cheerful Tractor");
  const { default: App } = await import("../App");
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => { root!.render(<App />); });
  act(() => { for (const w of FakeWS.all) w.onopen?.(); });
  await settle();
  await settle();
  vi.useFakeTimers({ toFake: ["Date", "setTimeout", "clearTimeout", "setInterval", "clearInterval"] });
  vi.setSystemTime(T0);
  for (const m of f.frames()) tell(m);
  tick(GUARD_MS + 10);
  for (const s of f.steps ?? []) await step(s);
}

/** The panel and everything it put up: the Play block(s), the announcer
 *  before each, a code's Join panel (in Play's place), open sheets and
 *  dialogs, the chat sheet and the toast. */
function scopes(): Element[] {
  const out: Element[] = [];
  for (const s of document.querySelectorAll(".play-section")) {
    const before = s.previousElementSibling;
    if (before?.matches(".sr-only[role='status']")) out.push(before);
    out.push(s);
  }
  for (const d of document.querySelectorAll(".tp, [role='alertdialog'], dialog, .chat-panel, .toast")) {
    if (!out.some((o) => o.contains(d))) out.push(d);
  }
  return out;
}

/** React's generated ids, renumbered by first appearance; nothing else changes. */
function normalize(html: string): string {
  const seen = new Map<string, string>();
  return html.replace(/«[^»]+»|:r[0-9a-z]+:|_r_[0-9a-z]+_/g, (id) => {
    if (!seen.has(id)) seen.set(id, `«id${seen.size}»`);
    return seen.get(id)!;
  });
}
/** The markup, one tag per line. */
const dom = () => normalize(scopes().map((e) => e.outerHTML).join("\n")).replace(/></g, ">\n<").split("\n");

/** What a tap changed: the lines from `at` that went (`cut` of them) and
 *  the lines in their place; null for no change. */
function change(before: string[], after: string[]) {
  let at = 0;
  while (at < before.length && at < after.length && before[at] === after[at]) at++;
  let end = 0;
  while (end < before.length - at && end < after.length - at
         && before[before.length - 1 - end] === after[after.length - 1 - end]) end++;
  if (at === before.length && at === after.length) return null;
  return { at, cut: before.length - at - end, put: after.slice(at, after.length - end) };
}

function controls(): (HTMLButtonElement | HTMLSelectElement)[] {
  return scopes().flatMap((s) => [...s.querySelectorAll<HTMLButtonElement | HTMLSelectElement>("button, select")])
    .filter((c) => !c.disabled);
}
const nameOf = (c: Element) =>
  `${c.tagName.toLowerCase()} "${c.getAttribute("aria-label") ?? c.textContent ?? ""}"`;

async function press(c: HTMLButtonElement | HTMLSelectElement) {
  if (c instanceof HTMLSelectElement) {
    const other = [...c.options].find((o) => o.value !== c.value)!;
    act(() => {
      c.value = other.value;
      c.dispatchEvent(new Event("change", { bubbles: true }));
    });
  } else {
    act(() => c.click());
  }
  await flush();
}

async function step(s: Step) {
  if ("tap" in s) {
    const c = scopes().flatMap((e) => [...e.querySelectorAll<HTMLButtonElement>("button")])
      .find((b) => b.getAttribute("aria-label")?.split(",")[0] === s.tap || b.getAttribute("aria-label") === s.tap
                   || b.textContent === s.tap);
    if (!c) throw new Error(`no control ${s.tap}`);
    await press(c);
  } else if ("say" in s) {
    const sheet = document.querySelector(".q-sheet.chat-sheet")!;
    const input = sheet.querySelector<HTMLInputElement>("input")!;
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
    act(() => { setter.call(input, s.say); input.dispatchEvent(new Event("input", { bubbles: true })); });
    const send = [...sheet.querySelectorAll<HTMLButtonElement>("button")].find((b) => b.textContent === "Send")!;
    await press(send);
  } else if ("frames" in s) {
    for (const m of s.frames()) tell(m);
    await flush();
  } else {
    tick(s.wait);
  }
}

/** The fixture's markup, then one replay per enabled control. */
async function trace(f: Fixture) {
  await boot(f);
  const base = { dom: dom(), sentBySteps: allSent().slice(0) };
  const n = controls().length;
  const taps: { control: string; sent: unknown[]; change: ReturnType<typeof change> }[] = [];
  for (let i = 0; i < n; i++) {
    await boot(f);
    const c = controls()[i];
    const name = nameOf(c);
    const from = allSent().length;
    await press(c);
    taps.push({ control: name, sent: allSent().slice(from), change: change(base.dom, dom()) });
  }
  return { ...base, taps };
}

function queued(over: Record<string, unknown> = {}) {
  const since = nowSecs();
  return { type: "queue_state", queued: true, count: 3, since, front: false, party_id: null,
           leader: true, bots_at: since + 60, ...over };
}
const coded = (over: Record<string, unknown> = {}) =>
  queued({ mode: "ranked", code: "4N5Z", allow_joiners: true, start_level: "2", opener: true, ...over });
type Seat = { name: string; you?: boolean; ready?: boolean; reconnecting?: boolean; since?: number;
              sit?: string; pair?: boolean; leader?: boolean } | null;
const seat = (name: string, over: Partial<NonNullable<Seat>> = {}): Seat => ({
  name, you: false, ready: false, reconnecting: false, since: nowSecs() - 30, sit: `sit-${name}`, pair: false,
  leader: true, ...over,
});
function atTable(seats: Seat[], table: Record<string, unknown> = {}, over: Record<string, unknown> = {}) {
  const you = (table.you as number | undefined) ?? 0;
  const taken = seats.filter((s) => s !== null) as NonNullable<Seat>[];
  return coded({
    count: taken.length,
    ...over,
    table: {
      id: "t1", code: "4N5Z", opener: 0, you, seats, timer: null,
      ready: taken.filter((s) => s.ready).length, of: taken.length,
      you_ready: !!seats[you]?.ready,
      waiting_for: taken.filter((s) => !s.ready && !s.you).map((s) => s.name),
      ...table,
    },
  });
}
const JERRY = { name: "Jerry", leader: true, you: true };
const ALICE = { name: "Alice", leader: false, you: false };
const duoParty = (youLead: boolean) => ({
  type: "party", party_id: "d1", code: "4N5Z", table: true, you_lead: youLead, expires_at: nowSecs() + 300,
  members: youLead ? [JERRY, ALICE] : [{ ...JERRY, you: false }, { ...ALICE, you: true }],
});
const duoState = (opener: boolean, ready: number, youReady: boolean, over: Record<string, unknown> = {}) =>
  queued({ party_id: "d1", leader: opener, duo: true, held_seat: null, duo_ready: ready, you_ready: youReady,
           code: "4N5Z", opener, allow_joiners: true, ...over });
const follower = () => ({ type: "party", party_id: "p1", code: "7F2K", you_lead: false, expires_at: nowSecs() + 300,
                          members: [{ name: "Sam", leader: true, you: false }, { name: "Jerry", leader: false, you: true }] });
const offerSeat = (name: string, bot: boolean, open: boolean) => ({ name, bot, open });
const offer = (over: Record<string, unknown> = {}) => ({
  room: "OPEN", pick: 2, expires_at: nowSecs() + 20, round_end: false,
  seats: [offerSeat("Mei", false, false), offerSeat("Bot 1", true, true),
          offerSeat("Bot 2", true, true), offerSeat("Bot 3", true, true)],
  ...over,
});
const tableChat = () => ({ type: "table_chat_history", table: "t1", messages: [
  { id: 1, seat: 1, name: "Alice", text: "hi!", t: nowSecs() }] });
const two = () => [seat("Jerry", { you: true }), seat("Alice"), null, null];
const three = () => [seat("Jerry", { you: true }), seat("Alice"), seat("Li"), null];

/** A room's seat in a peek's answer: a bot, a dropped player (claimable,
 *  a bot covering it) or a person. */
const roomSeat = (seat: number, name: string, o: { bot?: boolean; away?: boolean } = {}) => ({
  seat, name, is_bot: !!o.bot, connected: !o.away, team: seat % 2, claimable: !!o.bot || !!o.away,
  controller: o.bot ? "bot" : o.away ? "bot_cover" : "human", reserved_secs: null,
});
const roomPeek = (seats: ReturnType<typeof roomSeat>[]) => ({ type: "room_seats", room: "WXYZ", in_game: true, seats });
const tablePeek = (seats: [string, string | null, boolean?][], over: Record<string, unknown> = {}) => ({
  type: "room_seats", room: "4N5Z", table: true, mode: "casual", in_game: false, allow_joiners: true,
  full: false, closed: false,
  seats: seats.map(([state, name, ready], seat) => ({ seat, team: seat % 2, state, name, ready: ready ?? false })),
  ...over,
});

const QUEUES: Fixture[] = [
  { name: "own: ranked", frames: () => [coded({ count: 1 })] },
  { name: "own: ranked, wide", wide: true, frames: () => [coded({ count: 1 })] },
  { name: "own: casual, level 4", frames: () => [coded({ count: 1, mode: "casual", start_level: "4" })] },
  { name: "own: waiting for people", frames: () => [coded({ count: 1, wait_players: true, bots_at: null })] },
  { name: "own: bots paused, open tables", frames: () => [coded({ count: 1, bots_paused: true, open_tables: 2 })] },
  { name: "own: no code", frames: () => [queued({ count: 1 })] },
  { name: "own: guest", guest: true, frames: () => [queued({ count: 1 })] },
  { name: "own: bots nearly here", frames: () => [coded({ count: 1, bots_at: nowSecs() + 5 })] },
  { name: "own: chat history", frames: () => [
    { type: "table_chat_history", table: null, messages: [{ id: 1, seat: 0, name: "Jerry", text: "back", t: nowSecs() }] },
    coded({ count: 1 })] },
  { name: "own: chat sent", frames: () => [coded({ count: 1 })], steps: [{ tap: "Chat" }, { say: "anyone?" }] },
  { name: "own: leave sheet", frames: () => [coded({ count: 1 })], steps: [{ tap: "Leave" }] },
  { name: "own: Duo, seat held", frames: () => [coded({ count: 1, duo: true, held_seat: 2 })] },
  { name: "own: Duo, seat held, leave sheet", frames: () => [coded({ count: 1, duo: true, held_seat: 2 })],
    steps: [{ tap: "Leave" }] },
  { name: "own: Duo follower", frames: () => [follower(), queued({ party_id: "p1", leader: false })] },
  { name: "own: Duo friend, none ready", frames: () => [duoParty(false), duoState(false, 0, false)] },
  { name: "own: Duo friend, you ready", frames: () => [duoParty(false), duoState(false, 1, true)] },
  { name: "own: Duo friend, both ready", frames: () => [duoParty(false), duoState(false, 2, true)] },
  { name: "own: Duo opener, partner ready", frames: () => [duoParty(true), duoState(true, 1, false)] },
  { name: "own: Duo opener, leave sheet", frames: () => [duoParty(true), duoState(true, 0, false)],
    steps: [{ tap: "Leave" }] },
  { name: "join: Mei", frames: () => [coded({ offer: offer(), bots_paused: true, bots_at: null, code: null })] },
  { name: "join: Mei, wide", wide: true,
    frames: () => [coded({ offer: offer(), bots_paused: true, bots_at: null, code: null })] },
  { name: "join: an away seat, round end", frames: () => [coded({ offer: offer({ round_end: true, pick: 1,
    seats: [offerSeat("Mei", false, false), offerSeat("Alexandrina", false, true),
            offerSeat("Sam", false, false), offerSeat("Bot 3", true, true)] }), bots_paused: true, bots_at: null })] },
  { name: "join: nearly lapsed", frames: () => [coded({ offer: offer({ expires_at: nowSecs() + 4 }) })] },
  { name: "join: a Duo's offer", frames: () => [queued({ party_id: "p1", leader: false, bots_at: null, bots_paused: true,
    offer: { room: "OPEN", pick: 3, partner: { seat: 1, name: "Lee" }, expires_at: nowSecs() + 10, round_end: false,
             seats: [offerSeat("Mei", false, false), offerSeat("Bot 1", true, true),
                     offerSeat("Sam", false, false), offerSeat("Bot 3", true, true)] } })] },
  { name: "join: guest", guest: true, frames: () => [queued({ offer: offer(), bots_paused: true, bots_at: null })] },
  { name: "shared: two, opener", frames: () => [atTable(two())] },
  { name: "shared: two, opener, wide", wide: true, frames: () => [atTable(two())] },
  { name: "shared: two, non-opener", frames: () => [atTable(two(), {}, { opener: false })] },
  { name: "shared: just joined, timer", frames: () => [atTable(
    [seat("Jerry", { you: true }), seat("Alice", { since: nowSecs() }), null, null],
    { timer: { at: nowSecs() + 42, name: "Jerry", you: true } })] },
  { name: "shared: casual, joiner", frames: () => [atTable(
    [seat("Mei"), null, seat("Jerry", { you: true }), null], { you: 2 },
    { opener: false, mode: "casual", start_level: "7" })] },
  { name: "shared: you ready, waiting for Alice", frames: () => [atTable(
    [seat("Jerry", { you: true, ready: true }), seat("Alice"), null, null])] },
  { name: "shared: Alice reconnecting", frames: () => [atTable(
    [seat("Jerry", { you: true, ready: true }), seat("Alice", { reconnecting: true }), null, null])] },
  { name: "shared: all ready, starting", frames: () => [atTable(
    [seat("Jerry", { you: true, ready: true }), seat("Alice", { ready: true }), null, null])] },
  { name: "shared: three, two waiting", frames: () => [atTable(
    [seat("Jerry", { you: true, ready: true }), seat("Alice"), seat("Li"), null])] },
  { name: "shared: Start now unlocked", frames: () => [atTable(
    [seat("Jerry", { you: true }), seat("Alice"), null, null], { start_now_at: nowSecs() - 1 })] },
  { name: "shared: Start now later", frames: () => [atTable(
    [seat("Jerry", { you: true }), seat("Alice"), null, null], { start_now_at: nowSecs() + 30 })] },
  { name: "shared: Start now, joiner", frames: () => [atTable(
    [seat("Jerry"), seat("Alice", { you: true }), null, null], { you: 1, start_now_at: nowSecs() - 1 },
    { opener: false })] },
  { name: "shared: no timer, waiting for people", frames: () => [atTable(
    [seat("Jerry", { you: true }), seat("Alice")], {}, { bots_at: null, wait_players: true })] },
  { name: "shared: a Duo at the table", frames: () => [atTable(
    [seat("Jerry", { you: true, pair: true }), seat("Li"), seat("Kai", { pair: true }), null], {},
    { party_id: "p1" })] },
  { name: "shared: Duo follower", frames: () => [follower(), atTable(
    [seat("Alice"), seat("Sam", { pair: true }), null, seat("Jerry", { you: true, pair: true, leader: false })],
    { you: 3 }, { party_id: "p1", leader: false })] },
  { name: "shared: held seat", frames: () => [atTable(
    [seat("Jerry"), seat("Mei", { you: true }), null, null], { you: 1, held_seat: 2, held_seats: [2] },
    { opener: false })] },
  { name: "shared: Duo made at a waiting table", frames: () => [duoParty(false), atTable(
    [seat("Mei"), null, seat("Jerry", { pair: true }), seat("Alice", { you: true, pair: true, leader: false })],
    { you: 3 }, { party_id: "d1", leader: false, opener: false })] },
  { name: "shared: still here", frames: () => [atTable(two(), {}, { still_here_until: nowSecs() + 30 })] },
  { name: "shared: chat history", frames: () => [atTable(two()), tableChat()] },
  { name: "shared: chat sent", frames: () => [atTable(two()), tableChat()], steps: [{ tap: "Chat" }, { say: "yes" }] },
  { name: "shared: leave sheet", frames: () => [atTable(three())], steps: [{ tap: "Leave" }] },
  { name: "shared: opener picks Alice", frames: () => [atTable(three())],
    steps: [{ tap: "Alice, other team. Move" }] },
  { name: "shared: opener moves Alice, confirm", frames: () => [atTable(three())],
    steps: [{ tap: "Alice, other team. Move" }, { tap: "Open seat, other team. Move Alice here" }] },
  { name: "shared: opener picks Alice, held seat", frames: () => [atTable(
    [seat("Jerry", { you: true }), seat("Alice"), null, seat("Li")], { held_seats: [2], held_seat: 2 })],
    steps: [{ tap: "Alice, other team. Move" }] },
  { name: "shared: a new sitting drops the pick", frames: () => [atTable(three())],
    steps: [{ tap: "Alice, other team. Move" },
            { frames: () => [atTable([seat("Jerry", { you: true }), seat("Alice", { sit: "sit-Alice-2" }),
                                      seat("Li"), null])] }] },
  { name: "elsewhere: leader", frames: () => [queued({ elsewhere: true, count: 2, table: null, offer: null })] },
  { name: "elsewhere: follower", frames: () => [queued({ elsewhere: true, count: 2, leader: false, table: null, offer: null })] },
  { name: "join code: a room with two bot seats", link: "/?code=WXYZ", frames: () => [roomPeek([
    roomSeat(0, "Mei"), roomSeat(1, "Bot 1", { bot: true }), roomSeat(2, "Sam"), roomSeat(3, "Bot 3", { bot: true })])] },
  { name: "join code: a dropped player's seat", link: "/?code=WXYZ", frames: () => [roomPeek([
    roomSeat(0, "Mei"), roomSeat(1, "Alice", { away: true }), roomSeat(2, "Sam"), roomSeat(3, "Li")])] },
  { name: "join code: a full room", link: "/?code=WXYZ", frames: () => [roomPeek([
    roomSeat(0, "Mei"), roomSeat(1, "Alice"), roomSeat(2, "Sam"), roomSeat(3, "Li")])] },
  { name: "join code: a queued table with a held Partner seat", link: "/?code=4N5Z", frames: () => [tablePeek(
    [["taken", "Mei", true], ["held", null], ["held", null], ["open", null]])] },
  { name: "join code: a ranked queued table", link: "/?code=4N5Z", frames: () => [tablePeek(
    [["taken", "Mei"], ["taken", "Li", true], ["open", null], ["open", null]], { mode: "ranked" })] },
  { name: "join code: a link mid-peek", link: "/?code=4N5Z", frames: () => [] },
];

describe("the table panel, fixture by fixture", () => {
  for (const f of QUEUES) {
    it(f.name, async () => {
      expect(await trace(f)).toMatchSnapshot();
    }, 60_000);
  }
});

describe("the model and its dispatcher", () => {
  it("a table's move needs the sitting token", async () => {
    vi.resetModules();
    const { conn } = await import("../ws");
    const { queueSend } = await import("./tableModel");
    const sent: unknown[] = [];
    const spy = vi.spyOn(conn, "send").mockImplementation((m) => { sent.push(m); return true; });
    queueSend({ type: "move_other", from: 1, to: 3, sit: null });
    expect(sent).toEqual([]);
    spy.mockRestore();
  });
});
