// The matchmaking queue's screens against a mocked socket: Play's Ranked
// block and the Duo sheet, the queue bar, the waiting table, the pair
// flow, the away notice and the matched game's note.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { WIDE } from "../home/HomeShell";
import { SHORT_VIEWPORT } from "../phoneLayout";
import { GUARD_MS } from "./useKindGuard";

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
const sentTypes = () => FakeWS.all.flatMap((w) => w.sent).map((m) => m.type);
const lastSent = () => { const all = FakeWS.all.flatMap((w) => w.sent); return all[all.length - 1]; };
const sentCount = () => FakeWS.all.flatMap((w) => w.sent).length;
const nowSecs = () => Date.now() / 1000;

let signedIn = true;
let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
const realMatchMedia = window.matchMedia;

/** A phone held upright, a wide window, or (`short`) a phone held sideways,
 *  which is wide as well. */
function viewport(wide: boolean, short = false) {
  window.matchMedia = ((q: string) => ({
    matches: q === WIDE ? wide || short : q === SHORT_VIEWPORT ? short : false,
    media: q, addEventListener() {}, removeEventListener() {},
  })) as unknown as typeof window.matchMedia;
}

beforeEach(() => {
  FakeWS.all = [];
  signedIn = true;
  localStorage.clear();
  viewport(false);
  (globalThis as unknown as { WebSocket: unknown }).WebSocket = FakeWS;
  (window as unknown as { AudioContext: unknown }).AudioContext = class {
    state = "running";
    resume() { return Promise.resolve(); }
  };
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if ((url === "/api/me" || url.startsWith("/api/me/")) && !signedIn) {
      return { status: 401, json: async () => ({}) } as Response;
    }
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
const buttons = (scope: ParentNode = document) => [...scope.querySelectorAll<HTMLButtonElement>("button")];
const button = (text: string | RegExp, scope: ParentNode = document) => buttons(scope).find((b) => {
  const t = b.textContent ?? "";
  return typeof text === "string" ? t === text : text.test(t);
});
const click = (b: HTMLElement | null | undefined) => {
  if (!b) throw new Error("no such button");
  act(() => b.click());
};
const findBtn = () => q(".q-find")!;

/** Fake clock from here on; the app is already rendered and settled. */
function fakeClock() {
  vi.useFakeTimers({ toFake: ["Date", "setTimeout", "clearTimeout", "setInterval", "clearInterval"] });
}
const tick = (ms: number) => act(() => { vi.advanceTimersByTime(ms); });

function queued(over: Record<string, unknown> = {}) {
  const since = nowSecs();
  return { type: "queue_state", queued: true, count: 3, since, front: false, party_id: null,
           leader: true, bots_at: since + 60, ...over };
}
type Seat = { name: string; you?: boolean; ready?: boolean; reconnecting?: boolean; since?: number;
              pair?: boolean; leader?: boolean } | null;
const seat = (name: string, over: Partial<NonNullable<Seat>> = {}): Seat => ({
  name, you: false, ready: false, reconnecting: false, since: nowSecs() - 30, pair: false, leader: true, ...over,
});
/** A queue_state at a waiting table (you at seat 0 unless `you` says). */
function atTable(seats: Seat[], table: Record<string, unknown> = {}, over: Record<string, unknown> = {}) {
  const you = (table.you as number | undefined) ?? 0;
  const taken = seats.filter((s) => s !== null) as NonNullable<Seat>[];
  return queued({
    ...over,
    table: {
      id: "t1", you, seats, timer: null,
      ready: taken.filter((s) => s.ready).length, of: taken.length,
      you_ready: !!seats[you]?.ready,
      waiting_for: taken.filter((s) => !s.ready && !s.you).map((s) => s.name),
      ...table,
    },
  });
}

describe("Play", () => {
  const lobby = () => q(".lobby-panel")!;
  it("signed in: Ranked / Casual above a gold Play and Duo; no Find a game, Create room or Play bots", async () => {
    await renderApp();
    const modes = [...lobby().querySelectorAll(".play-mode button")].map((b) => b.textContent);
    expect(modes).toEqual(["Ranked", "Casual"]);
    expect(lobby().querySelector(".play-label")).toBeNull();
    expect(findBtn().textContent).toBe("Play");
    expect(findBtn().className).toContain("gold");
    say({ type: "queue_count", count: 3 });
    expect(findBtn().textContent).toBe("Play");          // no count under the button
    expect(button("Duo", lobby())).toBeDefined();
    expect(button(/Find a game/)).toBeUndefined();
    expect(button(/Create room/, lobby())).toBeUndefined();
    expect(button(/Play bots/, lobby())).toBeUndefined();
    expect(q("input[aria-label='Room or duo code']")).not.toBeNull();
  });

  it("Play joins the ranked queue at once, with no sheet", async () => {
    await renderApp();
    click(findBtn());
    expect(lastSent()).toEqual({ type: "queue_join", mode: "ranked" });
    expect(q(".q-sheet")).toBeNull();
    // waiting for the server's word: Play holds, and nothing else says searching
    expect(findBtn().textContent).toBe("Play");
    expect((findBtn() as HTMLButtonElement).disabled).toBe(true);
    expect(findBtn().getAttribute("aria-busy")).toBe("true");
  });

  it("Duo opens the pair sheet, titled Duo and marked Ranked", async () => {
    await renderApp();
    click(button("Duo", lobby()));
    expect(lastSent()).toEqual({ type: "party_create" });
    expect(q(".q-sheet h2")?.textContent).toBe("Duo");
    expect(q(".q-sheet .ranked-chip")?.textContent).toBe("Ranked");
  });

  it("a guest: both modes, Play and Duo, the guest line, and no Play bots or Create room", async () => {
    signedIn = false;
    await renderApp();
    const modes = [...lobby().querySelectorAll(".play-mode button")].map((b) => b.textContent);
    expect(modes).toEqual(["Ranked", "Casual"]);
    expect(document.body.textContent).not.toContain("Sign in to play ranked");
    expect(q(".play-guest-line")?.textContent).toBe("Playing as a guest · Sign in to be ranked");
    expect(button(/Play bots/, lobby())).toBeUndefined();
    expect(button(/Create room/, lobby())).toBeUndefined();
    // Play queues a guest exactly as it does an account, with the chip's name
    const name = q(".lobby-panel .guest-pill .account-pill-name")!.textContent;
    click(button("Play", lobby())!);
    expect(lastSent()).toEqual({ type: "queue_join", mode: "ranked", name });
    expect(localStorage.getItem("shengji.name")).toBe(name);
    say(queued());
    expect(q(".q-find")).toBeNull();
    expect(panel()).not.toBeNull();
    // at a table a guest is not offered sign-in: it would end the guest's seat
    expect(q(".play-guest-signin")).toBeNull();
  });

  it("a guest's Duo opens the pair sheet and makes a code, as an account's does", async () => {
    signedIn = false;
    await renderApp();
    const name = q(".lobby-panel .guest-pill .account-pill-name")!.textContent;
    click(button("Duo", lobby())!);
    expect(lastSent()).toEqual({ type: "party_create", name });
    expect(q(".q-sheet h2")?.textContent).toBe("Duo");
    expect(q(".q-sheet .google-signin")).toBeNull();
    // the same device cannot be both halves of a pair: the sheet says so
    say({ type: "error", code: "same_device", message: "A pair needs two devices." });
    expect(q(".q-sheet .q-error")?.textContent).toBe("A pair needs two devices.");
  });

  it("an account's queue messages carry no name", async () => {
    await renderApp();
    click(button("Play", lobby())!);
    expect(lastSent()).toEqual({ type: "queue_join", mode: "ranked" });
  });

  it("a guest who signs in mid-search starts over: the search is cleared and Play asked for again", async () => {
    signedIn = false;
    await renderApp();
    click(button("Play", lobby())!);
    say(queued());
    expect(panel()).not.toBeNull();
    const { auth } = await import("../auth");
    act(() => auth.signedIn({ name: "Jerry Yu", email: "j@x", picture: null, display_name: null, name_shown: "Jerry" }));
    await settle();
    expect(panel()).toBeNull();
    expect(findBtn().textContent).toBe("Play");
    expect(q(".q-toast")?.textContent).toContain("Signed in. Press Play to find a table.");
  });

  it("a guest who signs in at a waiting table or in a pair keeps nothing: the new socket's one Play is the only search", async () => {
    signedIn = false;
    await renderApp();
    say({ type: "party", party_id: "p1", code: "7F2K", you_lead: false, expires_at: nowSecs() + 300,
          members: [{ name: "Sam", leader: true, you: false }, { name: "Guesty", leader: false, you: true }] });
    click(button("Play", lobby())!);
    say(atTable([seat("Guesty", { you: true }), seat("Alice"), null, null]));
    expect(panel()?.className).toContain("tp-shared");
    const old = ws();
    const oldSent = old.sent.length;
    fakeClock();
    const { auth } = await import("../auth");
    act(() => auth.signedIn({ name: "Jerry Yu", email: "j@x", picture: null, display_name: null, name_shown: "Jerry" }));
    tick(0);
    const fresh = ws();
    expect(fresh).not.toBe(old);                  // the identity moved to a new socket
    act(() => fresh.onopen?.());
    // what the guest's socket still had in flight belongs to the guest
    act(() => old.deliver(atTable([seat("Guesty", { you: true }), seat("Alice"), null, null])));
    // the server holds nothing for the account: it says only the count
    say({ type: "queue_count", count: 1 });
    tick(10_000);                                 // past the reconnect resync: no "left while away"
    expect(panel()).toBeNull();
    expect(q(".q-party-chip")).toBeNull();
    tick(GUARD_MS + 10);
    expect(findBtn().textContent).toBe("Play");
    expect(document.body.textContent).not.toContain("left the table while away");
    expect(fresh.sent.filter((m) => m.type === "queue_join")).toEqual([]);
    click(findBtn());
    expect(fresh.sent.filter((m) => m.type === "queue_join")).toEqual([{ type: "queue_join", mode: "ranked" }]);
    expect(old.sent.slice(oldSent)).toEqual([]);  // nothing more on the guest's socket
    say(queued());
    expect(panel()).not.toBeNull();
    expect(fresh.sent.filter((m) => m.type === "queue_join")).toHaveLength(1);
  });

  it("a guest's Sign in shows the sign-in buttons in the line's place", async () => {
    signedIn = false;
    await renderApp();
    click(q(".play-guest-signin") as HTMLButtonElement);
    expect(q(".play-guest-line")).toBeNull();
    expect(q(".lobby-panel .google-signin")).not.toBeNull();
    // the website signs in with Google only; nothing promises a provider still to come
    expect(q("[data-testid='apple-signin']")).toBeNull();
    expect(document.body.textContent).not.toMatch(/coming soon/i);
  });
});

it("in the app a guest's Sign in offers Apple beside Google", async () => {
  const { resetNativeForTests } = await import("../native");
  const Plugins: Record<string, unknown> = {
    SocialLogin: { initialize: () => Promise.resolve(), login: () => Promise.resolve(), logout: () => Promise.resolve() },
  };
  (window as unknown as { Capacitor: unknown }).Capacitor = {
    isNativePlatform: () => true, getPlatform: () => "ios", isPluginAvailable: (name: string) => name in Plugins, Plugins,
  };
  resetNativeForTests();
  try {
    signedIn = false;
    await renderApp();
    click(q(".play-guest-signin") as HTMLButtonElement);
    await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
    expect(q("[data-testid='google-signin']")).not.toBeNull();
    expect(q("[data-testid='apple-signin']")?.textContent).toBe("Sign in with Apple");
    expect(document.body.textContent).not.toMatch(/coming soon/i);
  } finally {
    delete (window as unknown as { Capacitor?: unknown }).Capacitor;
    resetNativeForTests();
  }
});

/** Past the panel's primary-button guard, on either clock. */
async function pastGuard() {
  if (vi.isFakeTimers()) tick(GUARD_MS + 10);
  else await act(async () => { await new Promise((r) => setTimeout(r, GUARD_MS + 20)); });
}
const panel = () => q(".play-section .tp");
const lines = (scope: ParentNode | null = panel()) =>
  [...(scope?.querySelectorAll(".tp-line") ?? [])].map((l) => l.textContent);
const primary = () => panel()?.querySelector<HTMLButtonElement>(".tp-primary") ?? null;
const live = () => q(".sr-only[aria-live='polite']");
/** The open leave sheet's title and line. */
const leaveSheetText = () => {
  const d = q("[role='alertdialog']");
  return d ? `${d.querySelector("h2")!.textContent} / ${d.querySelector("p")!.textContent}` : null;
};
/** Taps Leave in the open leave sheet. */
const confirmLeave = () => click(q("[role='alertdialog'] .leave-sheet-leave"));

describe("your own table", () => {
  it("Play turns into your table in Play's place: seats, the bot countdown, Start with bots and Leave table", async () => {
    await renderApp();
    fakeClock();
    say(queued());
    const p = panel()!;
    expect(q(".q-find")).toBeNull();                       // the panel replaces Play and Duo
    expect(button("Duo", q(".lobby-panel")!)).toBeUndefined();
    expect(p.classList.contains("tp-own")).toBe(true);
    expect(p.querySelector(".tp-title")?.textContent).toBe("Waiting for players");
    expect(lines()).toEqual(["Bots in 1:00"]);
    // the app draws the table: you, then three open seats, as two teams
    const [ours, theirs] = [...p.querySelectorAll(".tp-col")];
    expect([...ours.querySelectorAll(".tp-seat")].map((s) => s.getAttribute("aria-label")))
      .toEqual(["Open seat, your team", "You, your team"]);
    expect([...theirs.querySelectorAll(".tp-seat.open")]).toHaveLength(2);
    expect(p.querySelector(".tp-seat.open")?.tagName).toBe("DIV");   // nothing to move to alone
    expect(button("Wait for people", p)?.getAttribute("aria-checked")).toBe("false");
    tick(6000);
    expect(lines()).toEqual(["Bots in 0:54"]);
    expect(p.querySelector(".tp-secondary")?.textContent).toBe("Leave table");
    expect(primary()?.textContent).toBe("Start with bots");
    click(primary());
    expect(lastSent()).toEqual({ type: "queue_start_bots" });
    expect(primary()?.textContent).toBe("Starting…");
    say({ type: "match_started", match_id: null, room: "BOTS", rated: true });
    expect(panel()).toBeNull();
    say(queued());
    tick(GUARD_MS + 10);
    click(button("Leave table", panel()!));
    expect(leaveSheetText()).toBe("Leave the table? / Free.");
    expect(lastSent()).not.toEqual({ type: "queue_leave" });
    confirmLeave();
    expect(lastSent()).toEqual({ type: "queue_leave" });
    say({ type: "queue_state", queued: false, count: 0 });
    expect(panel()).toBeNull();
    expect(findBtn().textContent).toBe("Play");
  });

  it("no word a player reads says queue, searching, host or Leave queue", async () => {
    await renderApp();
    say(queued());
    const text = q(".lobby-panel")!.textContent ?? "";
    expect(text).not.toMatch(/queue|searching|finding|host|bots paused/i);
  });

  it("Wait for people: no timer and no line; off again brings the countdown back", async () => {
    await renderApp();
    fakeClock();
    say(queued());
    const sw = () => button("Wait for people", panel()!)!;
    expect(sw().getAttribute("role")).toBe("switch");
    click(sw());
    expect(lastSent()).toEqual({ type: "queue_wait_players" });
    expect(sw().getAttribute("aria-checked")).toBe("true");
    expect(lines()).toEqual([]);
    say(queued({ bots_at: null, wait_players: true }));
    tick(120_000);
    expect(lines()).toEqual([]);
    click(sw());
    expect(lastSent()).toEqual({ type: "queue_allow_bots" });
    say(queued({ bots_at: nowSecs() + 60, wait_players: false }));
    expect(lines()).toEqual(["Bots in 1:00"]);
  });

  it("a table you skipped that still has a seat is one row away", async () => {
    await renderApp();
    say(queued({ open_tables: 1 }));
    click(button(/^1 table has a seat · View$/, panel()!));
    expect(lastSent()).toEqual({ type: "open_table_show" });
    say(queued({ open_tables: 2 }));
    expect(button(/^2 tables have a seat · View$/, panel()!)).toBeDefined();
  });

  it("a Duo's table: the partner sits across; only the leader has the buttons", async () => {
    await renderApp();
    say({ type: "party", party_id: "p1", code: "7F2K", you_lead: false, expires_at: nowSecs() + 300,
          members: [{ name: "Kai", leader: true, you: false }, { name: "Jerry", leader: false, you: true }] });
    say(queued({ party_id: "p1", leader: false }));
    const p = panel()!;
    expect(p.classList.contains("tp-own")).toBe(true);
    expect(lines()).toEqual(["Bots in 1:00"]);
    expect(p.querySelector(".tp-seat.friend")?.getAttribute("aria-label")).toBe("Kai, your Duo partner");
    expect(p.querySelector(".tp-led")?.textContent).toBe("Kai leads");
    expect(primary()).toBeNull();
    expect(button("Wait for people", p)).toBeUndefined();
  });

  it("on other tabs a phone keeps a one-line strip back to Play: the bots' countdown ring, amber in the last ten seconds", async () => {
    await renderApp();
    fakeClock();
    say(queued());
    expect(q(".q-bar")).toBeNull();                        // on Play the panel is the table
    const { openTab } = await import("../home/route");
    act(() => openTab("leaderboard"));
    const bar = q(".q-bar")!;
    expect(bar.parentElement?.className).toContain("home-narrow");
    expect(bar.querySelector(".q-bar-title")?.textContent).toBe("Your table");
    // the bots' countdown, never the time waited
    const ring = () => q(".q-bar .q-bar-time .timer-ring");
    expect(ring()?.textContent).toBe("60");
    expect(ring()?.getAttribute("style")).toContain("--ring-deg: 360deg");
    tick(49_000);
    expect(ring()?.textContent).toBe("11");
    expect(ring()?.className).not.toContain("low");
    expect(q(".q-bar")?.className).not.toContain("warn");
    tick(1_000);
    expect(ring()?.textContent).toBe("10");
    expect(ring()?.className).toContain("low");
    expect(q(".q-bar")?.className).toContain("warn");
    // notices are lifted over the strip while it shows
    expect(document.documentElement.style.getPropertyValue("--q-bar-clear")).toMatch(/^\d+px$/);
    click(q(".q-bar-go"));
    expect(q(".q-bar")).toBeNull();
    expect(panel()).not.toBeNull();
  });

  it("on a desktop or an iPad the panel is in the Ranked card's place with the mini table, and a pill elsewhere", async () => {
    viewport(true);
    await renderApp();
    say(queued({ since: nowSecs() - 24, bots_at: nowSecs() + 36 }));
    expect(q(".q-bar")).toBeNull();
    expect(q(".q-strip")).toBeNull();
    expect(q(".q-pill")).toBeNull();
    const p = panel()!;
    expect(p.className).toContain("tp-wide");
    expect(p.querySelector(".seat-clock .tp-seat.pos-bottom")?.getAttribute("aria-label")).toBe("You, your team");
    expect(p.querySelectorAll(".seat-clock .tp-seat")).toHaveLength(4);
    expect(p.closest("[aria-modal]")).toBeNull();
    expect(p.closest("[inert]")).toBeNull();
    const { openTab } = await import("../home/route");
    for (const go of [() => openTab("leaderboard"), () => openTab("me", "stats"), () => openTab("me", "games")]) {
      act(go);
      const pill = q(".topbar .topbar-end .q-pill")!;
      // the bots' countdown, 36 s left, not the 24 s waited
      expect(pill.querySelector(".timer-ring")?.textContent).toBe("36");
      // a narrow top bar hides this label and keeps the ring (topBarFitCss.test.ts)
      expect(pill.querySelector(".q-pill-label")?.textContent).toBe("Your table");
      expect(pill.nextElementSibling?.className).toContain("account-pill");
      expect(q(".q-strip")).toBeNull();
    }
    click(q(".q-pill"));
    expect(window.location.hash).toBe("");
    expect(q(".q-pill")).toBeNull();
    expect(panel()).not.toBeNull();
  });

  it("a phone held sideways: the panel on Play, the strip under the top bar elsewhere", async () => {
    viewport(false, true);
    await renderApp();
    say(queued({ since: nowSecs() - 24, bots_at: nowSecs() + 36 }));
    expect(panel()?.className).not.toContain("tp-wide");
    expect(q(".q-strip")).toBeNull();
    const { openTab } = await import("../home/route");
    act(() => openTab("leaderboard"));
    expect(q(".q-strip .q-chip .q-chip-text")?.textContent).toBe("Your table");
    expect(q(".q-strip .q-chip .timer-ring")?.textContent).toBe("36");
    expect(q(".q-pill")).toBeNull();
    expect(q(".q-bar")).toBeNull();
  });
});

describe("the panel's primary button", () => {
  it("waits 700 ms after the panel changes kind, so a second tap on Play never starts with bots", async () => {
    await renderApp();
    fakeClock();
    click(findBtn());
    say(queued());
    expect(primary()?.textContent).toBe("Start with bots");
    expect(primary()?.disabled).toBe(true);
    tick(GUARD_MS - 50);
    expect(primary()?.disabled).toBe(true);
    tick(60);
    expect(primary()?.disabled).toBe(false);
    // a fresh offer: Join is not live under the finger that aimed at Start
    say(queued({ offer: { room: "OPEN", pick: 2, expires_at: nowSecs() + 10, round_end: false,
                          seats: [0, 1, 2, 3].map((i) => ({ name: i === 0 ? "Mei" : `Bot ${i}`, bot: i !== 0, open: i !== 0 })) },
                 bots_paused: true, bots_at: null }));
    expect(primary()?.textContent).toMatch(/Join$/);
    expect(primary()?.disabled).toBe(true);
    tick(GUARD_MS + 10);
    expect(primary()?.disabled).toBe(false);
    // the same kind updating does not re-arm it
    say(queued({ offer: { room: "OPEN", pick: 3, expires_at: nowSecs() + 10, round_end: false,
                          seats: [0, 1, 2, 3].map((i) => ({ name: i === 0 ? "Mei" : `Bot ${i}`, bot: i !== 0, open: i !== 0 })) },
                 bots_paused: true, bots_at: null }));
    expect(primary()?.disabled).toBe(false);
  });

  it("Escape does nothing and Enter is the primary button; the page is never inert", async () => {
    viewport(true);
    await renderApp();
    say(queued());
    await pastGuard();
    const key = (k: string) => act(() => {
      document.dispatchEvent(new KeyboardEvent("keydown", { key: k, bubbles: true, cancelable: true }));
    });
    key("Escape");
    expect(panel()).not.toBeNull();
    expect(sentTypes()).not.toContain("queue_leave");
    expect(sentTypes()).not.toContain("open_table_wait");
    expect(q("[inert]")).toBeNull();
    act(() => (document.activeElement as HTMLElement | null)?.blur());
    key("Enter");
    expect(lastSent()).toEqual({ type: "queue_start_bots" });
  });

  it("one polite announcement per state, none per tick, and one at ten seconds left", async () => {
    await renderApp();
    fakeClock();
    say(queued());
    const region = live()!;
    expect(region.getAttribute("role")).toBe("status");
    expect(region.textContent).toBe("Your table. Waiting for players.");
    tick(5000);
    expect(region.textContent).toBe("Your table. Waiting for players.");
    tick(45_500);
    expect(region.textContent).toBe("Your table. Waiting for players. Bots fill the empty seats in 10 seconds.");
    expect(live()).toBe(region);                           // the same region throughout
    say(atTable([seat("Jerry", { you: true }), seat("Alice"), null, null]));
    expect(live()).toBe(region);
    expect(region.textContent).toBe("Table. You and Alice. 0 of 2 ready.");
    // the clocks themselves are not in any live region
    expect(panel()?.closest("[aria-live]")).toBeNull();
  });
});

const TABLE_STATE = {
  type: "state", room: "ABCD", you: 0, phase: "play", matched: true,
  players: [0, 1, 2, 3].map((seat) => ({
    seat, name: `P${seat}`, is_bot: false, connected: true, team: seat % 2, cards_left: 3, is_banker: seat === 1,
    takeover_in: null, controller: "human", reserved_for: null, reserved_secs: null,
  })),
  hand: [{ id: 1, code: "S5" }], levels: ["2", "2"], games_won: [0, 0], banker: 1,
  trump: { suit: "S", rank: "2", declarer: 1 }, turn: 1, declare_options: [], current_declaration: null,
  passed: [], trick: { leader: 1, plays: [] }, last_trick: null, attacker_points: 0, kitty_count: 8,
  message: null, notice: null, round_result: null,
};

describe("a shared table", () => {
  it("a second person makes it shared: both teams, the timer, the ready count and Start now", async () => {
    await renderApp();
    fakeClock();
    say(queued());
    say(atTable([seat("Jerry", { you: true }), seat("Alice", { since: nowSecs() }), null, null],
                { timer: { at: nowSecs() + 42, name: "Alice", you: false } }));
    const p = panel()!;
    expect(p.classList.contains("tp-shared")).toBe(true);
    expect(p.querySelector(".tp-title")?.textContent).toBe("You and Alice");
    expect(lines()).toEqual(["0 of 2 ready · Bots in 0:42"]);
    const [ours, theirs] = [...p.querySelectorAll(".tp-col")];
    expect([...ours.querySelectorAll(".tp-seat")].map((s) => s.getAttribute("aria-label")))
      .toEqual(["Open seat, your team. Move here", "You"]);
    expect(theirs.querySelector(".tp-seat")?.getAttribute("aria-label")).toBe("Alice, Just joined, other team");
    expect(button("Wait for people", p)).toBeUndefined();  // a personal switch: only alone
    expect(p.querySelector(".tp-hint")).toBeNull();          // the open seat's label says Move here
    tick(6000);
    expect(theirs.querySelector(".tp-seat")?.getAttribute("aria-label")).toBe("Alice, other team");
    expect(lines()).toEqual(["0 of 2 ready · Bots in 0:36"]);
    expect(primary()?.textContent).toBe("Start now");
    click(primary());
    expect(lastSent()).toEqual({ type: "table_start" });
    expect(primary()?.disabled).toBe(true);
    expect(q(".tabbar")).not.toBeNull();
  });

  it("after your Start the button waits for the others by name; a newcomer keeps your tick", async () => {
    await renderApp();
    say(atTable([seat("Jerry", { you: true, ready: true }), seat("Alice"), null, null]));
    expect(button("Waiting for Alice", panel()!)?.disabled).toBe(true);
    expect(panel()!.querySelector(".tp-seat.you")?.getAttribute("aria-label")).toBe("You, ready");
    expect(panel()!.querySelector(".tp-seat.you .tp-tick")).not.toBeNull();
    say(atTable([seat("Jerry", { you: true, ready: true }), seat("Alice", { reconnecting: true }),
                 seat("Bobby Tables The Third", { since: nowSecs() }), null],
                { timer: { at: nowSecs() + 18, name: "Alice", you: false } }));
    expect(button("Waiting for 2 players", panel()!)?.disabled).toBe(true);
    expect(panel()!.querySelector(".tp-title")?.textContent).toBe("You, Alice and Bobby Tabl…");
    expect(lines()[0]).toMatch(/^1 of 3 ready · Bots in 0:1[789]$/);
    const names = [...panel()!.querySelectorAll(".tp-seat")].map((s) => s.getAttribute("aria-label"));
    expect(names).toContain("Alice, Reconnecting, other team");
    expect(names).toContain("Bobby Tables The Third, Just joined, your team");
  });

  it("with every switch on there is no timer; Add bots brings one back", async () => {
    await renderApp();
    say(atTable([seat("Jerry", { you: true }), seat("Alice")], {}, { bots_at: null, wait_players: true }));
    expect(lines()).toEqual(["0 of 2 ready"]);
    click(button("Add bots in 1:00", panel()!));
    expect(lastSent()).toEqual({ type: "queue_allow_bots" });
    say(atTable([seat("Jerry", { you: true }), seat("Alice")], { timer: { at: nowSecs() + 30, name: "Jerry", you: true } }));
    expect(lines()[0]).toMatch(/^0 of 2 ready · Bots in 0:(29|30|31)$/);
    expect(button("Add bots in 1:00", panel()!)).toBeUndefined();
  });

  it("Leave table frees your seat and puts you back on Play", async () => {
    await renderApp();
    say(atTable([seat("Jerry", { you: true }), seat("Alice"), null, null]));
    const before = sentCount();
    click(button("Leave table", panel()!));
    expect(leaveSheetText()).toBe("Leave the table? / Free. Alice stays at the table.");
    expect(sentCount()).toBe(before);
    confirmLeave();
    expect(lastSent()).toEqual({ type: "queue_leave" });
    expect(leaveSheetText()).toBeNull();
    say({ type: "queue_state", queued: false, count: 1 });
    expect(panel()).toBeNull();
    await pastGuard();
    expect((findBtn() as HTMLButtonElement).disabled).toBe(false);
  });

  it("the table starting goes straight to the game: no match-found sheet", async () => {
    await renderApp();
    say(atTable([seat("Jerry", { you: true, ready: true }), seat("Alice", { ready: true }), null, null]));
    say({ type: "match_started", match_id: "t1", room: "ABCD", rated: true });
    expect(panel()).toBeNull();
    expect(document.body.textContent).not.toContain("match found");
    say({ type: "resume", token: "t1", gen: 1 });
    say(TABLE_STATE);
    expect(q(".table-screen")).not.toBeNull();
  });

  it("the last other person leaving: Alice left the table, and you are at your own table again", async () => {
    await renderApp();
    say(atTable([seat("Jerry", { you: true }), seat("Alice"), null, null]));
    say(queued({ table: null }));
    expect(panel()?.classList.contains("tp-own")).toBe(true);
    expect(q(".q-toast")?.textContent).toContain("Alice left the table.");
  });

  it("two minutes without a tap: one notice, back on Play, no cooldown", async () => {
    await renderApp();
    say(atTable([seat("Jerry", { you: true }), seat("Alice"), null, null]));
    say({ type: "queue_removed", reason: "idle", cooldown_until: null });
    expect(panel()).toBeNull();
    expect(q(".q-toast")?.textContent).toContain("You left the table.");
    await pastGuard();
    expect((findBtn() as HTMLButtonElement).disabled).toBe(false);
  });

  it("a Duo's other member sees the table but the leader starts and leaves", async () => {
    await renderApp();
    say({ type: "party", party_id: "p1", code: "7F2K", you_lead: false, expires_at: nowSecs() + 300,
          members: [{ name: "Sam", leader: true, you: false }, { name: "Jerry", leader: false, you: true }] });
    say(atTable([seat("Alice"), seat("Sam", { pair: true }), null, seat("Jerry", { you: true, pair: true, leader: false })],
                { you: 3 }, { party_id: "p1", leader: false }));
    const p = panel()!;
    expect(p.querySelector(".tp-title")?.textContent).toBe("You, Alice and Sam");
    const [ours] = [...p.querySelectorAll(".tp-col")];
    expect([...ours.querySelectorAll(".tp-seat")].map((s) => s.getAttribute("aria-label")))
      .toEqual(["Sam, your Duo partner, your team", "You"]);
    expect(primary()).toBeNull();
    expect(button("Leave table", p)).toBeUndefined();
    expect(p.querySelector(".tp-led")?.textContent).toBe("Sam leads");
  });

  it("server_error after the room's frames: back to the lobby, at your table again", async () => {
    await renderApp();
    say(atTable([seat("Jerry", { you: true, ready: true }), seat("Mei", { ready: true }), null, null]));
    say({ type: "match_started", match_id: "t1", room: "ABCD", rated: true });
    say({ type: "resume", token: "t1", gen: 1 });
    say({ type: "room", room: "ABCD", you: 0, host: 0, start_level: "2", matched: true,
          players: [0, 1, 2, 3].map((seat) => ({ seat, name: `P${seat}`, is_bot: false, connected: true })) });
    say(TABLE_STATE);
    expect(q(".table-screen")).not.toBeNull();
    expect(localStorage.getItem("shengji.room")).toBe("ABCD");
    say({ type: "match_cancelled", match_id: "t1", reason: "server_error" });
    say(queued({ front: true }));
    expect(q(".table-screen")).toBeNull();
    expect(panel()?.classList.contains("tp-own")).toBe(true);
    expect(localStorage.getItem("shengji.room")).toBeNull();   // nothing to resume
    expect(q(".q-toast")?.textContent).toContain("The game could not start.");
  });

  it("a bots game that fails to start returns to the lobby, away from the table", async () => {
    await renderApp();
    say(queued());
    await pastGuard();
    click(button("Start with bots", panel()!));
    say({ type: "match_started", match_id: null, room: "BOTS", rated: true });
    say({ ...TABLE_STATE, room: "BOTS" });
    say({ type: "error", code: "start_failed", message: "Could not start the game." });
    expect(q(".table-screen")).toBeNull();
    expect(panel()).toBeNull();
    await pastGuard();
    expect((findBtn() as HTMLButtonElement).disabled).toBe(false);
  });

  it("on a desktop or an iPad the shared table is the same inline panel with the mini table", async () => {
    viewport(true);
    await renderApp();
    say(atTable([seat("Jerry", { you: true }), seat("Alice"), null, null],
                { timer: { at: nowSecs() + 42, name: "Alice", you: false } }));
    const p = panel()!;
    expect(p.getAttribute("role")).toBeNull();
    expect(p.querySelector(".seat-clock .tp-seat.pos-bottom")?.getAttribute("aria-label")).toBe("You");
    expect(p.querySelector(".seat-clock .tp-seat.pos-left")?.getAttribute("aria-label")).toBe("Alice, other team");
    expect(p.querySelector(".seat-clock .tp-seat.pos-top")?.getAttribute("aria-label")).toBe("Open seat, your team. Move here");
    expect(p.querySelector(".seat-clock .tp-seat.pos-top")?.tagName).toBe("BUTTON");
    expect(q(".home-body")?.className).not.toContain("wt-behind");
    expect(q("[inert]")).toBeNull();
    expect(lines()).toEqual(["0 of 2 ready · Bots in 0:42"]);
  });
});

describe("with a friend", () => {
  const party = (members: { name: string; leader: boolean; you: boolean }[], youLead = true) => ({
    type: "party", party_id: "p1", code: "7F2K", you_lead: youLead, members, expires_at: nowSecs() + 300,
  });
  const ME = { name: "Jerry", leader: true, you: true };
  const SAM = { name: "Sam", leader: false, you: false };

  it("creates a code, shows it, forms the pair chip and queues as a pair", async () => {
    await renderApp();
    click(button("Duo"));
    expect(lastSent()).toEqual({ type: "party_create" });
    expect(q(".q-sheet h2")?.textContent).toBe("Duo");
    say(party([ME]));
    expect(q(".q-codebox b")?.textContent).toBe("7F2K");
    expect(button("Invite partner")).toBeDefined();
    expect(button("Copy code")).toBeDefined();
    click(button("Cancel", q(".q-sheet")!));
    expect(q(".q-party-chip")?.textContent).toContain("7F2K");
    say(party([ME, SAM]));
    expect(q(".q-toast")?.textContent).toContain("Sam joined your Duo.");
    const chip = q(".q-party-chip")!;
    expect(chip.textContent).toContain("You + Sam");
    expect(chip.textContent).toContain("you lead");
    expect(findBtn().textContent).toBe("Play");
    click(findBtn());          // no sheet: straight into the queue
    expect(q(".q-sheet")).toBeNull();
    expect(lastSent()).toEqual({ type: "queue_join", party_id: "p1", mode: "ranked" });
    fakeClock();
    say(queued({ party_id: "p1" }));
    tick(12_000);
    expect(panel()?.classList.contains("tp-own")).toBe(true);
    expect(panel()?.querySelector(".tp-seat.friend")?.getAttribute("aria-label")).toBe("Sam, your Duo partner");
    expect(lines()).toEqual(["Bots in 0:48"]);
    expect(primary()?.textContent).toBe("Start with bots");
  });

  it("joins a friend's pair by code from Duo; the member cannot start or cancel", async () => {
    await renderApp();
    const { openTab } = await import("../home/route");
    click(button("Duo", q(".lobby-panel")!));
    expect(lastSent()).toEqual({ type: "party_create" });
    const input = q("#q-join-code") as HTMLInputElement;
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
    act(() => { setter.call(input, "ab12"); input.dispatchEvent(new Event("input", { bubbles: true })); });
    click(button("Join", q(".q-join")!));
    expect(lastSent()).toEqual({ type: "code_lookup", code: "AB12" });
    say({ type: "code_kind", code: "AB12", kind: "party" });
    expect(lastSent()).toEqual({ type: "party_join", code: "AB12" });
    say(party([{ name: "Sam", leader: true, you: false }, { name: "Jerry", leader: false, you: true }], false));
    expect(q(".q-sheet")).toBeNull();
    expect(q(".q-toast")?.textContent).toContain("You joined Sam's Duo.");
    act(() => openTab("play"));
    expect(findBtn().textContent).toBe("Play");
    expect((findBtn() as HTMLButtonElement).disabled).toBe(true);
    say(queued({ party_id: "p1", leader: false }));
    expect(button("Leave table", panel()!)).toBeUndefined();
    expect(panel()?.querySelector(".tp-led")?.textContent).toBe("Sam leads");
    expect(button("Start with bots", panel()!)).toBeUndefined();
    expect(button("Wait for people")).toBeUndefined();
    say(queued({ party_id: "p1", leader: false, bots_at: null, wait_players: true }));
    expect(lines()).toEqual([]);
    expect(button("Wait for people")).toBeUndefined();
  });

  it("an invite link opens the pair sheet with its code", async () => {
    window.history.replaceState(null, "", "/?party=7F2K");
    await renderApp();
    await settle();
    expect(q(".q-sheet h2")?.textContent).toBe("Duo");
    expect((q("#q-join-code") as HTMLInputElement).value).toBe("7F2K");
    expect(window.location.search).toBe("");
    expect(sentTypes()).not.toContain("party_create");
  });
});

describe("a pair the server forgot", () => {
  const PAIR = { type: "party", party_id: "p9", code: "FG3K", you_lead: true,
                 members: [{ name: "Jerry", leader: true, you: true }], expires_at: 0 };

  it("Leave answered not_in_party drops the chip without an error", async () => {
    await renderApp();
    say({ ...PAIR, expires_at: nowSecs() + 300 });
    expect(q(".q-party-chip")).not.toBeNull();
    say({ type: "error", code: "not_in_party", message: "You are not in a party." });
    expect(q(".q-party-chip")).toBeNull();
    expect(q(".lobby-error")).toBeNull();
  });

  it("a reconnect that gets no pair back drops the chip", async () => {
    await renderApp();
    say({ ...PAIR, expires_at: nowSecs() + 300 });
    fakeClock();
    act(() => ws().close());
    tick(600);
    act(() => ws().onopen?.());
    expect(q(".q-party-chip")).not.toBeNull();      // the server may still hand it back
    tick(3000);
    expect(q(".q-party-chip")).toBeNull();
  });

  it("a reconnect that gets the pair back keeps it", async () => {
    await renderApp();
    say({ ...PAIR, expires_at: nowSecs() + 300 });
    fakeClock();
    act(() => ws().close());
    tick(600);
    act(() => ws().onopen?.());
    say({ ...PAIR, expires_at: nowSecs() + 300 });
    tick(3000);
    expect(q(".q-party-chip")).not.toBeNull();
  });
});

describe("away from the app", () => {
  it("a drop while the socket was gone: the notice on return", async () => {
    await renderApp();
    say(queued());
    fakeClock();
    act(() => ws().close());
    tick(600);                 // the reconnect backoff
    act(() => ws().onopen?.());
    expect(panel()).not.toBeNull();      // the server may still hand it back
    tick(3000);
    expect(panel()).toBeNull();
    expect(q(".q-toast")?.textContent).toContain("You left the table while away.");
  });

  it("a socket back in time gets its entry back and no notice", async () => {
    await renderApp();
    say(queued());
    fakeClock();
    act(() => ws().close());
    tick(600);
    act(() => ws().onopen?.());
    say(queued());
    tick(3000);
    expect(panel()).not.toBeNull();
    expect(q(".q-toast")).toBeNull();
  });

  it("the server's away removal says so too", async () => {
    await renderApp();
    say(queued());
    say({ type: "queue_removed", reason: "away", cooldown_until: null });
    expect(q(".q-toast")?.textContent).toContain("You left the table while away.");
    expect(panel()).toBeNull();
    await pastGuard();
    expect((findBtn() as HTMLButtonElement).disabled).toBe(false);   // no cooldown
  });
});

describe("the table", () => {
  const player = (seat: number) => ({
    seat, name: `P${seat}`, is_bot: false, connected: true, team: seat % 2, cards_left: 3, is_banker: seat === 1,
    takeover_in: null, controller: "human", reserved_for: null, reserved_secs: null,
  });
  const state = (matched: boolean) => ({
    type: "state", room: "ABCD", you: 0, phase: "play", ...(matched ? { matched: true } : {}),
    players: [0, 1, 2, 3].map(player), hand: [{ id: 1, code: "S5" }], levels: ["2", "2"], games_won: [0, 0],
    banker: 1, trump: { suit: "S", rank: "2", declarer: 1 }, turn: 1, declare_options: [],
    current_declaration: null, passed: [], trick: { leader: 1, plays: [] }, last_trick: null,
    attacker_points: 0, kitty_count: 8, message: null, notice: null, round_result: null,
  });

  it("a matched room shows a Ranked chip in the top bar; an invite room does not", async () => {
    await renderApp();
    say({ type: "match_started", match_id: "m1", room: "ABCD", rated: true });
    say(state(true));
    const chip = q(".table-screen .hud-bar .mode-chip");
    expect(chip?.textContent).toBe("Ranked");
    expect(chip?.classList.contains("ranked")).toBe(true);
    say(state(false));
    expect(q(".mode-chip")).toBeNull();
  });
});

describe("one code for rooms and pairs", () => {
  const typeInto = (input: HTMLInputElement, value: string) => {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
    act(() => { setter.call(input, value); input.dispatchEvent(new Event("input", { bubbles: true })); });
  };
  const playBox = () => q("input[aria-label='Room or duo code']") as HTMLInputElement;
  const playJoin = () => click(button(/^Join$/, q(".join-row")!));
  const pairParty = (code: string) => ({
    type: "party", party_id: "p9", code, you_lead: false, expires_at: nowSecs() + 300,
    members: [{ name: "Sam", leader: true, you: false }, { name: "Jerry", leader: false, you: true }],
  });
  const seats = (room: string) => ({
    type: "room_seats", room, in_game: false,
    seats: [{ seat: 0, name: "Host", is_bot: false, connected: true, team: 0, claimable: false,
              controller: "human", reserved_secs: null }],
  });
  let clipboard: string[];
  beforeEach(() => {
    clipboard = [];
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: (t: string) => { clipboard.push(t); return Promise.resolve(); } },
    });
  });

  it("the Play box joins a room code through the room flow", async () => {
    await renderApp();
    typeInto(playBox(), "wxyz");
    playJoin();
    expect(lastSent()).toEqual({ type: "code_lookup", code: "WXYZ" });
    say({ type: "code_kind", code: "WXYZ", kind: "room" });
    expect(lastSent()).toEqual({ type: "peek_room", room: "WXYZ" });
    say(seats("WXYZ"));
    expect(lastSent()).toMatchObject({ type: "join_room", room: "WXYZ", name: "Jerry" });
  });

  it("the Play box joins a pair code: the pair chip and the toast", async () => {
    await renderApp();
    typeInto(playBox(), "7F2K");
    playJoin();
    say({ type: "code_kind", code: "7F2K", kind: "party" });
    expect(lastSent()).toEqual({ type: "party_join", code: "7F2K" });
    expect(sentTypes()).not.toContain("peek_room");
    say(pairParty("7F2K"));
    expect(q(".q-party-chip")?.textContent).toContain("You + Sam");
    expect(q(".q-toast")?.textContent).toContain("You joined Sam's Duo.");
    expect(button(/^Join$/, q(".join-row")!)?.disabled).toBe(false);
  });

  it("a code that names nothing says so in the Play box and the pair sheet", async () => {
    await renderApp();
    typeInto(playBox(), "ZZZZ");
    playJoin();
    say({ type: "code_kind", code: "ZZZZ", kind: "none" });
    expect(q(".join-error")?.textContent).toBe("No game or pair has that code.");
    expect(sentTypes()).not.toContain("peek_room");
    expect(sentTypes()).not.toContain("party_join");
    click(button("Duo"));
    typeInto(q("#q-join-code") as HTMLInputElement, "ZZZZ");
    click(button("Join", q(".q-join")!));
    say({ type: "code_kind", code: "ZZZZ", kind: "none" });
    expect(q(".q-sheet .q-error")?.textContent).toBe("No game or pair has that code.");
  });

  it("a guest who types a pair code joins the pair, as an account does", async () => {
    signedIn = false;
    await renderApp();
    typeInto(playBox(), "7F2K");
    playJoin();
    expect(lastSent()).toEqual({ type: "code_lookup", code: "7F2K" });
    say({ type: "code_kind", code: "7F2K", kind: "party" });
    expect(lastSent()).toMatchObject({ type: "party_join", code: "7F2K" });
    expect(typeof (lastSent() as { name?: unknown }).name).toBe("string");
    expect(document.body.textContent).not.toContain("Sign in to join duo");
  });

  it("the pair sheet's box joins with a code, and a game code closes it and opens the room", async () => {
    await renderApp();
    const { openTab } = await import("../home/route");
    click(button("Duo", q(".lobby-panel")!));
    act(() => openTab("me"));
    await settle();
    expect(q(".q-join-label")?.textContent).toBe("Join with a code");
    typeInto(q("#q-join-code") as HTMLInputElement, "wxyz");
    click(button("Join", q(".q-join")!));
    expect(lastSent()).toEqual({ type: "code_lookup", code: "WXYZ" });
    say({ type: "code_kind", code: "WXYZ", kind: "room" });
    await settle();
    expect(q(".q-sheet")).toBeNull();
    expect(window.location.hash).toBe("");
    expect(lastSent()).toEqual({ type: "peek_room", room: "WXYZ" });
    say(seats("WXYZ"));
    expect(lastSent()).toMatchObject({ type: "join_room", room: "WXYZ" });
  });

  it("a ?code= link for a room goes into the room", async () => {
    window.history.replaceState(null, "", "/?code=wxyz");
    await renderApp();
    expect(lastSent()).toEqual({ type: "code_lookup", code: "WXYZ" });
    say({ type: "code_kind", code: "WXYZ", kind: "room" });
    await settle();
    expect(lastSent()).toEqual({ type: "peek_room", room: "WXYZ" });
    say(seats("WXYZ"));
    expect(lastSent()).toMatchObject({ type: "join_room", room: "WXYZ" });
  });

  it("a ?code= link for a room with a name joins it, as ?room= does", async () => {
    signedIn = false;
    window.history.replaceState(null, "", "/?code=WXYZ&name=Ann");
    await renderApp();
    say({ type: "code_kind", code: "WXYZ", kind: "room" });
    await settle();
    expect(lastSent()).toEqual({ type: "join_room", room: "WXYZ", name: "Ann" });
  });

  it("a ?code= link for a pair opens the pair sheet with its code", async () => {
    window.history.replaceState(null, "", "/?code=7F2K");
    await renderApp();
    expect(lastSent()).toEqual({ type: "code_lookup", code: "7F2K" });
    say({ type: "code_kind", code: "7F2K", kind: "party" });
    await settle();
    expect(q(".q-sheet h2")?.textContent).toBe("Duo");
    expect((q("#q-join-code") as HTMLInputElement).value).toBe("7F2K");
    expect(window.location.search).toBe("");
    expect(sentTypes()).not.toContain("party_join");
  });

  it("a ?code= link that names nothing says so", async () => {
    window.history.replaceState(null, "", "/?code=ZZZZ");
    await renderApp();
    say({ type: "code_kind", code: "ZZZZ", kind: "none" });
    await settle();
    expect(q(".join-error")?.textContent).toBe("No game or pair has that code.");
    expect(window.location.search).toBe("");
  });

  it("an old ?room= link still prefills Join without a lookup", async () => {
    window.history.replaceState(null, "", "/?room=WXYZ");
    await renderApp();
    expect(playBox().value).toBe("WXYZ");
    expect(sentTypes()).not.toContain("code_lookup");
  });

  it("share links are ?code= links, for a pair and for a room", async () => {
    Object.defineProperty(navigator, "share", { configurable: true, value: undefined });
    await renderApp();
    click(button("Duo"));
    say({ type: "party", party_id: "p1", code: "7F2K", you_lead: true, expires_at: nowSecs() + 300,
          members: [{ name: "Jerry", leader: true, you: true }] });
    click(button("Invite partner"));
    await settle();
    expect(clipboard).toEqual([`${window.location.origin}/?code=7F2K`]);
    click(button("Cancel", q(".q-sheet")!));
    say({ type: "room", room: "WXYZ", you: 0, host: 0, start_level: "2",
          players: [{ seat: 0, name: "Jerry", is_bot: false, connected: true }] });
    click(button("Invite link", q(".tp-room")!));
    await settle();
    expect(clipboard.at(-1)).toBe(`${window.location.origin}/?code=WXYZ`);
  });
});

describe("a code lookup that is interrupted or refused", () => {
  const typeInto = (input: HTMLInputElement, value: string) => {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
    act(() => { setter.call(input, value); input.dispatchEvent(new Event("input", { bubbles: true })); });
  };
  const lookups = () => FakeWS.all.flatMap((w) => w.sent).filter((m) => m.type === "code_lookup");
  const LIMITED = { type: "error", code: "rate_limited", lookup: "FG3K", message: "Too many requests; wait a minute." };
  const reconnect = () => {
    fakeClock();
    act(() => ws().close());
    tick(600);                 // the reconnect backoff
    act(() => ws().onopen?.());
    vi.useRealTimers();
  };

  it("a ?code= link whose lookup died with the socket is asked once more, then joins", async () => {
    signedIn = false;
    window.history.replaceState(null, "", "/?code=WXYZ&name=Ann");
    await renderApp();
    expect(lookups()).toHaveLength(1);
    reconnect();
    await settle();
    expect(lookups()).toHaveLength(2);
    expect(ws().sent).toEqual([{ type: "code_lookup", code: "WXYZ" }]);
    say({ type: "code_kind", code: "WXYZ", kind: "room" });
    await settle();
    expect(lastSent()).toEqual({ type: "join_room", room: "WXYZ", name: "Ann" });
  });

  it("a ?code= link already answered and joined is not looked up or joined again on reconnect", async () => {
    signedIn = false;
    window.history.replaceState(null, "", "/?code=WXYZ&name=Ann");
    await renderApp();
    say({ type: "code_kind", code: "WXYZ", kind: "room" });
    await settle();
    const joins = () => FakeWS.all.flatMap((w) => w.sent).filter((m) => m.type === "join_room");
    expect(joins()).toHaveLength(1);
    reconnect();
    await settle();
    expect(lookups()).toHaveLength(1);
    expect(joins()).toHaveLength(1);
  });

  it("a rate-limited Play lookup says so under the Play box", async () => {
    await renderApp();
    typeInto(q("input[aria-label='Room or duo code']") as HTMLInputElement, "WXYZ");
    click(button(/^Join$/, q(".join-row")!));
    say(LIMITED);
    expect(q(".lobby-error")?.textContent).toBe("Too many requests; wait a minute.");
    expect(button(/^Join$/, q(".join-row")!)?.disabled).toBe(false);
  });

  it("a rate-limited ?code= lookup says so under the Play box", async () => {
    window.history.replaceState(null, "", "/?code=WXYZ");
    await renderApp();
    say(LIMITED);
    await settle();
    expect(q(".lobby-error")?.textContent).toBe("Too many requests; wait a minute.");
  });

  it("a rate-limited pair-sheet lookup says so in the sheet", async () => {
    await renderApp();
    click(button("Duo"));
    typeInto(q("#q-join-code") as HTMLInputElement, "WXYZ");
    click(button("Join", q(".q-join")!));
    say(LIMITED);
    expect(q(".q-sheet .q-error")?.textContent).toBe("Too many requests; wait a minute.");
  });

  it("an unrelated error while a lookup waits does not cancel it", async () => {
    await renderApp();
    typeInto(q("input[aria-label='Room or duo code']") as HTMLInputElement, "WXYZ");
    click(button(/^Join$/, q(".join-row")!));
    say({ type: "error", code: "room_full", message: "Room is full." });
    say({ type: "code_kind", code: "WXYZ", kind: "room" });
    expect(lastSent()).toEqual({ type: "peek_room", room: "WXYZ" });
  });
});

describe("a pair-sheet lookup the player walks away from", () => {
  const typeInto = (input: HTMLInputElement, value: string) => {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
    act(() => { setter.call(input, value); input.dispatchEvent(new Event("input", { bubbles: true })); });
  };
  const openPairSheet = () => {
    click(button("Duo"));
  };
  const pairJoinButton = () => q(".q-join button[type='submit']") as HTMLButtonElement;
  const askInSheet = (code: string) => {
    typeInto(q("#q-join-code") as HTMLInputElement, code);
    click(pairJoinButton());
    expect(lastSent()).toEqual({ type: "code_lookup", code });
  };
  const LIMITED = { type: "error", code: "rate_limited", lookup: "FG3K", message: "Too many requests; wait a minute." };

  it("Cancel, then a late pair answer: no party_join and nothing shown", async () => {
    await renderApp();
    openPairSheet();
    askInSheet("FG3K");
    click(button("Cancel", q(".q-sheet")!));
    expect(q(".q-sheet")).toBeNull();
    say({ type: "code_kind", code: "FG3K", kind: "party" });
    expect(sentTypes()).not.toContain("party_join");
    expect(q(".q-sheet")).toBeNull();
    expect(q(".q-error")).toBeNull();
  });

  it("a tap on the scrim, then a late room answer: no Play tab, no peek, no join", async () => {
    await renderApp();
    const { openTab } = await import("../home/route");
    openPairSheet();
    act(() => openTab("me"));
    await settle();
    askInSheet("WXYZ");
    click(q(".q-scrim"));
    expect(q(".q-sheet")).toBeNull();
    say({ type: "code_kind", code: "WXYZ", kind: "room" });
    await settle();
    expect(window.location.hash).toBe("#/me");
    expect(sentTypes()).not.toContain("peek_room");
    expect(sentTypes()).not.toContain("join_room");
  });

  it("Escape, then a late answer of either kind: nothing happens", async () => {
    await renderApp();
    openPairSheet();
    askInSheet("FG3K");
    act(() => { document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" })); });
    expect(q(".q-sheet")).toBeNull();
    say({ type: "code_kind", code: "FG3K", kind: "party" });
    await settle();
    expect(sentTypes()).not.toContain("party_join");
    expect(sentTypes()).not.toContain("peek_room");
  });

  it("a new lookup after a cancel is answered and joins", async () => {
    await renderApp();
    openPairSheet();
    askInSheet("FG3K");
    click(button("Cancel", q(".q-sheet")!));
    openPairSheet();
    askInSheet("AB12");
    say({ type: "code_kind", code: "FG3K", kind: "party" });    // the cancelled one's answer
    expect(sentTypes()).not.toContain("party_join");
    say({ type: "code_kind", code: "AB12", kind: "party" });
    expect(lastSent()).toEqual({ type: "party_join", code: "AB12" });
    expect(FakeWS.all.flatMap((w) => w.sent).filter((m) => m.type === "party_join")).toHaveLength(1);
  });

  it("the pair sheet's Join says Joining… and holds while the lookup waits; a refusal frees it", async () => {
    await renderApp();
    openPairSheet();
    askInSheet("WXYZ");
    expect(pairJoinButton().textContent).toBe("Joining…");
    expect(pairJoinButton().disabled).toBe(true);
    expect(pairJoinButton().getAttribute("aria-busy")).toBe("true");
    say(LIMITED);
    expect(pairJoinButton().textContent).toBe("Join");
    expect(pairJoinButton().disabled).toBe(false);
  });

  it("the pair sheet's Join is freed when the socket drops", async () => {
    await renderApp();
    openPairSheet();
    askInSheet("WXYZ");
    act(() => ws().close());
    expect(pairJoinButton().textContent).toBe("Join");
    expect(pairJoinButton().disabled).toBe(false);
  });

  it("the Play box's Join holds while its lookup waits, past an unrelated error, and a drop frees it", async () => {
    await renderApp();
    typeInto(q("input[aria-label='Room or duo code']") as HTMLInputElement, "WXYZ");
    const playJoin = () => q(".join-row button") as HTMLButtonElement;
    click(playJoin());
    expect(playJoin().textContent).toBe("Joining…");
    expect(playJoin().disabled).toBe(true);
    say({ type: "error", code: "room_full", message: "Room is full." });
    expect(playJoin().textContent).toBe("Joining…");
    expect(playJoin().disabled).toBe(true);
    say(LIMITED);
    expect(playJoin().disabled).toBe(false);
    click(playJoin());
    act(() => ws().close());
    expect(playJoin().textContent).toBe("Join");
  });
});

describe("open tables", () => {
  const offerSeat = (name: string, bot: boolean, open: boolean) => ({ name, bot, open });
  const offer = (over: Record<string, unknown> = {}) => ({
    room: "OPEN", pick: 2, expires_at: nowSecs() + 10, round_end: false,
    seats: [offerSeat("Jerry", false, false), offerSeat("Bot 1", true, true),
            offerSeat("Bot 2", true, true), offerSeat("Bot 3", true, true)],
    ...over,
  });
  const player = (seat: number, over: Record<string, unknown> = {}) => ({
    seat, name: seat === 0 ? "Jerry" : `Bot ${seat}`, is_bot: seat !== 0, connected: true, team: seat % 2,
    cards_left: 3, is_banker: seat === 1, takeover_in: null, controller: seat === 0 ? "human" : "bot",
    reserved_for: null, reserved_secs: null, ...over,
  });
  const state = (over: Record<string, unknown> = {}) => ({
    type: "state", room: "OPEN", you: 0, phase: "play", matched: true, allow_joiners: true, joining: [],
    players: [0, 1, 2, 3].map((s) => player(s)), hand: [{ id: 1, code: "S5" }], levels: ["2", "2"],
    games_won: [0, 0], banker: 1, trump: { suit: "S", rank: "2", declarer: 1 }, turn: 1, declare_options: [],
    current_declaration: null, passed: [], trick: { leader: 1, plays: [] }, last_trick: null,
    attacker_points: 0, kitty_count: 8, message: null, notice: null, round_result: null, ...over,
  });
  // An earlier test's app may reopen a socket while this one renders, so
  // frames go to every socket opened during this test (the stale app is
  // unmounted) and sends are read from all of them.
  const open = async () => {
    await renderApp();
    act(() => { for (const w of FakeWS.all) if (w !== ws()) w.onopen?.(); });
    await settle();
  };
  const tell = (msg: unknown) => act(() => { for (const w of FakeWS.all) w.deliver(msg); });
  const sentLast = () => lastSent();

  const seatLabels = (col: number) =>
    [...(panel()?.querySelectorAll(".tp-col")[col]?.querySelectorAll(".tp-seat") ?? [])].map((s) => s.getAttribute("aria-label"));

  it("O1: Join Mei: both teams, your partner seat picked, no lines; the offer's ring on Join from its first second", async () => {
    await open();
    fakeClock();
    tell(queued({ offer: offer({ expires_at: nowSecs() + 20,
                                 seats: [offerSeat("Mei", false, false), offerSeat("Bot 1", true, true),
                                         offerSeat("Bot 2", true, true), offerSeat("Bot 3", true, true)] }),
                  bots_paused: true, bots_at: null }));
    const p = panel()!;
    expect(p.classList.contains("tp-join")).toBe(true);
    expect(p.querySelector(".tp-title")?.textContent).toBe("Join Mei");
    // the leave cost is said only in the Leave sheet; Join carries no lines
    expect(lines()).toEqual([]);
    expect(p.textContent).not.toMatch(/minute|Round in progress|Ranked/);
    expect(seatLabels(0)).toEqual(["Mei, playing, your team", "You, your team"]);
    expect(p.querySelector(".tp-seat-sub")).toBeNull();
    // the open seats keep their spoken label though the visible hint is gone
    expect(seatLabels(1)).toEqual(["Open seat, other team. Sit here", "Open seat, other team. Sit here"]);
    expect(p.querySelector(".tp-hint")).toBeNull();
    expect(p.textContent).not.toMatch(/Tap a green seat/);
    const ring = () => primary()?.querySelector(".timer-ring");
    expect(ring()?.textContent).toBe("20");
    expect(ring()?.getAttribute("style")).toContain("--ring-deg: 360deg");
    tick(GUARD_MS + 10);
    expect(primary()?.textContent).toBe(`${ring()?.textContent}Join`);
    expect(ring()?.className).not.toContain("low");
    tick(9300);                          // 10 s left
    expect(ring()?.textContent).toBe("10");
    expect(ring()?.className).toContain("low");
    expect(ring()?.getAttribute("style")).toContain("--ring-deg: 180deg");
    tick(3000);
    expect(ring()?.textContent).toBe("7");
    // tap a green seat on the other team: you move there
    click(p.querySelectorAll<HTMLElement>(".tp-col")[1].querySelector<HTMLElement>("button.tp-seat"));
    expect(seatLabels(0)).toEqual(["Open seat, your team. Sit here", "You, your team"]);
    expect(seatLabels(1)).toEqual(["Mei, playing, other team", "Open seat, other team. Sit here"]);
    click(primary());
    expect(lastSent()).toEqual({ type: "open_table_join", room: "OPEN", seat: 3 });
    expect(button("Joining…")?.disabled).toBe(true);
    expect(button("Keep looking")?.disabled).toBe(true);
  });

  it("Join has no lines at a round end, mid-round, signed in or as a guest", async () => {
    await open();
    tell(queued({ offer: offer({ round_end: true }), bots_paused: true, bots_at: null }));
    expect(lines()).toEqual([]);
    signedIn = false;
    tell(queued({ offer: offer(), bots_paused: true, bots_at: null }));
    expect(lines()).toEqual([]);
    expect(panel()?.textContent).not.toMatch(/minute/);
  });

  it("the title names the people staying, cut to ten characters; an away seat is open, not named", async () => {
    await open();
    tell(queued({ offer: offer({ pick: 1, seats: [offerSeat("Mei", false, false), offerSeat("Bot 1", true, true),
                                                  offerSeat("Samantha-Rose", false, false), offerSeat("Li", false, true)] }),
                  bots_paused: true, bots_at: null }));
    expect(panel()?.querySelector(".tp-title")?.textContent).toBe("Join Mei & Samantha-R…");
    const away = [...panel()!.querySelectorAll(".tp-seat")].find((s) => s.textContent?.includes("away"));
    expect(away?.getAttribute("aria-label")).toBe("Open seat, your team, Li is away. Sit here");
    tell(queued({ offer: offer({ seats: [offerSeat("Mei", false, false), offerSeat("Sam", false, false),
                                         offerSeat("Bot 2", true, true), offerSeat("Li", false, false)] }),
                  bots_paused: true, bots_at: null }));
    expect(panel()?.querySelector(".tp-title")?.textContent).toBe("Join Mei, Sam & Li");
  });

  it("a seat taken first: the offer re-renders with it taken and keeps your other pick", async () => {
    await open();
    tell(queued({ offer: offer(), bots_paused: true, bots_at: null }));
    await pastGuard();
    click(primary());
    tell({ type: "error", code: "seat_taken", message: "That seat was just taken. Pick another." });
    const taken = offer({ pick: 1, seats: [offerSeat("Jerry", false, false), offerSeat("Bot 1", true, true),
                                            offerSeat("Bob", false, false), offerSeat("Bot 3", true, true)] });
    tell(queued({ offer: taken, bots_paused: true, bots_at: null }));
    expect(q(".q-toast")?.textContent).toContain("That seat was just taken.");
    expect([...panel()!.querySelectorAll(".tp-seat")].map((s) => s.getAttribute("aria-label")))
      .toContain("Bob, playing, other team");
    expect(panel()!.querySelector(".tp-seat.you")).not.toBeNull();
    expect(primary()?.disabled).toBe(false);
  });

  it("O6: Keep looking; your table comes back with the row that shows the offer again", async () => {
    await open();
    tell(queued({ offer: offer(), bots_paused: true, bots_at: null }));
    expect(panel()?.textContent).not.toMatch(/Bots paused/);
    click(button("Keep looking"));
    expect(sentLast()).toEqual({ type: "open_table_wait" });
    tell(queued({ offer: null, open_tables: 1, bots_paused: false, bots_at: nowSecs() + 35 }));
    expect(panel()?.classList.contains("tp-own")).toBe(true);
    expect(lines()[0]).toMatch(/^Bots in 0:3[56]$/);
    click(button(/^1 table has a seat · View$/));
    expect(sentLast()).toEqual({ type: "open_table_show" });
    tell(queued({ offer: offer(), open_tables: 0, bots_paused: true, bots_at: null }));
    expect(panel()?.classList.contains("tp-join")).toBe(true);
    expect(button(/table has a seat/)).toBeUndefined();
  });

  it("on another tab the strip says a table has a seat and opens Play", async () => {
    await open();
    tell(queued({ offer: offer(), bots_paused: true, bots_at: null }));
    const { openTab } = await import("../home/route");
    act(() => openTab("leaderboard"));
    expect(q(".q-bar")?.textContent).toBe("Table with a seatJoin");
    click(q(".q-bar-go"));
    expect(panel()?.classList.contains("tp-join")).toBe(true);
  });

  it("on a desktop the offer's seats sit around the mini table; a green seat is a button", async () => {
    viewport(true);
    await open();
    tell(queued({ offer: offer(), bots_paused: true, bots_at: null }));
    const p = panel()!;
    expect(p.querySelector(".seat-clock .tp-seat.pos-bottom")?.getAttribute("aria-label")).toBe("You, your team");
    expect(p.querySelector(".seat-clock .tp-seat.pos-top")?.getAttribute("aria-label")).toBe("Jerry, playing, your team");
    const left = p.querySelector<HTMLButtonElement>(".seat-clock button.tp-seat.pos-left")!;
    expect(left.getAttribute("aria-label")).toBe("Open seat, other team. Sit here");
    click(left);
    expect(p.querySelector(".seat-clock .tp-seat.pos-bottom")?.getAttribute("aria-label")).toBe("You, your team");
    expect(q("[aria-modal]")).toBeNull();
  });

  it("O2b: the newcomer watches its seat with Joining after this trick and a Leave", async () => {
    await open();
    tell(queued({ offer: offer(), bots_paused: true, bots_at: null }));
    await pastGuard();
    click(primary());
    tell({ type: "match_started", match_id: null, room: "OPEN", rated: true, joining: true, seat: 2 });
    expect(panel()).toBeNull();
    tell(state({ you: 2, joining_you: true, turn: 2, joining: [{ seat: 2, name: "Jerry Yu", when: "trick" }] }));
    expect(q(".join-pill")?.textContent).toContain("Joining after this trick");
    expect(q(".join-pill")?.textContent).toContain("A bot plays your seat until then");
    expect(q(".join-notice")).toBeNull();
    expect(button(/^Play/)).toBeUndefined();
    click(button("Leave", q(".join-pill")!));
    expect(leaveSheetText()).toBe("Leave the game? / You'll wait 1 minute to play again.");
    expect(sentLast()).not.toEqual({ type: "leave_room" });
    confirmLeave();
    expect(sentLast()).toEqual({ type: "leave_room" });
  });

  it("O2: the table sees one corner line, next trick then next round", async () => {
    await open();
    tell({ type: "match_started", match_id: "m1", room: "OPEN", rated: true });
    tell(state({ joining: [{ seat: 2, name: "Alice", when: "trick" }] }));
    expect(q(".join-notice")?.textContent).toBe("Alice joins next trick");
    tell(state({ joining: [{ seat: 2, name: "Alice", when: "round" }] }));
    expect(q(".join-notice")?.textContent).toBe("Alice joins next round");
    tell(state({ joining: [] }));
    expect(q(".join-notice")).toBeNull();
  });

  it("the game menu's Allow joiners switch, at ranked tables only", async () => {
    await open();
    tell({ type: "match_started", match_id: "m1", room: "OPEN", rated: true });
    tell(state());
    click(q(".hud-more-btn"));
    const allow = [...document.querySelectorAll<HTMLElement>(".hud-menu-row")]
      .find((r) => r.textContent?.startsWith("Allow joiners"));
    expect(allow?.getAttribute("aria-checked")).toBe("true");
    click(allow);
    expect(sentLast()).toEqual({ type: "allow_joiners", on: false });
    tell(state({ allow_joiners: false }));
    const off = [...document.querySelectorAll<HTMLElement>(".hud-menu-row")]
      .find((r) => r.textContent?.startsWith("Allow joiners"));
    expect(off?.getAttribute("aria-checked")).toBe("false");
  });
});

describe("a ranked table's invite and a pair's open-table offer", () => {
  const typeInto = (input: HTMLInputElement, value: string) => {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
    act(() => { setter.call(input, value); input.dispatchEvent(new Event("input", { bubbles: true })); });
  };
  const open = async () => {
    await renderApp();
    act(() => { for (const w of FakeWS.all) if (w !== ws()) w.onopen?.(); });
    await settle();
  };
  const tell = (msg: unknown) => act(() => { for (const w of FakeWS.all) w.deliver(msg); });
  const seatRow = (seat: number, name: string, isBot: boolean, claimable: boolean) => ({
    seat, name, is_bot: isBot, connected: true, team: seat % 2, claimable,
    controller: isBot ? "bot" : "human", reserved_secs: null,
  });
  const rankedSeats = (full = false) => ({
    type: "room_seats", room: "RANK", in_game: true, ranked: true, full,
    seats: [seatRow(0, "Host", false, false), seatRow(1, "Bot 1", true, !full),
            seatRow(2, "Bot 2", true, !full), seatRow(3, "Bot 3", true, !full)],
  });
  const viaPlayBox = () => {
    typeInto(q("input[aria-label='Room or duo code']") as HTMLInputElement, "rank");
    click(button(/^Join$/, q(".join-row")!));
    tell({ type: "code_kind", code: "RANK", kind: "room" });
    expect(lastSent()).toEqual({ type: "peek_room", room: "RANK" });
  };

  it("signed in: no seat picker, the server seats you at a bot's seat", async () => {
    await open();
    viaPlayBox();
    tell(rankedSeats());
    expect(document.body.textContent).not.toContain("Take a seat");
    expect(lastSent()).toMatchObject({ type: "join_room", room: "RANK" });
    expect(lastSent()).not.toHaveProperty("seat");
  });

  it("a guest takes a ranked table's seat as an account does", async () => {
    signedIn = false;
    await open();
    viaPlayBox();
    tell(rankedSeats());
    expect(q(".ranked-gate")).toBeNull();
    expect(lastSent()).toMatchObject({ type: "join_room", room: "RANK" });
  });

  it("same_device shows the server's message", async () => {
    await open();
    viaPlayBox();
    tell(rankedSeats());
    tell({ type: "error", code: "same_device", message: "Someone on this device is already at that table." });
    expect(document.body.textContent).toContain("Someone on this device is already at that table.");
  });

  it("a ranked table with no bot seat says Table is full", async () => {
    await open();
    viaPlayBox();
    tell(rankedSeats(true));
    expect(q(".ranked-gate h2")?.textContent).toBe("Table is full");
    expect(sentTypes()).not.toContain("join_room");
  });

  it("a ranked table's menu has both Copy invite link and Allow joiners", async () => {
    await open();
    tell({ type: "match_started", match_id: "m1", room: "RANK", rated: true });
    tell({
      type: "state", room: "RANK", you: 0, phase: "play", matched: true, allow_joiners: false, joining: [],
      players: [0, 1, 2, 3].map((s) => ({
        seat: s, name: `P${s}`, is_bot: s !== 0, connected: true, team: s % 2, cards_left: 3, is_banker: s === 1,
        takeover_in: null, controller: s === 0 ? "human" : "bot", reserved_for: null, reserved_secs: null })),
      hand: [{ id: 1, code: "S5" }], levels: ["2", "2"], games_won: [0, 0], banker: 1,
      trump: { suit: "S", rank: "2", declarer: 1 }, turn: 1, declare_options: [], current_declaration: null,
      passed: [], trick: { leader: 1, plays: [] }, last_trick: null, attacker_points: 0, kitty_count: 8,
      message: null, notice: null, round_result: null,
    });
    click(q(".hud-more-btn"));
    const rows = [...document.querySelectorAll<HTMLElement>(".hud-menu-row")].map((r) => r.textContent);
    expect(rows).toContain("Copy invite link");
    expect(rows).toContain("Allow joinersoff");
  });

  it("a created ranked table's menu has Allow joiners too", async () => {
    await open();
    tell({
      type: "state", room: "RANK", you: 0, phase: "play", ranked: true, allow_joiners: true, joining: [],
      players: [0, 1, 2, 3].map((s) => ({
        seat: s, name: `P${s}`, is_bot: s !== 0, connected: true, team: s % 2, cards_left: 3, is_banker: s === 1,
        takeover_in: null, controller: s === 0 ? "human" : "bot", reserved_for: null, reserved_secs: null })),
      hand: [{ id: 1, code: "S5" }], levels: ["2", "2"], games_won: [0, 0], banker: 1,
      trump: { suit: "S", rank: "2", declarer: 1 }, turn: 1, declare_options: [], current_declaration: null,
      passed: [], trick: { leader: 1, plays: [] }, last_trick: null, attacker_points: 0, kitty_count: 8,
      message: null, notice: null, round_result: null,
    });
    click(q(".hud-more-btn"));
    const rows = [...document.querySelectorAll<HTMLElement>(".hud-menu-row")].map((r) => r.textContent);
    expect(rows).toContain("Allow joinerson");
  });

  it("a Duo's offer: Join together, both partner seats fixed, no lines", async () => {
    await open();
    tell({ type: "queue_state", queued: true, count: 2, since: nowSecs(), front: false, party_id: "p1",
           leader: false, bots_at: null, bots_paused: true, open_tables: 0, table: null,
           offer: { room: "OPEN", pick: 3, partner: { seat: 1, name: "Lee" }, expires_at: nowSecs() + 10,
                    round_end: false,
                    seats: [{ name: "Mei", bot: false, open: false }, { name: "Bot 1", bot: true, open: true },
                            { name: "Sam", bot: false, open: false }, { name: "Bot 3", bot: true, open: true }] } });
    const p = q(".play-section .tp")!;
    expect(p.querySelector(".tp-title")?.textContent).toBe("Join Mei & Sam");
    expect(p.querySelectorAll(".tp-line")).toHaveLength(0);
    expect([...p.querySelectorAll(".tp-seat.friend, .tp-seat.you")].map((s) => s.getAttribute("aria-label")))
      .toEqual(["Lee, your Duo partner", "You, your team"]);
    expect(p.querySelectorAll("button.tp-seat").length).toBe(0);
    expect(p.querySelector(".tp-hint")).toBeNull();
    // either member may join; the leader's buttons rule does not apply to Join
    await act(async () => { await new Promise((r) => setTimeout(r, 720)); });
    const join = p.querySelector<HTMLButtonElement>(".tp-primary")!;
    expect(join.textContent).toMatch(/^(9|10)Join together$/);
    expect(join.querySelector(".timer-ring")?.textContent).toMatch(/^(9|10)$/);
    click(join);
    expect(lastSent()).toEqual({ type: "open_table_join", room: "OPEN", seat: 3 });
  });
});

describe("the search on screen is the server's", () => {
  const sentOf = (type: string) => FakeWS.all.flatMap((w) => w.sent).filter((m) => m.type === type);

  for (const who of ["signed in", "a guest"] as const) {
    it(`${who}: a Play the server never confirms reverts with a notice and asks what it holds`, async () => {
      signedIn = who === "signed in";
      await renderApp();
      fakeClock();
      click(findBtn());
      expect(findBtn().getAttribute("aria-busy")).toBe("true");
      tick(3000);
      expect(findBtn().getAttribute("aria-busy")).toBeNull();
      expect((findBtn() as HTMLButtonElement).disabled).toBe(false);
      expect(q(".q-toast")?.textContent).toContain("Couldn't open a table.");
      expect(lastSent()).toMatchObject({ type: "queue_status" });
      say(queued());                       // it did reach the server after all
      expect(panel()).not.toBeNull();
    });
  }

  it("a confirmed Play does not revert", async () => {
    await renderApp();
    fakeClock();
    click(findBtn());
    say(queued());
    tick(3000);
    expect(panel()).not.toBeNull();
    expect(q(".q-toast")).toBeNull();
  });

  for (const error of [{ code: "same_device", message: "Someone on this device is already at that table." },
                       { message: "Invalid request." }]) {
    it(`an error reply (${error.code ?? "no code"}) clears an unconfirmed Play`, async () => {
      await renderApp();
      click(findBtn());
      say({ type: "error", ...error });
      expect(findBtn().textContent).toBe("Play");
      expect(lastSent()).toEqual({ type: "queue_status" });
    });
  }

  it("a reconnect asks the server and a search it dropped is cleared with a notice", async () => {
    await renderApp();
    say(queued());
    fakeClock();
    act(() => ws().close());
    tick(600);
    act(() => ws().onopen?.());
    expect(ws().sent).toContainEqual({ type: "queue_status" });
    say({ type: "queue_state", queued: false, count: 0 });
    expect(panel()).toBeNull();
    expect(findBtn().textContent).toBe("Play");
    expect(q(".q-toast")?.textContent).toContain("You're no longer at a table.");
    expect(q(".q-toast")?.textContent).toContain("Press Play to find one.");
  });

  it.each([true, false])("an elsewhere-held table can be reclaimed with leader=%s", async (leader) => {
    await renderApp();
    say({ type: "queue_state", queued: true, elsewhere: true, count: 2, since: nowSecs(), leader,
          table: null, offer: null });
    expect(panel()?.querySelector(".tp-title")?.textContent).toBe("Your table is open on another device.");
    expect(q(".q-find")).toBeNull();
    await pastGuard();
    expect(Boolean(button("Leave table", panel()!))).toBe(leader);
    click(button("Move it here", panel()!));
    expect(lastSent()).toEqual({ type: "queue_join", mode: "ranked" });
    say({ type: "queue_state", queued: false, count: 1 });
    expect(panel()).toBeNull();
    expect(q(".q-toast")).toBeNull();
  });

  it("back in view, a socket suspended without a close is probed and replaced, and the search rechecked", async () => {
    await renderApp();
    say({ type: "heartbeat_ready" });
    say(queued());
    fakeClock();
    const suspended = ws();
    Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "visible" });
    act(() => { document.dispatchEvent(new Event("visibilitychange")); });
    expect(suspended.sent[suspended.sent.length - 1]).toMatchObject({ type: "ping" });
    tick(5000);                          // no pong: the socket is dead
    expect(suspended.readyState).toBe(3);
    tick(10);
    expect(ws()).not.toBe(suspended);
    act(() => ws().onopen?.());
    expect(ws().sent).toContainEqual({ type: "queue_status" });
  });

  it("while a search is on screen the client checks it with the server", async () => {
    await renderApp();
    fakeClock();
    say(queued());
    const before = sentOf("queue_status").length;
    tick(15_000);
    expect(sentOf("queue_status").length).toBe(before + 1);
    say({ type: "queue_state", queued: false, count: 0 });
    expect(panel()).toBeNull();
    tick(30_000);
    expect(sentOf("queue_status").length).toBe(before + 1);   // nothing to check any more
  });
});

describe("flow fixes: cooldown, joined seat, other device, Duo, guests", () => {
  const typeInto = (input: HTMLInputElement, value: string) => {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
    act(() => { setter.call(input, value); input.dispatchEvent(new Event("input", { bubbles: true })); });
  };
  const player = (seat: number) => ({
    seat, name: seat === 2 ? "Jerry" : `Bot ${seat}`, is_bot: seat !== 2, connected: true, team: seat % 2,
    cards_left: 3, is_banker: seat === 1, takeover_in: null, controller: seat === 2 ? "human" : "bot",
    reserved_for: null, reserved_secs: null,
  });
  const state = (over: Record<string, unknown> = {}) => ({
    type: "state", room: "OPEN", you: 2, phase: "play", matched: true, allow_joiners: true, joining: [],
    players: [0, 1, 2, 3].map(player), hand: [{ id: 1, code: "S5" }], levels: ["2", "2"],
    games_won: [0, 0], banker: 1, trump: { suit: "S", rank: "2", declarer: 1 }, turn: 1, declare_options: [],
    current_declaration: null, passed: [], trick: { leader: 1, plays: [] }, last_trick: null,
    attacker_points: 0, kitty_count: 8, message: null, notice: null, round_result: null, ...over,
  });
  const leaveAlertText = () => {
    click(q(".table-screen .leave-btn"));
    const d = q("[role='alertdialog']")!;
    const out = `${d.querySelector("h2")!.textContent} / ${d.querySelector("p")!.textContent}`;
    click(d.querySelector<HTMLElement>(".leave-sheet-stay"));
    return out;
  };

  it("a queue cooldown counts down on Play, which stays disabled until it ends", async () => {
    await renderApp();
    fakeClock();
    say({ type: "queue_state", queued: false, count: 0, cooldown_until: nowSecs() + 252 });
    expect(findBtn().textContent).toBe("Play in 4:12");
    expect((findBtn() as HTMLButtonElement).disabled).toBe(true);
    tick(60_000);
    expect(findBtn().textContent).toBe("Play in 3:12");
    tick(192_000);
    expect(findBtn().textContent).toBe("Play");
    expect((findBtn() as HTMLButtonElement).disabled).toBe(false);
  });

  it("a cooldown refusal is told once (the lobby's line), and Play counts it down", async () => {
    await renderApp();
    click(findBtn());
    say({ type: "error", code: "cooldown", message: "You left a table you joined. Play again in 4:59.",
          cooldown_until: nowSecs() + 299 });
    expect(q(".q-toast")).toBeNull();
    expect(document.body.textContent?.match(/You left a table you joined/g)?.length).toBe(1);
    expect(findBtn().textContent).toBe("Play in 4:59");
  });

  it("leaving a round joined from an open table: a 1-minute wait", async () => {
    await renderApp();
    say({ type: "match_started", match_id: null, room: "OPEN", rated: true, joining: true, seat: 2 });
    say(state({ joining_you: true }));
    say(state());
    expect(leaveAlertText()).toBe(
      "Leave the game? / You'll wait 1 minute to play again.");
    // the round over, the next one is an ordinary ranked round
    say(state({ phase: "round_end" }));
    say(state({ phase: "deal" }));
    expect(leaveAlertText()).toBe(
      "Leave the game? / A bot takes your seat. This round counts as at best a draw for you.");
  });

  it("after a reload, state frames alone (no match_started) carry the joined round's warning", async () => {
    // a fresh module load is a reload: the client never saw this seat's match_started
    await renderApp();
    say(state({ joined_round: true }));
    expect(leaveAlertText()).toBe(
      "Leave the game? / You'll wait 1 minute to play again.");
    // the server omits the flag once the round is over; the round end clears it
    say(state({ phase: "round_end" }));
    say(state({ phase: "deal" }));
    expect(leaveAlertText()).toBe(
      "Leave the game? / A bot takes your seat. This round counts as at best a draw for you.");
  });

  it("review: reconnect after the joined round ends clears its warning", async () => {
    await renderApp();
    const first = ws();
    say(state({ joined_round: true }));
    expect(leaveAlertText()).toMatch(/wait 1 minute/);
    act(() => first.close());
    await act(async () => { await new Promise((r) => setTimeout(r, 1600)); });
    expect(ws()).not.toBe(first);
    act(() => ws().onopen?.());          // a frame only arrives on an opened socket
    // The server omits joined_round in the subsequent round. The offline
    // client never received the previous round_end frame.
    say(state({ phase: "play", levels: ["3", "2"] }));
    expect(leaveAlertText()).toBe(
      "Leave the game? / A bot takes your seat. This round counts as at best a draw for you.");
  });

  it("after a reconnect, the new socket's joined_round frame keeps the joined round's warning", async () => {
    await renderApp();
    const first = ws();
    say(state({ joined_round: true }));
    act(() => first.close());
    await act(async () => { await new Promise((r) => setTimeout(r, 1600)); });
    expect(ws()).not.toBe(first);
    say(state({ joined_round: true }));
    expect(leaveAlertText()).toMatch(/You'll wait 1 minute to play again/);
  });

  it("a seat taken at a round end, or a server flag saying otherwise, gets the ranked warning", async () => {
    await renderApp();
    say({ type: "match_started", match_id: null, room: "OPEN", rated: true, joining: true, seat: 2 });
    say(state({ joining_you: true, phase: "round_end" }));
    say(state({ phase: "round_end" }));
    say(state({ phase: "deal" }));
    expect(leaveAlertText()).toMatch(/at best a draw for you\.$/);
    say({ type: "match_started", match_id: null, room: "OPEN", rated: true, joining: true, seat: 2 });
    say(state({ joined_round: false }));
    expect(leaveAlertText()).toMatch(/at best a draw for you\.$/);
    say(state({ joined_round: true }));
    expect(leaveAlertText()).toMatch(/You'll wait 1 minute/);
  });

  it("Leave table on another device: the holder says the table was closed there", async () => {
    await renderApp();
    say(queued());
    say({ type: "queue_state", queued: false, count: 0, replaced: true, by: "device", stopped: true });
    expect(q(".q-toast")?.textContent).toContain("Your table was closed from another device.");
    expect(q(".q-toast")?.textContent).not.toContain("window");
    say(queued());
    say({ type: "queue_state", queued: false, count: 0, replaced: true, by: "window" });
    expect(q(".q-toast")?.textContent).toContain("Your table moved to another window.");
  });

  it("the Duo sheet says Duo: Your Duo and Leave Duo", async () => {
    await renderApp();
    click(button("Duo"));
    say({ type: "party", party_id: "p1", code: "7F2K", you_lead: true, expires_at: nowSecs() + 300,
          members: [{ name: "Jerry", leader: true, you: true }, { name: "Sam", leader: false, you: false }] });
    click(button("Duo"));
    const sheet = q(".q-sheet")!;
    expect(sheet.textContent).toContain("Your Duo");
    expect(button("Leave Duo", sheet)).toBeDefined();
    expect(sheet.textContent?.toLowerCase()).not.toMatch(/\b(pair|party)\b/);
  });

  it("a Duo refusal from the Play box's code shows on Play", async () => {
    await renderApp();
    typeInto(q("input[aria-label='Room or duo code']") as HTMLInputElement, "7F2K");
    click(button(/^Join$/, q(".join-row")!));
    say({ type: "code_kind", code: "7F2K", kind: "party" });
    say({ type: "error", code: "same_device", message: "A Duo needs two devices." });
    expect(document.body.textContent).toContain("A Duo needs two devices.");
  });

  it("a guest is never called ranked: search, table, Duo sheet, offer and the table's top bar", async () => {
    signedIn = false;
    await renderApp();
    click(button("Duo"));
    expect(q(".q-sheet .ranked-chip")).toBeNull();
    click(button("Cancel", q(".q-sheet")!));
    say(queued());
    expect(panel()?.textContent).not.toMatch(/ranked/i);
    say(queued({ offer: { room: "OPEN", pick: 2, expires_at: nowSecs() + 10, round_end: true,
                          seats: [0, 1, 2, 3].map((i) => ({ name: `Bot ${i}`, bot: true, open: i !== 0 })) },
                 bots_paused: true, bots_at: null }));
    expect(panel()?.textContent).not.toMatch(/ranked/i);
    say(queued({ offer: { room: "OPEN", pick: 2, expires_at: nowSecs() + 10, round_end: false,
                          seats: [0, 1, 2, 3].map((i) => ({ name: `Bot ${i}`, bot: true, open: i !== 0 })) },
                 bots_paused: true, bots_at: null }));
    expect(panel()?.classList.contains("tp-join")).toBe(true);
    expect(panel()?.textContent).not.toMatch(/ranked/i);
    say(queued({ offer: null, table: { id: "t1", you: 0, timer: null, ready: 0, of: 2, you_ready: false,
                                       waiting_for: ["Sam"],
                                       seats: [{ name: "Me", you: true, ready: false, reconnecting: false,
                                                 since: nowSecs(), pair: false, leader: true },
                                               null,
                                               { name: "Sam", you: false, ready: false, reconnecting: false,
                                                 since: nowSecs(), pair: false, leader: true },
                                               null] } }));
    expect(panel()?.classList.contains("tp-shared")).toBe(true);
    expect(document.body.textContent).not.toMatch(/ranked table|waiting table/i);
    expect(panel()?.textContent).not.toMatch(/ranked/i);
    expect(q(".ranked-chip")).toBeNull();
    say({ type: "match_started", match_id: "m1", room: "OPEN", rated: false, guest: true });
    say(state({ guest: true }));
    expect(q(".table-screen .mode-chip")).toBeNull();
    // a table that is not rated at all sends no guest flag: still no chip for a signed-out player
    say(state());
    expect(q(".table-screen .mode-chip")).toBeNull();
  });

  it("a cooldown says why, and holds Play and Duo until it ends", async () => {
    await renderApp();
    fakeClock();
    say({ type: "queue_state", queued: false, count: 0, cooldown_until: nowSecs() + 252 });
    expect(q(".play-cool-line")?.textContent).toBe("You left a table you joined.");
    expect(findBtn().textContent).toBe("Play in 4:12");
    expect(button("Duo", q(".lobby-panel")!)?.disabled).toBe(true);
    tick(253_000);
    expect(q(".play-cool-line")).toBeNull();
    expect(findBtn().textContent).toBe("Play");
    expect(button("Duo", q(".lobby-panel")!)?.disabled).toBe(false);
  });
});

describe("the unified table on the client", () => {
  const sentOf = (type: string) => FAKE_SENT().filter((m) => m.type === type);
  const FAKE_SENT = () => FakeWS.all.flatMap((w) => w.sent);
  const presence = () => q(".play-presence");

  it("the presence line: waiting first, then open tables split by mode, else nobody; counts only and not a button", async () => {
    await renderApp();
    expect(presence()?.textContent).toBe("Nobody is playing right now");
    expect(presence()?.querySelector(".play-presence-dot")?.getAttribute("aria-hidden")).toBe("true");
    expect(presence()?.closest("button")).toBeNull();
    say({ type: "presence", tables: 2, playing: 3, waiting: 0, ranked: 2, casual: 0 });
    expect(presence()?.textContent).toBe("2 ranked tables have a seat · 3 people playing");
    say({ type: "presence", tables: 1, playing: 1, waiting: 0, ranked: 0, casual: 1 });
    expect(presence()?.textContent).toBe("1 casual table has a seat · 1 person playing");
    say({ type: "presence", tables: 3, playing: 5, waiting: 0, ranked: 2, casual: 1 });
    expect(presence()?.textContent).toBe("3 tables have a seat · 2 ranked, 1 casual · 5 people playing");
    expect(presence()?.querySelector(".play-presence-hl")?.textContent).toBe("2 ranked");
    say({ type: "presence", tables: 1, playing: 1, waiting: 1, ranked: 1, casual: 0 });
    expect(presence()?.textContent).toBe("1 person is waiting for a game");
    say({ type: "presence", tables: 0, playing: 0, waiting: 3, ranked: 0, casual: 0 });
    expect(presence()?.textContent).toBe("3 people are waiting for a game");
    // an older server sends no split
    say({ type: "presence", tables: 2, playing: 4, waiting: 0 });
    expect(presence()?.textContent).toBe("2 tables have a seat · 4 people playing");
    say({ type: "presence", tables: 0, playing: 0, waiting: 0 });
    expect(presence()?.textContent).toBe("Nobody is playing right now");
    // the panel takes Play's place, and the line with it
    say(queued());
    expect(presence()).toBeNull();
  });

  it("the presence line splits by mode only when both have tables, the selected mode's count lit", async () => {
    await renderApp();
    say({ type: "presence", tables: 2, playing: 3, waiting: 0, ranked: 1, casual: 1 });
    expect(presence()?.textContent).toBe("2 tables have a seat · 1 ranked, 1 casual · 3 people playing");
    expect([...presence()!.querySelectorAll(".play-presence-hl")].map((b) => b.textContent)).toEqual(["1 ranked"]);
    click(button("Casual", q(".play-mode")!));
    expect([...presence()!.querySelectorAll(".play-presence-hl")].map((b) => b.textContent)).toEqual(["1 casual"]);
    say({ type: "presence", tables: 1, playing: 2, waiting: 0, ranked: 0, casual: 1 });
    expect(presence()!.querySelector(".play-presence-hl")).toBeNull();
  });

  it("a guest sees the same presence line", async () => {
    signedIn = false;
    await renderApp();
    say({ type: "presence", tables: 1, playing: 2, waiting: 0, ranked: 1, casual: 0 });
    expect(presence()?.textContent).toBe("1 ranked table has a seat · 2 people playing");
  });

  it("the presence line hides during a cooldown and on a reconnect forgets old counts", async () => {
    await renderApp();
    fakeClock();
    say({ type: "presence", tables: 0, playing: 0, waiting: 2 });
    say({ type: "queue_state", queued: false, count: 0, cooldown_until: nowSecs() + 30 });
    expect(presence()).toBeNull();
    tick(31_000);
    expect(presence()?.textContent).toBe("2 people are waiting for a game");
    act(() => ws().close());
    act(() => { vi.advanceTimersByTime(5000); });
    act(() => ws().onopen?.());
    expect(presence()?.textContent).toBe("Nobody is playing right now");
  });

  it("Ranked / Casual is remembered on this device, and Play queues in the chosen mode", async () => {
    await renderApp();
    const modeBtn = (label: string) => button(label, q(".play-mode")!)!;
    expect(modeBtn("Ranked").getAttribute("aria-pressed")).toBe("true");
    click(modeBtn("Casual"));
    expect(modeBtn("Casual").getAttribute("aria-pressed")).toBe("true");
    expect(localStorage.getItem("shengji.playMode")).toBe("casual");
    click(findBtn());
    expect(lastSent()).toEqual({ type: "queue_join", mode: "casual" });
    // at a table the switch shows that table's mode and holds still
    say(queued({ mode: "casual" }));
    expect(modeBtn("Casual").disabled).toBe(true);
    expect(modeBtn("Casual").getAttribute("aria-pressed")).toBe("true");
  });

  it("a stored Casual choice is read back on a fresh page, and blocked storage reads as Ranked", async () => {
    localStorage.setItem("shengji.playMode", "casual");
    const { readPlayMode } = await import("./store");
    expect(readPlayMode()).toBe("casual");
    const spy = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("blocked"); });
    try {
      expect(readPlayMode()).toBe("ranked");
    } finally {
      spy.mockRestore();
    }
    await renderApp();
    click(findBtn());
    expect(lastSent()).toEqual({ type: "queue_join", mode: "casual" });
  });

  it("a single moves seats before Start: a green seat sends table_move; no visible hint, the label says Move here", async () => {
    await renderApp();
    say(atTable([seat("Jerry", { you: true }), seat("Alice"), null, null]));
    await pastGuard();
    const p = panel()!;
    expect(p.querySelector(".tp-hint")).toBeNull();
    expect(p.textContent).not.toMatch(/Tap a green seat/);
    const open = [...p.querySelectorAll<HTMLButtonElement>("button.tp-seat")];
    expect(open.map((b) => b.getAttribute("aria-label")))
      .toEqual(["Open seat, your team. Move here", "Open seat, other team. Move here"]);
    click(open[1]);
    expect(lastSent()).toEqual({ type: "table_move", seat: 3 });
    // seat refusals in a few words
    say({ type: "error", code: "seat_taken", message: "That seat was just taken. Pick another." });
    expect(q(".q-toast")?.textContent).toBe("!That seat was just taken.Pick another.");
    say({ type: "error", code: "already_ready", message: "You tapped Start, so your seat is set." });
    expect(q(".q-toast")?.textContent).toBe("!You tapped Start, so your seat is set.");
    say({ type: "error", code: "pair_seats_fixed", message: "A Duo's seats stay together." });
    expect(q(".q-toast")?.textContent).toBe("!A Duo's seats stay together.");
    // after your Start the seat is set: no seat buttons
    say(atTable([seat("Jerry", { you: true, ready: true }), seat("Alice"), null, null]));
    expect(panel()!.querySelector(".tp-hint")).toBeNull();
    expect(panel()!.querySelector("button.tp-seat")).toBeNull();
  });

  it("a Duo's seats never move", async () => {
    await renderApp();
    say(atTable([seat("Jerry", { you: true, pair: true }), seat("Li"), seat("Kai", { pair: true }), null],
                {}, { party_id: "p1" }));
    expect(panel()!.querySelector(".tp-hint")).toBeNull();
    expect(panel()!.querySelector("button.tp-seat")).toBeNull();
  });

  it("table_moved tells the table which team the mover joined", async () => {
    await renderApp();
    say(atTable([seat("Jerry", { you: true }), null, seat("Alice"), null]));
    say({ type: "table_moved", name: "Alice", seat: 2, your_team: true });
    expect(q(".q-toast")?.textContent).toBe("!Alice moved to your team.");
    expect(q(".q-toast")?.getAttribute("role")).toBe("status");
    say({ type: "table_moved", name: "Alice", seat: 1, your_team: false });
    expect(q(".q-toast")?.textContent).toBe("!Alice moved to the other team.");
  });

  it("still here?: the prompt, a countdown and I'm here; the automatic check is not an answer", async () => {
    await renderApp();
    fakeClock();
    const table = [seat("Jerry", { you: true }), seat("Alice"), null, null];
    say(atTable(table, {}, { still_here_until: nowSecs() + 30 }));
    const p = panel()!;
    expect(lines()).toEqual(["Still here? You leave the table in 0:30."]);
    expect(p.querySelector(".tp-line.warn")?.textContent).toBe("Still here? You leave the table in 0:30.");
    expect(p.querySelector(".tp-hint")).toBeNull();
    expect(live()?.textContent).toBe("Still here? Tap I'm here to stay at the table.");
    tick(GUARD_MS + 10);
    expect(primary()?.textContent).toBe("I'm here");
    tick(15_000);
    expect(lines()).toEqual(["Still here? You leave the table in 0:15."]);
    // the periodic check went out, and the prompt is still up
    expect(sentOf("queue_status").length).toBeGreaterThan(0);
    expect(sentOf("table_here")).toHaveLength(0);
    expect(primary()?.textContent).toBe("I'm here");
    click(primary());
    expect(lastSent()).toEqual({ type: "table_here" });
    say(atTable(table, {}, { still_here_until: null }));
    expect(lines()).toEqual(["0 of 2 ready"]);
    // Start now takes the place under a fresh guard: a second tap cannot start
    expect(primary()?.textContent).toBe("Start now");
    expect(primary()?.disabled).toBe(true);
    tick(GUARD_MS + 10);
    expect(primary()?.disabled).toBe(false);
  });

  it("panel_seq goes back with Start with bots, Start now and Join; panel_changed refreshes quietly", async () => {
    await renderApp();
    say(queued({ panel_seq: 7 }));
    await pastGuard();
    click(primary());
    expect(lastSent()).toEqual({ type: "queue_start_bots", panel_seq: 7 });
    const before = sentOf("queue_status").length;
    say({ type: "error", code: "panel_changed", message: "Your table changed. Look again before you tap." });
    expect(q(".q-toast")).toBeNull();
    expect(q(".lobby-error")).toBeNull();
    expect(sentOf("queue_status").length).toBe(before + 1);
    expect(primary()?.textContent).toBe("Start with bots");
    say(atTable([seat("Jerry", { you: true }), seat("Alice"), null, null], {}, { panel_seq: 8 }));
    await pastGuard();
    click(primary());
    expect(lastSent()).toEqual({ type: "table_start", panel_seq: 8 });
    say({ type: "queue_state", queued: false, count: 0 });
    click(findBtn());
    say(queued({ panel_seq: 9, bots_paused: true, bots_at: null, offer: {
      room: "OPEN", pick: 2, expires_at: nowSecs() + 20, round_end: false,
      seats: [{ name: "Mei", bot: false, open: false }, { name: "Bot 1", bot: true, open: true },
              { name: "Bot 2", bot: true, open: true }, { name: "Bot 3", bot: true, open: true }] } }));
    await pastGuard();
    click(primary());
    expect(lastSent()).toEqual({ type: "open_table_join", room: "OPEN", seat: 2, panel_seq: 9 });
  });

  it("account_in_game with a room on this device: the message in Play's place and Return to your game", async () => {
    await renderApp();
    localStorage.setItem("shengji.room", "GAME");
    await pastGuard();
    click(findBtn());
    say({ type: "error", code: "account_in_game", message: "You are already in a game on another device." });
    expect(q(".play-in-game-line")?.textContent).toBe("You are already in a game on another device.");
    expect(document.body.textContent?.match(/already in a game/g)?.length).toBe(1);   // no toast as well
    expect(q(".q-find")).toBeNull();
    click(button("Return to your game"));
    expect(lastSent()).toMatchObject({ type: "join_room", room: "GAME" });
    expect(findBtn().textContent).toBe("Play");
  });

  it("account_in_game with no room to go back to: just the message, and OK puts Play back", async () => {
    await renderApp();
    await pastGuard();
    click(findBtn());
    say({ type: "error", code: "account_in_game", message: "You are already in a game on another device." });
    expect(q(".play-in-game-line")?.textContent).toBe("You are already in a game on another device.");
    expect(button("Return to your game")).toBeUndefined();
    click(button("OK"));
    expect(q(".play-in-game")).toBeNull();
    expect(findBtn().textContent).toBe("Play");
    expect((findBtn() as HTMLButtonElement).disabled).toBe(false);
  });

  it("a guest refused for its account's game is told so, with no way back but signing in", async () => {
    signedIn = false;
    await renderApp();
    localStorage.setItem("shengji.room", "GAME");
    await pastGuard();
    click(findBtn());
    say({ type: "error", code: "account_in_game", message: "Sign in again to return to your game." });
    expect(q(".play-in-game-line")?.textContent).toBe("Sign in again to return to your game.");
    expect(button("Return to your game")).toBeUndefined();
  });
});

describe("the first joiner", () => {
  const player = (seat: number) => ({
    seat, name: seat === 0 ? "Jerry" : `Bot ${seat}`, is_bot: seat !== 0, connected: true, team: seat % 2,
    cards_left: 3, is_banker: seat === 1, takeover_in: null, controller: seat === 0 ? "human" : "bot",
    reserved_for: null, reserved_secs: null,
  });
  const state = {
    type: "state", room: "SOLO", you: 0, phase: "play", matched: true, allow_joiners: true, joining: [],
    players: [0, 1, 2, 3].map(player), hand: [{ id: 1, code: "S5" }], levels: ["2", "2"],
    games_won: [0, 0], banker: 1, trump: { suit: "S", rank: "2", declarer: 1 }, turn: 1, declare_options: [],
    current_declaration: null, passed: [], trick: { leader: 1, plays: [] }, last_trick: null,
    attacker_points: 0, kitty_count: 8, message: null, notice: null, round_result: null,
  };

  it("a game you started alone says once, politely, who joined and that moves are timed", async () => {
    await renderApp();
    say({ type: "match_started", match_id: "m1", room: "SOLO", rated: true });
    say(state);
    say({ type: "first_joiner", name: "Alice", seat: 2, move_secs: 30, round_end: false });
    const t = q(".table-screen .toast");
    expect(t?.textContent).toBe("Alice joined your table. Moves are now timed, 30 s each.");
    expect(t?.getAttribute("role")).toBe("status");
  });

  it("at a round end the toast says from next round; with no move clock, only who", async () => {
    const { firstJoinerText } = await import("./tableText");
    expect(firstJoinerText({ name: "Alice", move_secs: 30, round_end: true }))
      .toBe("Alice joins your table from next round. Moves are timed from next round, 30 s each.");
    expect(firstJoinerText({ name: "Alice", move_secs: null, round_end: false })).toBe("Alice joined your table.");
    expect(firstJoinerText({ name: "Alice", move_secs: null, round_end: true }))
      .toBe("Alice joins your table from next round.");
    // render something for the shared teardown
    await renderApp();
  });
});
