// The matchmaking queue's screens against a mocked socket: Play's Ranked
// block and the Duo sheet, the queue bar, the waiting table, the pair
// flow, the away notice and the matched game's note.
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
const sentTypes = () => FakeWS.all.flatMap((w) => w.sent).map((m) => m.type);
const lastSent = () => { const all = FakeWS.all.flatMap((w) => w.sent); return all[all.length - 1]; };
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
  it("signed in: Ranked first with a gold Play and Duo, then Casual; no Find a game", async () => {
    await renderApp();
    const labels = [...lobby().querySelectorAll(".play-label")].map((h) => h.textContent);
    expect(labels).toEqual(["Ranked", "Casual"]);
    expect(findBtn().textContent).toBe("Play");
    expect(findBtn().className).toContain("gold");
    say({ type: "queue_count", count: 3 });
    expect(findBtn().textContent).toBe("Play");          // no count under the button
    expect(button("Duo", lobby())).toBeDefined();
    expect(button(/Find a game/)).toBeUndefined();
    expect(button("Create room", lobby())).toBeDefined();
    expect(button("Play bots", lobby())).toBeDefined();
    expect(q("input[aria-label='Room or duo code']")).not.toBeNull();
  });

  it("Play joins the ranked queue at once, with no sheet", async () => {
    await renderApp();
    click(findBtn());
    expect(lastSent()).toEqual({ type: "queue_join" });
    expect(q(".q-sheet")).toBeNull();
    expect(findBtn().textContent).toBe("Searching…");
    expect((findBtn() as HTMLButtonElement).disabled).toBe(true);
  });

  it("Duo opens the pair sheet, titled Duo and marked Ranked", async () => {
    await renderApp();
    click(button("Duo", lobby()));
    expect(lastSent()).toEqual({ type: "party_create" });
    expect(q(".q-sheet h2")?.textContent).toBe("Duo");
    expect(q(".q-sheet .ranked-chip")?.textContent).toBe("Ranked");
  });

  it("a guest: Play and Duo with no Ranked heading, the guest line, and Play bots as a Casual row", async () => {
    signedIn = false;
    await renderApp();
    const labels = [...lobby().querySelectorAll(".play-label")].map((h) => h.textContent);
    expect(labels).toEqual(["Casual"]);
    expect(document.body.textContent).not.toContain("Sign in to play ranked");
    expect(q(".play-guest-line")?.textContent).toBe("Playing as a guest · Sign in to be ranked");
    const bots = button("Play bots", lobby())!;
    expect(bots.className).toContain("grp-row");
    // Play queues a guest exactly as it does an account, with the chip's name
    const name = q(".lobby-panel .guest-pill .account-pill-name")!.textContent;
    click(button("Play", lobby())!);
    expect(lastSent()).toEqual({ type: "queue_join", name });
    expect(localStorage.getItem("shengji.name")).toBe(name);
    say(queued());
    expect(q(".q-find")?.textContent).toBe("Searching…");
    expect(q(".q-bar")).not.toBeNull();
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
    expect(lastSent()).toEqual({ type: "queue_join" });
  });

  it("a guest who signs in mid-search starts over: the search is cleared and Play asked for again", async () => {
    signedIn = false;
    await renderApp();
    click(button("Play", lobby())!);
    say(queued());
    expect(findBtn().textContent).toBe("Searching…");
    const { auth } = await import("../auth");
    act(() => auth.signedIn({ name: "Jerry Yu", email: "j@x", picture: null, display_name: null, name_shown: "Jerry" }));
    await settle();
    expect(q(".q-bar")).toBeNull();
    expect(findBtn().textContent).toBe("Play");
    expect(q(".q-toast")?.textContent).toContain("Signed in. Press Play to search again.");
  });

  it("a guest who signs in at a waiting table or in a pair keeps nothing: the new socket's one Play is the only search", async () => {
    signedIn = false;
    await renderApp();
    say({ type: "party", party_id: "p1", code: "7F2K", you_lead: false, expires_at: nowSecs() + 300,
          members: [{ name: "Sam", leader: true, you: false }, { name: "Guesty", leader: false, you: true }] });
    click(button("Play", lobby())!);
    say(atTable([seat("Guesty", { you: true }), seat("Alice"), null, null]));
    expect(q(".wt-sheet")).not.toBeNull();
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
    expect(q(".wt-sheet")).toBeNull();
    expect(q(".q-bar")).toBeNull();
    expect(q(".q-party-chip")).toBeNull();
    expect(findBtn().textContent).toBe("Play");
    expect(document.body.textContent).not.toContain("left the queue while away");
    expect(fresh.sent.filter((m) => m.type === "queue_join")).toEqual([]);
    click(findBtn());
    expect(fresh.sent.filter((m) => m.type === "queue_join")).toEqual([{ type: "queue_join" }]);
    expect(old.sent.slice(oldSent)).toEqual([]);  // nothing more on the guest's socket
    say(queued());
    expect(findBtn().textContent).toBe("Searching…");
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

describe("the queue bar", () => {
  it("counts down to the bots from the first second on every tab, amber in the last ten", async () => {
    await renderApp();
    fakeClock();
    say(queued());
    expect(q(".q-bar b")?.textContent).toBe("Finding a ranked game");
    expect(q(".q-bar small")?.textContent).toBe("Bots in 1:00");
    tick(6000);
    expect(q(".q-bar small")?.textContent).toBe("Bots in 0:54");
    expect(q(".q-bar")?.getAttribute("title")).toBe("Waiting 0:06");
    expect(q(".q-bar")?.className).not.toContain("warn");
    expect((findBtn() as HTMLButtonElement).disabled).toBe(true);
    tick(43_000);   // 49 s: eleven seconds before the bots
    expect(q(".q-bar small")?.textContent).toBe("Bots in 0:11");
    expect(q(".q-bar")?.className).not.toContain("warn");
    tick(1_000);    // 50 s: ten seconds before the bots
    expect(q(".q-bar")?.className).toContain("warn");
    expect(q(".q-bar small")?.textContent).toBe("Bots in 0:10");
    tick(5_000);
    expect(q(".q-bar small")?.textContent).toBe("Bots in 0:05");
    tick(5_000);
    expect(q(".q-bar small")?.textContent).toBe("Adding bots…");
    // the bar follows to the other tabs
    const { openTab } = await import("../home/route");
    act(() => openTab("leaderboard"));
    expect(q(".q-bar")?.className).toContain("warn");
    act(() => openTab("me"));
    expect(q(".q-bar")).not.toBeNull();
  });

  it("Start with bots sends queue_start_bots; Leave queue leaves", async () => {
    await renderApp();
    say(queued());
    // notices are lifted over the bar while it shows
    const clear = () => document.documentElement.style.getPropertyValue("--q-bar-clear");
    expect(clear()).toMatch(/^\d+px$/);
    expect(q(".q-bar")?.textContent).not.toContain("in queue");   // alone: no count
    click(button("Start with bots", q(".q-bar")!));
    expect(lastSent()).toEqual({ type: "queue_start_bots" });
    expect(button("Starting…")).toBeDefined();
    say({ type: "match_started", match_id: null, room: "BOTS", rated: true });
    expect(q(".q-bar")).toBeNull();
    say(queued());
    click(button("Leave queue", q(".q-bar")!));
    expect(lastSent()).toEqual({ type: "queue_leave" });
    say({ type: "queue_state", queued: false, count: 0 });
    expect(q(".q-bar")).toBeNull();
    expect(findBtn().textContent).toBe("Play");
    expect(clear()).toBe("");
  });

  it("on a desktop or an iPad Play's Ranked card becomes the search, with no strip", async () => {
    viewport(true);
    await renderApp();
    say(queued({ since: nowSecs() - 24, bots_at: nowSecs() + 36 }));
    expect(q(".q-bar:not(.q-card)")).toBeNull();
    expect(q(".q-strip")).toBeNull();
    expect(q(".q-chip")).toBeNull();
    expect(q(".q-pill")).toBeNull();
    const card = q(".play-section .q-card")!;
    expect(card.getAttribute("role")).toBe("status");
    expect(card.querySelector("b")?.textContent).toBe("Searching");
    expect(card.querySelector(".q-bar-time")?.textContent).toBe("0:24");
    expect(card.querySelector("small")?.textContent).toBe("Bots in 0:36");
    expect(card.getAttribute("title")).toBe("Waiting 0:24");
    // the card replaces Play and Duo while it shows
    expect(q(".q-find")).toBeNull();
    expect(button("Duo")).toBeUndefined();
    // the same 44 px rows as the phone's bar
    expect(card.querySelector(".q-bar-acts .q-bots")?.textContent).toBe("Start with bots");
    expect(card.querySelector(".q-bar-acts .q-cancel")?.textContent).toBe("Leave queue");
    click(button("Only tables with people", card));
    expect(lastSent()).toEqual({ type: "queue_wait_players" });
    expect(button("Only tables with people", card)?.getAttribute("aria-checked")).toBe("true");
    expect(card.querySelector("small")?.textContent).toBe("Waiting for people");
    click(button("Start with bots", card));
    expect(lastSent()).toEqual({ type: "queue_start_bots" });
    say({ type: "queue_state", queued: false, count: 0 });
    expect(q(".q-card")).toBeNull();
    expect(findBtn().textContent).toBe("Play");
    expect(button("Duo")).toBeDefined();
  });

  it("on a desktop's other tabs a Searching pill in the top bar goes back to Play", async () => {
    viewport(true);
    await renderApp();
    say(queued({ since: nowSecs() - 24, bots_at: nowSecs() + 36 }));
    const { openTab } = await import("../home/route");
    for (const go of [() => openTab("leaderboard"), () => openTab("me", "stats"), () => openTab("me", "games")]) {
      act(go);
      const pill = q(".topbar .topbar-end .q-pill")!;
      expect(pill.textContent).toBe("Searching · 0:24");
      // a narrow top bar hides this label and keeps the time (topBarFitCss.test.ts)
      expect(pill.querySelector(".q-pill-label")?.textContent).toBe("Searching · ");
      // before the account chip
      expect(pill.nextElementSibling?.className).toContain("account-pill");
      expect(q(".q-strip")).toBeNull();
      expect(q(".q-card")).toBeNull();
    }
    click(q(".q-pill"));
    expect(window.location.hash).toBe("");
    expect(q(".q-pill")).toBeNull();
    expect(q(".play-section .q-card")).not.toBeNull();
  });

  it("a phone held sideways keeps the strip, with 44 px buttons and switch", async () => {
    viewport(false, true);
    await renderApp();
    say(queued({ since: nowSecs() - 24, bots_at: nowSecs() + 36 }));
    expect(q(".q-card")).toBeNull();
    expect(q(".q-pill")).toBeNull();
    expect(q(".topbar .q-chip")).toBeNull();
    const chip = q(".q-strip .q-chip")!;
    expect(chip.textContent).toContain("Finding a ranked game · 0:24 · Bots in 0:36");
    expect(chip.getAttribute("title")).toBe("Waiting 0:24");
    // index.css sizes `.q-chip .q-bots`, `.q-chip .q-cancel` and `.q-chip .q-wait` at 44 px
    expect(button("Start with bots", chip)?.className).toBe("q-bots");
    expect(button("Leave queue", chip)?.className).toBe("q-cancel");
    expect(button("Only tables with people", chip)?.className).toBe("q-wait");
    expect(findBtn().textContent).toBe("Searching…");
    const { openTab } = await import("../home/route");
    act(() => openTab("leaderboard"));
    expect(q(".q-strip .q-chip")).not.toBeNull();
    expect(q(".q-pill")).toBeNull();
  });

  it("a phone held upright keeps the bar, its buttons in the 44 px row", async () => {
    await renderApp();
    say(queued());
    const bar = q(".q-bar")!;
    expect(bar.className).not.toContain("q-card");
    expect(bar.parentElement?.className).toContain("home-narrow");
    // index.css sizes `.q-bar-acts .q-bots` and `.q-bar-acts .q-cancel` at 44 px, 16 px type
    const acts = bar.querySelector(".q-bar-acts")!;
    expect(acts.querySelector(".q-bots")?.textContent).toBe("Start with bots");
    expect(acts.querySelector(".q-cancel")?.textContent).toBe("Leave queue");
    expect(q(".q-card")).toBeNull();
    expect(q(".q-pill")).toBeNull();
    expect(q(".q-strip")).toBeNull();
    expect(findBtn().textContent).toBe("Searching…");
  });

  it("the Only tables with people switch turns the countdown off and back on", async () => {
    await renderApp();
    fakeClock();
    say(queued());
    tick(52_000);
    expect(q(".q-bar")?.className).toContain("warn");
    const sw = () => button("Only tables with people", q(".q-bar")!)!;
    expect(sw().getAttribute("role")).toBe("switch");
    expect(sw().getAttribute("aria-checked")).toBe("false");
    click(sw());
    expect(lastSent()).toEqual({ type: "queue_wait_players" });
    expect(sw().getAttribute("aria-checked")).toBe("true");
    expect(q(".q-bar small")?.textContent).toBe("Waiting for people");
    expect(q(".q-bar")?.className).not.toContain("warn");
    say(queued({ since: nowSecs() - 52, bots_at: null, wait_players: true }));
    tick(120_000);
    expect(q(".q-bar small")?.textContent).toBe("Waiting for people");
    expect(button("Start with bots", q(".q-bar")!)).toBeDefined();
    expect(button("Leave queue", q(".q-bar")!)).toBeDefined();
    click(sw());
    expect(lastSent()).toEqual({ type: "queue_allow_bots" });
    say(queued({ since: nowSecs() - 172, bots_at: nowSecs() + 60, wait_players: false }));
    expect(q(".q-bar small")?.textContent).toBe("Bots in 1:00");
    expect(sw().getAttribute("aria-checked")).toBe("false");
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

describe("the waiting table", () => {
  it("a second person turns the bar into the table: seats, the timer line, Start", async () => {
    await renderApp();
    fakeClock();
    say(queued());
    expect(q(".wt-sheet")).toBeNull();
    say(atTable([seat("Jerry", { you: true }), seat("Alice", { since: nowSecs() }), null, null],
                { timer: { at: nowSecs() + 42, name: "Alice", you: false } }));
    expect(q(".q-bar")).toBeNull();                       // the bar grew into the sheet
    const sheet = q(".wt-sheet")!;
    expect(sheet.querySelector(".q-bar-title")?.textContent).toBe("Ranked table");
    expect(sheet.querySelector(".wt-timer")?.textContent).toBe("Alice starts with bots in 0:42");
    expect(button("Only tables with people", sheet)).toBeDefined();
    const cards = [...sheet.querySelectorAll<HTMLElement>(".seat-card")];
    expect(cards).toHaveLength(4);
    expect(sheet.querySelector(".pos-bottom")?.textContent).toBe("JerryYou");
    expect(sheet.querySelector(".pos-left")?.textContent).toBe("AliceJust joined");
    expect(sheet.querySelector(".pos-left")?.className).toContain("team1");   // the other team
    expect(sheet.querySelector(".pos-top")?.className).toContain("team0");    // your partner's seat
    expect(sheet.querySelector(".pos-top")?.textContent).toBe("Emptya bot plays");
    expect(sheet.querySelector(".wt-count")?.textContent).toBe("0 of 2 ready");
    tick(6000);
    expect(sheet.querySelector(".pos-left")?.textContent).toBe("Alice");
    expect(sheet.querySelector(".wt-timer")?.textContent).toBe("Alice starts with bots in 0:36");
    click(button("Start", sheet));
    expect(lastSent()).toEqual({ type: "table_start" });
    expect(button("Start", sheet)?.disabled).toBe(true);
    // the play page and the tabs stay behind the sheet
    expect(q(".tabbar")).not.toBeNull();
    expect(findBtn()).not.toBeNull();
  });

  it("after your Start the button waits for the others by name; a newcomer keeps your tick", async () => {
    await renderApp();
    say(atTable([seat("Jerry", { you: true, ready: true }), seat("Alice"), null, null]));
    const sheet = q(".wt-sheet")!;
    expect(button("Waiting for Alice", sheet)?.disabled).toBe(true);
    expect(sheet.querySelector(".pos-bottom")?.textContent).toBe("JerryYou · ✓ Ready");
    say(atTable([seat("Jerry", { you: true, ready: true }), seat("Alice", { reconnecting: true }),
                 seat("Bob", { since: nowSecs() }), null],
                { timer: { at: nowSecs() + 18, name: "Alice", you: false } }));
    expect(button("Waiting for 2 players", sheet)?.disabled).toBe(true);
    expect(sheet.querySelector(".pos-left")?.textContent).toBe("AliceReconnecting");
    expect(sheet.querySelector(".pos-top")?.textContent).toBe("BobJust joined");
    expect(sheet.querySelector(".wt-count")?.textContent).toBe("1 of 3 ready");
  });

  it("with every switch on there is no timer, only a unanimous Start", async () => {
    await renderApp();
    fakeClock();
    say(atTable([seat("Jerry", { you: true }), seat("Alice")], {}, { bots_at: null, wait_players: true }));
    const sheet = q(".wt-sheet")!;
    expect(sheet.querySelector(".wt-timer")?.textContent).toBe("Starts when everyone taps Start");
    expect(button("Only tables with people", sheet)?.getAttribute("aria-checked")).toBe("true");
    say(atTable([seat("Jerry", { you: true }), seat("Alice")],
                { timer: { at: nowSecs() + 30, name: "Jerry", you: true } }));
    expect(sheet.querySelector(".wt-timer")?.textContent).toBe("You start with bots in 0:30");
  });

  it("Leave queue frees your seat and puts you back on Play", async () => {
    await renderApp();
    say(atTable([seat("Jerry", { you: true }), seat("Alice"), null, null]));
    click(button("Leave queue", q(".wt-sheet")!));
    expect(lastSent()).toEqual({ type: "queue_leave" });
    say({ type: "queue_state", queued: false, count: 1 });
    expect(q(".wt-sheet")).toBeNull();
    expect((findBtn() as HTMLButtonElement).disabled).toBe(false);
  });

  it("the table starting goes straight to the game: no match-found sheet", async () => {
    await renderApp();
    say(atTable([seat("Jerry", { you: true, ready: true }), seat("Alice", { ready: true }), null, null]));
    say({ type: "match_started", match_id: "t1", room: "ABCD", rated: true });
    expect(q(".wt-sheet")).toBeNull();
    expect(document.body.textContent).not.toContain("match found");
    say({ type: "resume", token: "t1", gen: 1 });
    say(TABLE_STATE);
    expect(q(".table-screen")).not.toBeNull();
  });

  it("the last other person leaving makes you alone again: the bar comes back", async () => {
    await renderApp();
    say(atTable([seat("Jerry", { you: true }), seat("Alice"), null, null]));
    say(queued({ table: null }));
    expect(q(".wt-sheet")).toBeNull();
    expect(q(".q-bar b")?.textContent).toBe("Finding a ranked game");
  });

  it("two minutes without a tap: one notice, back on Play, no cooldown", async () => {
    await renderApp();
    say(atTable([seat("Jerry", { you: true }), seat("Alice"), null, null]));
    say({ type: "queue_removed", reason: "idle", cooldown_until: null });
    expect(q(".wt-sheet")).toBeNull();
    expect(q(".q-toast")?.textContent).toContain("You left the table.");
    expect((findBtn() as HTMLButtonElement).disabled).toBe(false);
  });

  it("a pair's other member sees the table but the leader starts and leaves", async () => {
    await renderApp();
    say({ type: "party", party_id: "p1", code: "7F2K", you_lead: false, expires_at: nowSecs() + 300,
          members: [{ name: "Sam", leader: true, you: false }, { name: "Jerry", leader: false, you: true }] });
    say(atTable([seat("Alice"), seat("Sam", { pair: true }), null, seat("Jerry", { you: true, pair: true, leader: false })],
                { you: 3 }, { party_id: "p1", leader: false }));
    const sheet = q(".wt-sheet")!;
    expect(sheet.querySelector(".pos-bottom")?.textContent).toBe("JerryYou");
    expect(sheet.querySelector(".pos-top")?.textContent).toBe("Sam");     // your partner across
    expect(button("Start", sheet)?.disabled).toBe(true);
    expect(button("Leave queue", sheet)).toBeUndefined();
    expect(sheet.textContent).toContain("Sam leads");
    expect(button("Only tables with people", sheet)).toBeUndefined();
  });

  it("server_error after the room's frames: back to the lobby, queued at the front", async () => {
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
    expect(q(".q-find")).not.toBeNull();
    expect(localStorage.getItem("shengji.room")).toBeNull();   // nothing to resume
    expect(q(".q-bar b")?.textContent).toBe("Back in queue");
    expect(q(".q-toast")?.textContent).toContain("The game could not start.");
  });

  it("a bots game that fails to start returns to the lobby, out of the queue", async () => {
    await renderApp();
    say(queued());
    click(button("Start with bots", q(".q-bar")!));
    say({ type: "match_started", match_id: null, room: "BOTS", rated: true });
    say({ ...TABLE_STATE, room: "BOTS" });
    say({ type: "error", code: "start_failed", message: "Could not start the game." });
    expect(q(".table-screen")).toBeNull();
    expect(q(".q-bar")).toBeNull();
    expect((findBtn() as HTMLButtonElement).disabled).toBe(false);
  });

  it("on a desktop or an iPad the table is a centred modal panel over a blurred Play, with no scrim", async () => {
    viewport(true);
    await renderApp();
    say(queued());
    expect(q(".home-body")?.classList.contains("wt-behind")).toBe(false);
    say(atTable([seat("Jerry", { you: true }), seat("Alice"), null, null],
                { timer: { at: nowSecs() + 42, name: "Alice", you: false } }));
    expect(q(".wt-sheet")).toBeNull();
    expect(q(".q-card")).toBeNull();                      // the search card steps aside
    expect(q(".q-pill")).toBeNull();
    const panel = q(".wt-panel")!;
    expect(panel.getAttribute("role")).toBe("dialog");
    expect(panel.getAttribute("aria-modal")).toBe("true");
    expect(panel.querySelector(".wt-panel-title")?.textContent).toBe("Waiting table Ranked");
    expect(panel.querySelector(".ranked-chip")).not.toBeNull();
    expect(panel.querySelector(".wt-timer")?.textContent).toBe("Alice starts with bots in 0:42");
    expect(panel.querySelectorAll(".seat-card")).toHaveLength(4);
    expect(panel.querySelector(".pos-top")?.textContent).toBe("Emptya bot plays");
    // Play behind blurs, and nothing dims it
    const body = q(".home-body")!;
    expect(body.classList.contains("wt-behind")).toBe(true);
    expect(body.contains(findBtn())).toBe(true);
    expect(q(".q-scrim")).toBeNull();
    expect(q(".q-layer")).toBeNull();
    // modal: focus inside, the page inert
    expect(panel.contains(document.activeElement)).toBe(true);
    expect(findBtn().closest("[inert]")).not.toBeNull();
    say(queued());                                        // back to searching alone
    expect(q(".wt-panel")).toBeNull();
    expect(body.classList.contains("wt-behind")).toBe(false);
    expect(q(".play-section .q-card")?.closest("[inert]")).toBeNull();
  });

  it("the panel's Start, Leave queue and switch send what the sheet's do; Tab stays inside; Escape stays queued", async () => {
    viewport(true);
    await renderApp();
    say(atTable([seat("Jerry", { you: true }), seat("Alice"), null, null]));
    const panel = q(".wt-panel")!;
    const key = (k: string, shiftKey = false) => act(() => {
      document.dispatchEvent(new KeyboardEvent("keydown", { key: k, shiftKey, bubbles: true, cancelable: true }));
    });
    key("Escape");
    expect(q(".wt-panel")).not.toBeNull();
    expect(sentTypes()).not.toContain("queue_leave");
    const inside = [...panel.querySelectorAll<HTMLElement>("button:not([disabled])")];
    act(() => inside[inside.length - 1].focus());
    key("Tab");
    expect(document.activeElement).toBe(inside[0]);
    key("Tab", true);
    expect(document.activeElement).toBe(inside[inside.length - 1]);
    click(button("Only tables with people", panel));
    expect(lastSent()).toEqual({ type: "queue_wait_players" });
    say(atTable([seat("Jerry", { you: true }), seat("Alice"), null, null], {}, { wait_players: true }));
    expect(button("Only tables with people", panel)?.getAttribute("aria-checked")).toBe("true");
    click(button("Only tables with people", panel));
    expect(lastSent()).toEqual({ type: "queue_allow_bots" });
    click(button("Start", panel));
    expect(lastSent()).toEqual({ type: "table_start" });
    say(atTable([seat("Jerry", { you: true, ready: true }), seat("Alice"), null, null]));
    expect(button("Waiting for Alice", panel)?.disabled).toBe(true);
    say(atTable([seat("Jerry", { you: true, ready: true }), seat("Alice", { reconnecting: true }), null, null]));
    expect(panel.querySelector(".pos-left")?.textContent).toBe("AliceReconnecting");
    click(button("Leave queue", panel));
    expect(lastSent()).toEqual({ type: "queue_leave" });
  });

  for (const [name, short] of [["upright", false], ["sideways", true]] as const) {
    it(`a phone held ${name} keeps the sheet`, async () => {
      viewport(false, short);
      await renderApp();
      say(atTable([seat("Jerry", { you: true }), seat("Alice"), null, null]));
      expect(q(".wt-sheet")).not.toBeNull();
      expect(q(".wt-panel")).toBeNull();
      expect(q(".wt-behind")).toBeNull();
    });
  }
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
    expect(lastSent()).toEqual({ type: "queue_join", party_id: "p1" });
    fakeClock();
    say(queued({ party_id: "p1" }));
    tick(12_000);
    expect(q(".q-bar b")?.textContent).toBe("You + Sam");
    expect(q(".q-bar-time")?.textContent).toBe("0:12");
    expect(q(".q-bar small")?.textContent).toBe("Bots in 0:48");
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
    expect(button("Leave queue", q(".q-bar")!)).toBeUndefined();
    expect(q(".q-bar")?.textContent).toContain("Sam leads");
    expect(button("Start with bots", q(".q-bar")!)?.disabled).toBe(true);
    expect(button("Only tables with people")).toBeUndefined();
    say(queued({ party_id: "p1", leader: false, bots_at: null, wait_players: true }));
    expect(q(".q-bar small")?.textContent).toBe("Only tables with people");
    expect(button("Only tables with people")).toBeUndefined();
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
    expect(q(".q-bar")).not.toBeNull();      // the server may still hand it back
    tick(3000);
    expect(q(".q-bar")).toBeNull();
    expect(q(".q-toast")?.textContent).toContain("You left the queue while away.");
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
    expect(q(".q-bar")).not.toBeNull();
    expect(q(".q-toast")).toBeNull();
  });

  it("the server's away removal says so too", async () => {
    await renderApp();
    say(queued());
    say({ type: "queue_removed", reason: "away", cooldown_until: null });
    expect(q(".q-toast")?.textContent).toContain("You left the queue while away.");
    expect(q(".q-bar")).toBeNull();
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
    expect(q(".lobby-error")?.textContent).toBe("No game or pair has that code.");
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
    expect(q(".lobby-error")?.textContent).toBe("No game or pair has that code.");
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
    click(q(".room-code"));
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
  const sheet = () => q(".ot-sheet");
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

  it("O1: the offer shows both teams, your partner seat picked and a ten-second Join", async () => {
    await open();
    fakeClock();
    tell(queued({ offer: offer(), bots_paused: true, bots_at: null }));
    const labelledBy = sheet()?.getAttribute("aria-labelledby");
    expect(labelledBy && document.getElementById(labelledBy)?.textContent).toBe("Table open");
    expect(q(".ot-sub")?.textContent).toBe("Game in progress · first round is unranked");
    const [ours, theirs] = [...document.querySelectorAll(".ot-col")];
    expect([...ours.querySelectorAll(".ot-name")].map((n) => n.textContent)).toEqual(["Jerry", "You"]);
    expect([...theirs.querySelectorAll(".ot-seat.open")].length).toBe(2);
    expect(button(/^Join · /)?.textContent).toBe("Join · 0:10");
    tick(3000);
    expect(button(/^Join · /)?.textContent).toBe("Join · 0:07");
    // tap a dashed seat on the other team: you move there
    click(theirs.querySelector<HTMLElement>(".ot-seat.open"));
    const [ours2] = [...document.querySelectorAll(".ot-col")];
    expect([...ours2.querySelectorAll(".ot-name")].map((n) => n.textContent)).toEqual(["Bot", "You"]);
    click(button(/^Join · /));
    expect(sentLast()).toEqual({ type: "open_table_join", room: "OPEN", seat: 3 });
    expect(button("Joining…")?.disabled).toBe(true);
  });

  it("O1 at a round end says the newcomer plays ranked from the next round", async () => {
    await open();
    tell(queued({ offer: offer({ round_end: true }), bots_paused: true, bots_at: null }));
    expect(q(".ot-sub")?.textContent).toBe("Joins next round · ranked");
  });

  it("a seat taken first: the offer re-renders with it solid and keeps your other pick", async () => {
    await open();
    tell(queued({ offer: offer(), bots_paused: true, bots_at: null }));
    click(button(/^Join · /));
    tell({ type: "error", code: "seat_taken", message: "That seat was just taken. Pick another." });
    const taken = offer({ pick: 1, seats: [offerSeat("Jerry", false, false), offerSeat("Bot 1", true, true),
                                            offerSeat("Bob", false, false), offerSeat("Bot 3", true, true)] });
    tell(queued({ offer: taken, bots_paused: true, bots_at: null }));
    expect(q(".q-toast")?.textContent).toContain("That seat was just taken.");
    expect([...document.querySelectorAll(".ot-name")].map((n) => n.textContent)).toContain("Bob");
    expect(q(".ot-seat.you")).not.toBeNull();
    expect(button(/^Join · /)?.disabled).toBe(false);
  });

  it("O6: Wait keeps queuing; the countdown runs on and the bar's chip brings the offer back", async () => {
    await open();
    tell(queued({ offer: offer(), bots_paused: true, bots_at: null }));
    expect(q(".q-bar small")?.textContent).toBe("Bots paused");
    click(button("Wait"));
    expect(sentLast()).toEqual({ type: "open_table_wait" });
    expect(sheet()).toBeNull();
    tell(queued({ offer: null, open_tables: 1, bots_paused: false, bots_at: nowSecs() + 35 }));
    expect(q(".q-bar small")?.textContent).toMatch(/^Bots in 0:3[56]$/);
    const chip = button("1 open table");
    expect(chip).toBeDefined();
    click(chip);
    expect(sentLast()).toEqual({ type: "open_table_show" });
    tell(queued({ offer: offer(), open_tables: 0, bots_paused: true, bots_at: null }));
    expect(sheet()).not.toBeNull();
    expect(button("1 open table")).toBeUndefined();
  });

  it("O2b: the newcomer watches its seat with Joining after this trick and a Leave", async () => {
    await open();
    tell(queued({ offer: offer(), bots_paused: true, bots_at: null }));
    click(button(/^Join · /));
    tell({ type: "match_started", match_id: null, room: "OPEN", rated: true, joining: true, seat: 2 });
    expect(sheet()).toBeNull();
    tell(state({ you: 2, joining_you: true, turn: 2, joining: [{ seat: 2, name: "Jerry Yu", when: "trick" }] }));
    expect(q(".join-pill")?.textContent).toContain("Joining after this trick");
    expect(q(".join-pill")?.textContent).toContain("A bot plays your seat until then");
    expect(q(".join-notice")).toBeNull();
    expect(button(/^Play/)).toBeUndefined();
    click(button("Leave", q(".join-pill")!));
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

  it("signed in: the ranked seat picker, then join_room with the seat", async () => {
    await open();
    viaPlayBox();
    tell(rankedSeats());
    expect(document.body.textContent).toContain("Ranked game in progress · first round is unranked");
    click(button(/Seat 2/));
    expect(lastSent()).toMatchObject({ type: "join_room", room: "RANK", seat: 2 });
  });

  it("a guest takes a ranked table's seat as an account does", async () => {
    signedIn = false;
    await open();
    viaPlayBox();
    tell(rankedSeats());
    expect(q(".ranked-gate")).toBeNull();
    click(button(/Seat 2/));
    expect(lastSent()).toMatchObject({ type: "join_room", room: "RANK", seat: 2 });
  });

  it("same_device closes the seat picker and shows the server's message", async () => {
    await open();
    viaPlayBox();
    tell(rankedSeats());
    click(button(/Seat 2/));
    tell({ type: "error", code: "same_device", message: "Someone on this device is already at that table." });
    expect(document.body.textContent).not.toContain("Take a seat");
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

  it("a pair's offer highlights both partner seats, fixed, and Join takes them", async () => {
    await open();
    tell({ type: "queue_state", queued: true, count: 2, since: nowSecs(), front: false, party_id: "p1",
           leader: false, bots_at: null, bots_paused: true, open_tables: 0, table: null,
           offer: { room: "OPEN", pick: 3, partner: { seat: 1, name: "Lee" }, expires_at: nowSecs() + 10,
                    round_end: false,
                    seats: [{ name: "Jerry", bot: false, open: false }, { name: "Bot 1", bot: true, open: true },
                            { name: "Bot 2", bot: true, open: true }, { name: "Bot 3", bot: true, open: true }] } });
    const picked = [...document.querySelectorAll(".ot-seat.you")].map((n) => n.querySelector(".ot-name")?.textContent);
    expect(picked).toEqual(["Lee", "You"]);
    expect(document.querySelectorAll(".ot-seat.open").length).toBe(0);
    expect(q(".ot-pair")?.textContent).toBe("Two seats for you and Lee");
    click(button(/^Join · /));
    expect(lastSent()).toEqual({ type: "open_table_join", room: "OPEN", seat: 3 });
  });
});

describe("the open-table offer is a modal sheet", () => {
  const open = async () => {
    await renderApp();
    act(() => { for (const w of FakeWS.all) if (w !== ws()) w.onopen?.(); });
    await settle();
  };
  const tell = (msg: unknown) => act(() => { for (const w of FakeWS.all) w.deliver(msg); });
  const offered = () => ({
    type: "queue_state", queued: true, count: 1, since: nowSecs(), front: false, party_id: null, leader: true,
    bots_at: null, bots_paused: true, open_tables: 0, table: null,
    offer: { room: "OPEN", pick: 2, partner: null, expires_at: nowSecs() + 10, round_end: false,
             seats: [{ name: "Jerry", bot: false, open: false }, { name: "Bot 1", bot: true, open: true },
                     { name: "Bot 2", bot: true, open: true }, { name: "Bot 3", bot: true, open: true }] },
  });
  const dialog = () => q(".ot-sheet");
  const escape = () => act(() => {
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  });
  const waits = () => FakeWS.all.flatMap((w) => w.sent).filter((m) => m.type === "open_table_wait").length;
  function touch(type: string, y: number, el: Element) {
    const e = new Event(type, { bubbles: true, cancelable: true });
    const ended = type === "touchend" || type === "touchcancel";
    Object.defineProperty(e, "touches", { value: ended ? [] : [{ clientX: 200, clientY: y }] });
    Object.defineProperty(e, "changedTouches", { value: [{ clientX: 200, clientY: y }] });
    act(() => { el.dispatchEvent(e); });
  }
  function dragDown(el: Element) {
    vi.spyOn(dialog()!, "getBoundingClientRect").mockReturnValue({ height: 400 } as DOMRect);
    touch("touchstart", 100, el);
    for (let i = 1; i <= 10; i++) touch("touchmove", 100 + 30 * i, el);
    touch("touchend", 400, el);
  }

  it("takes focus from a background control, is aria-modal with the page inert, and Escape is Wait", async () => {
    await open();
    const create = button("Create room")!;
    act(() => create.focus());
    expect(document.activeElement).toBe(create);
    tell(offered());
    expect(dialog()?.getAttribute("aria-modal")).toBe("true");
    expect(dialog()!.contains(document.activeElement)).toBe(true);
    expect(create.closest("[inert]")).not.toBeNull();
    escape();
    expect(lastSent()).toEqual({ type: "open_table_wait" });
    expect(dialog()).toBeNull();
    await settle();
    expect(create.closest("[inert]")).toBeNull();
    expect(document.activeElement).toBe(create);         // focus goes back to the opener
  });

  it("a tap on the scrim is Wait", async () => {
    await open();
    tell(offered());
    click(q(".q-scrim"));
    expect(lastSent()).toEqual({ type: "open_table_wait" });
    expect(dialog()).toBeNull();
  });

  it("a drag down is Wait", async () => {
    await open();
    tell(offered());
    dragDown(q(".ot-sheet .q-grab")!);
    await act(async () => { await new Promise((r) => setTimeout(r, 400)); });
    expect(waits()).toBe(1);
    expect(dialog()).toBeNull();
  });

  it("once Join is sent, Escape, the scrim and a drag wait for the server's answer", async () => {
    await open();
    tell(offered());
    click(button(/^Join · /));
    expect(lastSent()).toEqual({ type: "open_table_join", room: "OPEN", seat: 2 });
    escape();
    click(q(".q-scrim"));
    dragDown(q(".ot-sheet .q-grab")!);
    await act(async () => { await new Promise((r) => setTimeout(r, 400)); });
    expect(waits()).toBe(0);
    expect(dialog()).not.toBeNull();
    expect(button("Joining…")?.disabled).toBe(true);
    // the server's answer settles it: a refusal hands dismissal back
    tell({ type: "error", code: "seat_taken", message: "That seat was just taken. Pick another." });
    escape();
    expect(waits()).toBe(1);
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
      expect(findBtn().textContent).toBe("Searching…");
      tick(3000);
      expect(findBtn().textContent).toBe("Play");
      expect(q(".q-toast")?.textContent).toContain("Couldn't start searching.");
      expect(lastSent()).toMatchObject({ type: "queue_status" });
      say(queued());                       // it did reach the server after all
      expect(q(".q-bar")).not.toBeNull();
    });
  }

  it("a confirmed Play does not revert", async () => {
    await renderApp();
    fakeClock();
    click(findBtn());
    say(queued());
    tick(3000);
    expect(q(".q-bar")).not.toBeNull();
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
    expect(q(".q-bar")).toBeNull();
    expect(findBtn().textContent).toBe("Play");
    expect(q(".q-toast")?.textContent).toContain("You're no longer searching.");
    expect(q(".q-toast")?.textContent).toContain("Press Play to search again.");
  });

  it("a search held by another device of yours shows as such, and clears when it ends", async () => {
    await renderApp();
    say({ type: "queue_state", queued: true, elsewhere: true, count: 2, since: nowSecs(), leader: true,
          table: null, offer: null });
    expect(q(".q-bar")?.textContent).toContain("Searching on another device");
    expect(findBtn().textContent).toBe("Searching…");
    say({ type: "queue_state", queued: false, count: 1 });
    expect(q(".q-bar")).toBeNull();
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
    expect(q(".q-bar")).toBeNull();
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
    click(d.querySelector<HTMLElement>(".leave-alert-keep"));
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

  it("leaving a round joined from an open table: not ranked for you, and a 5-minute wait", async () => {
    await renderApp();
    say({ type: "match_started", match_id: null, room: "OPEN", rated: true, joining: true, seat: 2 });
    say(state({ joining_you: true }));
    say(state());
    expect(leaveAlertText()).toBe(
      "Leave the table? / This round isn't ranked for you, and leaving means a 5-minute wait to search.");
    // the round over, the next one is an ordinary ranked round
    say(state({ phase: "round_end" }));
    say(state({ phase: "deal" }));
    expect(leaveAlertText()).toBe(
      "Leave this ranked game? / A bot takes your seat, and this round counts as at best a draw.");
  });

  it("after a reload, state frames alone (no match_started) carry the joined round's warning", async () => {
    // a fresh module load is a reload: the client never saw this seat's match_started
    await renderApp();
    say(state({ joined_round: true }));
    expect(leaveAlertText()).toBe(
      "Leave the table? / This round isn't ranked for you, and leaving means a 5-minute wait to search.");
    // the server omits the flag once the round is over; the round end clears it
    say(state({ phase: "round_end" }));
    say(state({ phase: "deal" }));
    expect(leaveAlertText()).toBe(
      "Leave this ranked game? / A bot takes your seat, and this round counts as at best a draw.");
  });

  it("review: reconnect after the joined round ends clears its warning", async () => {
    await renderApp();
    const first = ws();
    say(state({ joined_round: true }));
    expect(leaveAlertText()).toMatch(/5-minute wait/);
    act(() => first.close());
    await act(async () => { await new Promise((r) => setTimeout(r, 1600)); });
    expect(ws()).not.toBe(first);
    // The server omits joined_round in the subsequent round. The offline
    // client never received the previous round_end frame.
    say(state({ phase: "play", levels: ["3", "2"] }));
    expect(leaveAlertText()).toBe(
      "Leave this ranked game? / A bot takes your seat, and this round counts as at best a draw.");
  });

  it("after a reconnect, the new socket's joined_round frame keeps the joined round's warning", async () => {
    await renderApp();
    const first = ws();
    say(state({ joined_round: true }));
    act(() => first.close());
    await act(async () => { await new Promise((r) => setTimeout(r, 1600)); });
    expect(ws()).not.toBe(first);
    say(state({ joined_round: true }));
    expect(leaveAlertText()).toMatch(/isn't ranked for you, and leaving means a 5-minute wait/);
  });

  it("a seat taken at a round end, or a server flag saying otherwise, gets the ranked warning", async () => {
    await renderApp();
    say({ type: "match_started", match_id: null, room: "OPEN", rated: true, joining: true, seat: 2 });
    say(state({ joining_you: true, phase: "round_end" }));
    say(state({ phase: "round_end" }));
    say(state({ phase: "deal" }));
    expect(leaveAlertText()).toMatch(/^Leave this ranked game\?/);
    say({ type: "match_started", match_id: null, room: "OPEN", rated: true, joining: true, seat: 2 });
    say(state({ joined_round: false }));
    expect(leaveAlertText()).toMatch(/^Leave this ranked game\?/);
    say(state({ joined_round: true }));
    expect(leaveAlertText()).toMatch(/isn't ranked for you/);
  });

  it("Leave queue on another device: the holder says the search was stopped there", async () => {
    await renderApp();
    say(queued());
    say({ type: "queue_state", queued: false, count: 0, replaced: true, by: "device", stopped: true });
    expect(q(".q-toast")?.textContent).toContain("Search stopped from another device.");
    expect(q(".q-toast")?.textContent).not.toContain("window");
    say(queued());
    say({ type: "queue_state", queued: false, count: 0, replaced: true, by: "window" });
    expect(q(".q-toast")?.textContent).toContain("Your search moved to another window.");
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
    expect(q(".q-bar b")?.textContent).toBe("Finding a game");
    say(queued({ offer: { room: "OPEN", pick: 2, expires_at: nowSecs() + 10, round_end: true,
                          seats: [0, 1, 2, 3].map((i) => ({ name: `Bot ${i}`, bot: true, open: i !== 0 })) },
                 bots_paused: true, bots_at: null }));
    expect(q(".ot-sub")?.textContent).toBe("Joins next round");
    say(queued({ offer: { room: "OPEN", pick: 2, expires_at: nowSecs() + 10, round_end: false,
                          seats: [0, 1, 2, 3].map((i) => ({ name: `Bot ${i}`, bot: true, open: i !== 0 })) },
                 bots_paused: true, bots_at: null }));
    expect(q(".ot-sub")?.textContent).toBe("Game in progress");
    say(queued({ offer: null, table: { id: "t1", you: 0, timer: null, ready: 0, of: 2, you_ready: false,
                                       waiting_for: ["Sam"],
                                       seats: [{ name: "Me", you: true, ready: false, reconnecting: false,
                                                 since: nowSecs(), pair: false, leader: true },
                                               null,
                                               { name: "Sam", you: false, ready: false, reconnecting: false,
                                                 since: nowSecs(), pair: false, leader: true },
                                               null] } }));
    expect(q(".wt-sheet .q-bar-title")?.textContent).toBe("Table");
    expect(document.body.textContent).not.toMatch(/ranked table|waiting table/i);
    expect(q(".ranked-chip")).toBeNull();
    say({ type: "match_started", match_id: "m1", room: "OPEN", rated: false, guest: true });
    say(state({ guest: true }));
    expect(q(".table-screen .mode-chip")).toBeNull();
    // a table that is not rated at all sends no guest flag: still no chip for a signed-out player
    say(state());
    expect(q(".table-screen .mode-chip")).toBeNull();
  });

  it("an account still sees Finding a ranked game and the Ranked table", async () => {
    await renderApp();
    say(queued());
    expect(q(".q-bar b")?.textContent).toBe("Finding a ranked game");
  });
});
