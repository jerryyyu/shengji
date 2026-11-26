// The matchmaking queue's screens against a mocked socket: Play's Ranked
// block and the Duo sheet, the queue bar, the waiting table, the pair
// flow, the away notice and the matched game's note.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { WIDE } from "../home/HomeShell";
import { SHORT_VIEWPORT } from "../phoneLayout";
import { GUARD_MS } from "./useKindGuard";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { framer, tableFrameFor } from "./testFrames";
import type { TableFrameMsg } from "./messages";

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
const sentTypes = () => FakeWS.all.flatMap((w) => w.sent).map((m) => m.type);
const lastSent = () => { const all = FakeWS.all.flatMap((w) => w.sent); return all[all.length - 1]; };
const sentCount = () => FakeWS.all.flatMap((w) => w.sent).length;
const nowSecs = () => Date.now() / 1000;
const SERVER_FRAMES = JSON.parse(readFileSync(join(__dirname, "fixtures", "table_frames.json"), "utf8")) as
  { scenario: string; queue_state: Record<string, unknown>; table: TableFrameMsg }[];

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
afterEach(async () => {
  vi.useRealTimers();
  // this test's store stops its timers: a periodic status check from it
  // would otherwise send, and save its guest name, during a later test
  (await import("./store")).queue.reset();
  // and its connection: a connect still pending would be abandoned and
  // retried on a real timer, during a later test
  (await import("../ws")).conn.stop();
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
/** A button's words, without the seconds of a timer ring inside it. */
const words = (b: Element) => (b.textContent ?? "").slice(b.querySelector(".timer-ring")?.textContent?.length ?? 0);
const button = (text: string | RegExp, scope: ParentNode = document) => buttons(scope).find((b) => {
  const t = words(b);
  return typeof text === "string" ? t === text : text.test(t);
});
/** Opens a panel's Table settings row, where its switches are. */
const openSettings = (p: ParentNode) => {
  const row = p.querySelector<HTMLButtonElement>("button.tp-settings");
  if (row && row.getAttribute("aria-expanded") !== "true") click(row);
};
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
              sit?: string; pair?: boolean; leader?: boolean } | null;
const seat = (name: string, over: Partial<NonNullable<Seat>> = {}): Seat => ({
  name, you: false, ready: false, reconnecting: false, since: nowSecs() - 30, sit: `sit-${name}`, pair: false,
  leader: true, ...over,
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
      // the joiners but you whose Ready is out: never the owner, never one reconnecting
      waiting_for: seats.flatMap((s, at) => s && at !== ((table.opener as number | undefined) ?? 0)
        && !s.ready && !s.you && !s.reconnecting ? [s.name] : []),
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
    expect(findBtn().textContent).toBe("Play");          // no count under the button
    expect(button("Duo", lobby())).toBeDefined();
    expect(button(/Find a game/)).toBeUndefined();
    expect(button(/Create room/, lobby())).toBeUndefined();
    expect(button(/Play bots/, lobby())).toBeUndefined();
    expect(q("input[aria-label='Table code']")).not.toBeNull();
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

  it("Duo opens your own table as a Duo, in the mode chosen: no sheet, no Duo code, no chip", async () => {
    await renderApp();
    click(button("Duo", lobby()));
    expect(lastSent()).toEqual({ type: "queue_join", mode: "ranked", duo: true });
    expect(q(".q-sheet")).toBeNull();
    expect(q(".q-party-chip")).toBeNull();
    expect(document.body.textContent).not.toContain("Duo code");
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

  it("a guest's Duo opens a Duo table as an account's does, with the chip's name", async () => {
    signedIn = false;
    await renderApp();
    const name = q(".lobby-panel .guest-pill .account-pill-name")!.textContent;
    click(button("Duo", lobby())!);
    expect(lastSent()).toEqual({ type: "queue_join", mode: "ranked", duo: true, name });
    expect(q(".q-sheet")).toBeNull();
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
    expect(q(".toast")?.textContent).toContain("Signed in. Press Play to find a table.");
  });

  it("a guest who signs in at a waiting table or in a pair keeps nothing: the new socket's one Play is the only search", async () => {
    signedIn = false;
    await renderApp();
    say({ type: "party", party_id: "p1", code: "7F2K", you_lead: false, expires_at: nowSecs() + 300,
          members: [{ name: "Sam", leader: true, you: false }, { name: "Guesty", leader: false, you: true }] });
    // Sam searches for the pair
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
    // the server holds nothing for the account: it says only that it is not queued
    say({ type: "queue_state", queued: false, count: 1 });
    tick(10_000);                                 // past the reconnect resync: no "left while away"
    expect(panel()).toBeNull();
    expect(q(".q-party-chip")).toBeNull();
    tick(GUARD_MS + 10);
    expect(findBtn().textContent).toBe("Play");
    expect(document.body.textContent).not.toContain("left the table while away");
    expect(fresh.sent.filter((m) => m.type === "queue_join")).toEqual([]);
    click(findBtn());
    expect(fresh.sent.filter((m) => m.type === "queue_join")).toEqual([{ type: "queue_join", mode: "ranked" }]);
    // nothing more on the guest's socket but its own buffered telemetry, handed over with it
    expect(old.sent.slice(oldSent).filter((m) => m.type !== "client_event")).toEqual([]);
    say(queued());
    expect(panel()).not.toBeNull();
    expect(fresh.sent.filter((m) => m.type === "queue_join")).toHaveLength(1);
  });

  it("a guest's Sign in opens the one identity sheet; the line stays under Play", async () => {
    signedIn = false;
    await renderApp();
    click(q(".play-guest-signin") as HTMLButtonElement);
    expect(q(".play-guest-line")?.textContent).toBe("Playing as a guest · Sign in to be ranked");
    expect(q(".lobby-panel .google-signin")).toBeNull();
    expect(document.querySelectorAll(".identity-sheet")).toHaveLength(1);
    expect(q(".identity-sheet input[aria-label='Your name']")).not.toBeNull();
    expect(q(".identity-sheet .google-signin")).not.toBeNull();
    // the website signs in with Google only; nothing promises a provider still to come
    expect(q("[data-testid='apple-signin']")).toBeNull();
    expect(document.body.textContent).not.toMatch(/coming soon/i);
  });
});

it("in the app a guest's Sign in opens the sheet with Apple above Google", async () => {
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
    const buttons = [...document.querySelectorAll(".identity-sheet .google-signin button")].map((b) => b.textContent);
    expect(buttons).toEqual(["Sign in with Apple", "Sign in with Google"]);
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
  if (!d) return null;
  const line = d.querySelector("p");
  return line ? `${d.querySelector("h2")!.textContent} / ${line.textContent}` : d.querySelector("h2")!.textContent;
};
/** The seconds on the panel's timer ring: on the primary button, or by the
 *  line that says who leads a Duo. */
const ringSecs = () => panel()?.querySelector(".tp-primary .timer-ring, .tp-led .timer-ring")?.textContent ?? null;
/** Taps Leave in the open leave sheet. */
const confirmLeave = () => click(q("[role='alertdialog'] .leave-sheet-leave"));

describe("your own table", () => {
  it("telemetry: Play is a tap, your table the waiting_table screen, Start with bots a tap", async () => {
    const { telemetry } = await import("../telemetry");
    await renderApp();
    telemetry.reset();
    fakeClock();
    click(findBtn());
    say(queued());
    tick(GUARD_MS + 10);
    click(primary());
    const evs = telemetry.pending();
    expect(evs.filter((e) => e.e === "tap").map((e) => (e as { id: string }).id)).toEqual(["play", "start_with_bots"]);
    expect(evs.filter((e) => e.e === "screen").map((e) => (e as { name: string }).name)).toContain("waiting_table");
    telemetry.reset();
  });

  it("Play turns into your table in Play's place: seats, Start with bots with the bots' ring, and Leave", async () => {
    await renderApp();
    fakeClock();
    say(queued());
    const p = panel()!;
    expect(q(".q-find")).toBeNull();                       // the panel replaces Play and Duo
    expect(button("Duo", q(".lobby-panel")!)).toBeUndefined();
    expect(p.classList.contains("tp-own")).toBe(true);
    expect(p.querySelector(".tp-title")?.textContent).toBe("Your table");
    // the bots' countdown is the ring on Start with bots, never a line
    expect(lines()).toEqual([]);
    expect(ringSecs()).toBe("60");
    expect(p.textContent).not.toContain("Bots in");
    expect([...p.querySelectorAll(".tp-team-label")].map((l) => l.textContent)).toEqual(["Us", "Them"]);
    // the app draws the table: you, then three open seats, as two teams
    const [ours, theirs] = [...p.querySelectorAll(".tp-col")];
    expect([...ours.querySelectorAll(".tp-seat")].map((s) => s.getAttribute("aria-label")))
      .toEqual(["Open seat, your team", "You, your team"]);
    expect([...theirs.querySelectorAll(".tp-seat.open")]).toHaveLength(2);
    expect(p.querySelector(".tp-seat.open")?.tagName).toBe("DIV");   // nothing to move to alone
    // Wait for people is off and Allow joiners on by default, both inside Table settings
    expect(button("Wait for people", p)).toBeUndefined();
    openSettings(p);
    expect(button("Wait for people", p)?.getAttribute("aria-checked")).toBe("false");
    expect(button("Allow joiners", p)?.getAttribute("aria-checked")).toBe("true");
    tick(6000);
    expect(lines()).toEqual([]);
    expect(ringSecs()).toBe("54");
    expect(p.querySelector(".tp-secondary")?.textContent).toBe("Leave");
    expect(words(primary()!)).toBe("Start with bots");
    click(primary());
    expect(lastSent()).toEqual({ type: "table_start_bots" });
    expect(primary()?.textContent).toBe("Starting…");
    say({ type: "match_started", match_id: null, room: "BOTS", rated: true });
    expect(panel()).toBeNull();
    say(queued());
    tick(GUARD_MS + 10);
    click(button("Leave", panel()!));
    // leaving your own table costs nothing, so the sheet has no line
    expect(leaveSheetText()).toBe("Leave the table?");
    expect(q("[role='alertdialog']")!.textContent).not.toContain("Free");
    expect(lastSent()).not.toEqual({ type: "table_leave" });
    confirmLeave();
    expect(lastSent()).toEqual({ type: "table_leave" });
    say({ type: "queue_state", queued: false, count: 0 });
    expect(panel()).toBeNull();
    expect(findBtn().textContent).toBe("Play");
  });

  it("on a phone the panel takes the art's place and the code box goes; wide screens keep the art beside it", async () => {
    await renderApp();
    expect(q(".lobby-preview")).not.toBeNull();
    expect(q(".join-row")).not.toBeNull();
    say(queued());
    expect(panel()).not.toBeNull();
    expect(q(".lobby-preview")).toBeNull();
    expect(q(".play-tab")!.classList.contains("play-table-up")).toBe(true);
    // seated, the panel is the page: no code box
    expect(q(".join-row")).toBeNull();
    say({ type: "queue_state", queued: false, count: 0 });
    expect(q(".lobby-preview")).not.toBeNull();
    expect(q(".join-row")).not.toBeNull();
  });

  it("in the app, seated, the panel leaves no way to the offline table", async () => {
    (window as unknown as { Capacitor: unknown }).Capacitor = {
      isNativePlatform: () => true,
      registerPlugin: () => new Proxy({}, { get: () => () => Promise.resolve(undefined) }),
    };
    try {
      await renderApp();
      expect(button("Play offline")).toBeDefined();
      say(queued());
      expect(button("Play offline")).toBeUndefined();
    } finally {
      delete (window as unknown as { Capacitor?: unknown }).Capacitor;
    }
  });

  it("the panel opening puts the Play page back at its top", async () => {
    await renderApp();
    const page = q(".play-tab")!;
    page.scrollTop = 300;
    say(queued());
    expect(page.scrollTop).toBe(0);
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
    openSettings(panel()!);
    const sw = () => button("Wait for people", panel()!)!;
    expect(sw().getAttribute("role")).toBe("switch");
    click(sw());
    expect(lastSent()).toEqual({ type: "queue_wait_players" });
    expect(sw().getAttribute("aria-checked")).toBe("true");
    expect(lines()).toEqual([]);
    expect(ringSecs()).toBeNull();
    say(queued({ bots_at: null, wait_players: true }));
    tick(120_000);
    expect(lines()).toEqual([]);
    expect(ringSecs()).toBeNull();
    click(sw());
    expect(lastSent()).toEqual({ type: "queue_allow_bots" });
    say(queued({ bots_at: nowSecs() + 60, wait_players: false }));
    expect(ringSecs()).toBe("60");
  });

  it("your own table has no row for a table you skipped: code, switches and chat only", async () => {
    await renderApp();
    say(queued({ open_tables: 2 }));
    expect(panel()!.textContent).not.toMatch(/table(s)? ha(s|ve) a seat|View/);
  });

  it("a Duo's table: the partner sits across; only the leader has the buttons", async () => {
    await renderApp();
    say({ type: "party", party_id: "p1", code: "7F2K", you_lead: false, expires_at: nowSecs() + 300,
          members: [{ name: "Kai", leader: true, you: false }, { name: "Jerry", leader: false, you: true }] });
    say(queued({ party_id: "p1", leader: false }));
    const p = panel()!;
    expect(p.classList.contains("tp-own")).toBe(true);
    expect(lines()).toEqual([]);
    expect(ringSecs()).toBe("60");
    expect(p.querySelector(".tp-seat.friend")?.getAttribute("aria-label")).toBe("Kai, your Duo partner");
    expect(words(p.querySelector(".tp-led")!)).toBe("Kai leads");
    expect(primary()).toBeNull();
    expect(button("Wait for people", p)).toBeUndefined();
  });

  it("on other tabs a phone's title row holds the Your table pill: the bots' countdown ring, amber in the last ten seconds", async () => {
    await renderApp();
    fakeClock();
    say(queued());
    expect(q(".table-pill")).toBeNull();                   // on Play the panel is the table
    const { openTab } = await import("../home/route");
    act(() => openTab("leaderboard"));
    const pill = () => q(".large-title-row .table-pill");
    expect(pill()?.previousElementSibling?.textContent).toBe("Leaderboard");
    expect(pill()?.querySelector(".table-pill-label")?.textContent).toBe("Your table");
    // the bots' countdown, never the time waited
    const ring = () => q(".table-pill .timer-ring");
    expect(ring()?.textContent).toBe("60");
    expect(ring()?.querySelector(".timer-ring-band")?.getAttribute("style")).toContain("--ring-at: 0s");
    tick(49_000);
    expect(ring()?.textContent).toBe("11");
    expect(ring()?.className).not.toContain("low");
    expect(pill()?.className).not.toContain("warn");
    tick(1_000);
    expect(ring()?.textContent).toBe("10");
    expect(ring()?.className).toContain("low");
    expect(pill()?.className).toContain("warn");
    click(pill());
    expect(q(".table-pill")).toBeNull();
    expect(panel()).not.toBeNull();
  });

  it("waiting for people, the pill is the dot and words with no ring", async () => {
    await renderApp();
    say(queued({ bots_at: null, wait_players: true }));
    const { openTab } = await import("../home/route");
    act(() => openTab("me", "stats"));
    expect(q(".table-pill")?.textContent).toBe("Your table");
    expect(q(".table-pill .timer-ring")).toBeNull();
  });

  it("nothing shows on another tab when you sit nowhere", async () => {
    await renderApp();
    const { openTab } = await import("../home/route");
    for (const go of [() => openTab("leaderboard"), () => openTab("me", "stats")]) {
      act(go);
      expect(q(".table-pill")).toBeNull();
    }
    viewport(true);
    act(() => openTab("leaderboard"));
    expect(q(".table-pill")).toBeNull();
  });

  it("on a desktop or an iPad the panel is in the Ranked card's place with the team columns, and the pill in the top bar elsewhere", async () => {
    viewport(true);
    await renderApp();
    say(queued({ since: nowSecs() - 24, bots_at: nowSecs() + 36 }));
    expect(q(".table-pill")).toBeNull();
    const p = panel()!;
    const [ours] = p.querySelectorAll(".tp-teams .tp-col");
    expect(ours.children[1]?.getAttribute("aria-label")).toBe("You, your team");
    expect(p.querySelectorAll(".tp-teams .tp-seat")).toHaveLength(4);
    expect(p.closest("[aria-modal]")).toBeNull();
    expect(p.closest("[inert]")).toBeNull();
    const { openTab } = await import("../home/route");
    for (const go of [() => openTab("leaderboard"), () => openTab("me", "stats"), () => openTab("me", "games")]) {
      act(go);
      const pill = q(".topbar .topbar-end .table-pill")!;
      // the bots' countdown, 36 s left, not the 24 s waited
      expect(pill.querySelector(".timer-ring")?.textContent).toBe("36");
      expect(pill.querySelector(".table-pill-label")?.textContent).toBe("Your table");
      expect(pill.nextElementSibling?.className).toContain("account-pill");
      expect(document.querySelectorAll(".table-pill")).toHaveLength(1);
    }
    click(q(".table-pill"));
    expect(window.location.hash).toBe("");
    expect(q(".table-pill")).toBeNull();
    expect(panel()).not.toBeNull();
  });

  it("a phone held sideways: the panel on Play, the same pill in the top bar elsewhere", async () => {
    viewport(false, true);
    await renderApp();
    say(queued({ since: nowSecs() - 24, bots_at: nowSecs() + 36 }));
    expect(panel()?.querySelectorAll(".tp-teams .tp-seat")).toHaveLength(4);
    expect(q(".table-pill")).toBeNull();
    const { openTab } = await import("../home/route");
    act(() => openTab("leaderboard"));
    expect(q(".topbar .topbar-end .table-pill .table-pill-label")?.textContent).toBe("Your table");
    expect(q(".topbar .table-pill .timer-ring")?.textContent).toBe("36");
    expect(document.querySelectorAll(".table-pill")).toHaveLength(1);
  });
});

describe("a Duo is a table", () => {
  const JERRY = { name: "Jerry", leader: true, you: true };
  const ALICE = { name: "Alice", leader: false, you: false };
  /** The Duo made at Jerry's table, as either member hears it. */
  const duoParty = (youLead: boolean) => ({
    type: "party", party_id: "d1", code: "4N5Z", table: true, you_lead: youLead, expires_at: nowSecs() + 300,
    members: youLead ? [JERRY, ALICE] : [{ ...JERRY, you: false }, { ...ALICE, you: true }],
  });
  /** Your own table alone: as its Duo opener (`opener`) or the friend who joined by its code. */
  const duoState = (opener: boolean, ready: number, youReady: boolean, over: Record<string, unknown> = {}) =>
    queued({ party_id: "d1", leader: opener, duo: true, held_seat: null, duo_ready: ready, you_ready: youReady,
             code: "4N5Z", opener, allow_joiners: true, ...over });
  const joiners = (p: Element) => [...p.querySelectorAll("[role='switch']")].filter((b) => b.textContent === "Allow joiners");
  const lobby = () => q(".lobby-panel")!;

  it("tap Duo: Your Duo, the partner seat held, the table's code as its Invite, Start with bots and Leave", async () => {
    await renderApp();
    click(button("Duo", q(".lobby-panel")!));
    expect(lastSent()).toEqual({ type: "queue_join", mode: "ranked", duo: true });
    say(queued({ duo: true, held_seat: 2, code: "4N5Z", opener: true, allow_joiners: true }));
    const p = panel()!;
    expect(p.querySelector(".tp-title")?.textContent).toBe("Your Duo");
    const held = p.querySelector(".tp-seat.held")!;
    expect(held.textContent).toBe("·Partner");
    expect(held.getAttribute("aria-label")).toBe("Partner seat, held for your friend");
    expect(held.tagName).not.toBe("BUTTON");
    expect(p.querySelectorAll(".tp-seat.open")).toHaveLength(2);
    expect(p.querySelector(".tp-code")?.textContent).toBe("4N5Z");
    expect(p.querySelector("button.tp-invite")?.getAttribute("aria-label")).toBe("Invite, table code 4 N 5 Z");
    // ranked: Allow joiners and Wait for people fold into Table settings
    expect(p.querySelector(".tp-settings")).not.toBeNull();
    expect(joiners(p)).toHaveLength(0);
    openSettings(p);
    expect(joiners(p)).toHaveLength(1);
    expect(lines()).toEqual([]);
    expect(words(primary()!)).toBe("Start with bots");
    expect(button("Leave", p)).toBeDefined();
    // one code: no Duo sheet, Duo code or Duo bar anywhere
    expect(q(".q-sheet")).toBeNull();
    expect(q(".q-party-chip")).toBeNull();
    expect(document.body.textContent).not.toContain("Duo code");
  });

  it("the friend who opened the link sits in the held seat: You and Jerry, Ready and Leave, no line, no switch", async () => {
    await renderApp();
    say(duoParty(false));
    say(duoState(false, 0, false));
    const p = panel()!;
    expect(p.querySelector(".tp-title")?.textContent).toBe("You and Jerry");
    expect(lines()).toEqual([]);
    expect(p.querySelector(".tp-seat.friend")?.getAttribute("aria-label")).toBe("Jerry, your Duo partner");
    expect(p.querySelector(".tp-seat.held")).toBeNull();
    expect(p.querySelector(".tp-led")).toBeNull();
    expect(words(primary()!)).toBe("Ready");
    await pastGuard();
    expect(primary()!.disabled).toBe(false);
    expect(button("Leave", p)).toBeDefined();
    expect(joiners(p)).toHaveLength(0);
    expect(p.textContent).not.toContain("Allow joiners");
    expect(p.querySelector(".tp-code")?.textContent).toBe("4N5Z");
  });

  it("the partner's Ready: Waiting for Jerry with the bots' ring, and a second tap takes it back", async () => {
    await renderApp();
    say(duoParty(false));
    say(duoState(false, 0, false));
    await pastGuard();
    click(primary());
    expect(lastSent()).toEqual({ type: "table_start" });
    expect(words(primary()!)).toBe("Waiting for Jerry");
    say(duoState(false, 1, true));
    expect(lines()).toEqual([]);
    expect(words(primary()!)).toBe("Waiting for Jerry");
    expect(primary()!.disabled).toBe(false);              // a tap takes the Ready back
    expect(primary()!.classList.contains("waiting")).toBe(true);
    expect(ringSecs()).not.toBeNull();
    expect(panel()!.querySelector(".tp-seat.you")?.getAttribute("aria-label")).toBe("You, ready");
    click(primary());
    expect(lastSent()).toEqual({ type: "table_start", on: false });
    say(duoState(false, 0, false));
    expect(words(primary()!)).toBe("Ready");
    // one Ready and one take-back, never a second Ready
    const starts = FakeWS.all.flatMap((w) => w.sent).filter((m) => m.type === "table_start");
    expect(starts).toEqual([{ type: "table_start" }, { type: "table_start", on: false }]);
  });

  it("the leader's panel: no Ready, Waiting for Alice until her Ready, then Start with bots, and Allow joiners", async () => {
    await renderApp();
    say(duoParty(true));
    say(duoState(true, 0, false));
    await pastGuard();
    const p = panel()!;
    expect(p.querySelector(".tp-title")?.textContent).toBe("You and Alice");
    expect(lines()).toEqual([]);
    expect(words(primary()!)).toBe("Waiting for Alice");
    expect(primary()!.disabled).toBe(true);
    expect(primary()!.classList.contains("waiting")).toBe(true);
    expect(ringSecs()).not.toBeNull();
    expect(p.textContent).not.toContain("Ready");
    say(duoState(true, 1, false));
    expect(panel()!.querySelector(".tp-seat.friend .tp-tick")).not.toBeNull();
    expect(words(primary()!)).toBe("Start with bots");
    expect(primary()!.disabled).toBe(false);
    openSettings(panel()!);
    expect(joiners(panel()!)).toHaveLength(1);
    click(primary());
    expect(lastSent()).toEqual({ type: "table_start_bots" });
    expect(sentTypes()).not.toContain("table_start");
  });

  it("at a waiting table a Duo's partner taps Ready; the held seat stays the friend's, never a move target", async () => {
    await renderApp();
    // a stranger at Jerry's Duo table, the partner seat still held
    say(atTable([seat("Jerry"), seat("Mei", { you: true }), null, null], { you: 1, held_seat: 2, held_seats: [2] },
                { opener: false }));
    const held = panel()!.querySelector(".tp-seat.held")!;
    expect(held.tagName).not.toBe("BUTTON");
    expect(held.getAttribute("aria-label")).toBe("Partner seat, held, other team");
    expect(panel()!.querySelectorAll("button.tp-seat")).toHaveLength(1);    // only seat 3 moves you
    // the Duo member who is not its leader has Ready and Leave, not "Jerry leads"
    say(duoParty(false));
    say(atTable([seat("Mei"), null, seat("Jerry", { pair: true }), seat("Alice", { you: true, pair: true, leader: false })],
                { you: 3 }, { party_id: "d1", leader: false, duo: true, duo_ready: 0, opener: false }));
    expect(panel()!.querySelector(".tp-led")).toBeNull();
    expect(words(primary()!)).toBe("Ready");
    await pastGuard();
    click(primary());
    expect(lastSent()).toEqual({ type: "table_start" });
  });

  it("Leave before the game: one sheet, Leave the Duo?, the partner keeps the table (and its code, when you opened it)", async () => {
    await renderApp();
    say(duoParty(false));
    say(duoState(false, 0, false));
    click(button("Leave", panel()!));
    expect(leaveSheetText()).toBe("Leave the Duo? / Jerry keeps the table.");
    click(q("[role='alertdialog'] .leave-sheet-stay"));
    expect(leaveSheetText()).toBeNull();
    say(duoParty(true));
    say(duoState(true, 0, false));
    click(button("Leave", panel()!));
    expect(leaveSheetText()).toBe("Leave the Duo? / Alice keeps the table and its code.");
    confirmLeave();
    expect(lastSent()).toEqual({ type: "table_leave" });
    expect(document.querySelectorAll("[role='alertdialog']")).toHaveLength(0);
  });

  it("between games the other member's Play tab is one row: Duo with Jerry, and Leave", async () => {
    await renderApp();
    say(duoParty(false));
    const row = q(".play-pair-row")!;
    expect(row.textContent).toBe("Duo with JerryLeave");
    expect(buttons(row).map((b) => b.textContent)).toEqual(["Leave"]);
    expect(button("Play", lobby())).toBeUndefined();
    expect(button("Duo", lobby())).toBeUndefined();
    expect(q(".play-presence")).toBeNull();
  });

  it("between games the leader has the same row above Play and Duo, and Play still queues the pair", async () => {
    await renderApp();
    say(duoParty(true));
    const row = q(".play-pair-row")!;
    expect(row.textContent).toBe("Duo with AliceLeave");
    expect(buttons(q(".play-ranked-row:not(.play-pair-row)")!).map((b) => b.textContent)).toEqual(["Play", "Duo"]);
    await pastGuard();
    click(button("Play", lobby()));
    expect(lastSent()).toEqual({ type: "queue_join", party_id: "d1", mode: "ranked" });
  });

  for (const leader of [true, false]) {
    const role = leader ? "the leader" : "the other member";
    const other = leader ? "Alice" : "Jerry";
    it(`${role}'s Leave goes through the Duo sheet, sends party_leave and no queue_join, and party_closed brings solo Play back`, async () => {
      await renderApp();
      say(duoParty(leader));
      click(button("Leave", q(".play-pair-row")!));
      expect(leaveSheetText()).toBe(`Leave the Duo? / ${other} keeps the table.`);
      click(q("[role='alertdialog'] .leave-sheet-stay"));
      expect(leaveSheetText()).toBeNull();
      expect(sentTypes()).not.toContain("party_leave");
      click(button("Leave", q(".play-pair-row")!));
      confirmLeave();
      expect(lastSent()).toEqual({ type: "party_leave" });
      expect(sentTypes()).not.toContain("queue_join");
      expect(leaveSheetText()).toBeNull();
      say({ type: "party_closed", party_id: "d1", reason: "left", by: leader ? "Jerry" : "Alice", you: true });
      expect(q(".play-pair-row")).toBeNull();
      expect(buttons(q(".play-ranked-row")!).map((b) => b.textContent)).toEqual(["Play", "Duo"]);
      await pastGuard();
      click(button("Play", lobby()));
      expect(lastSent()).toEqual({ type: "queue_join", mode: "ranked" });
    });
  }

  it("a link to another table opened in a Duo asks with the panel's Duo line", async () => {
    window.history.replaceState(null, "", "/?code=WXYZ");
    await renderApp();
    say(duoParty(true));
    say(duoState(true, 0, false));
    await settle();
    expect(leaveSheetText()).toBe("Leave to join WXYZ? / Alice keeps the table and its code.");
    click(q("[role='alertdialog'] .leave-sheet-stay"));
    expect(leaveSheetText()).toBeNull();
  });

  it("the pair row's Leave waits for the socket", async () => {
    await renderApp();
    say(duoParty(true));
    expect(button("Leave", q(".play-pair-row")!)?.disabled).toBe(false);
    act(() => ws().close());
    expect(button("Leave", q(".play-pair-row")!)?.disabled).toBe(true);
  });

  it("alone with the seat held, Leave is the plain table's", async () => {
    await renderApp();
    say(queued({ duo: true, held_seat: 2, code: "4N5Z", opener: true }));
    click(button("Leave", panel()!));
    expect(leaveSheetText()).toBe("Leave the table?");
  });
});

describe("the panel's primary button", () => {
  it("waits 700 ms after the panel changes kind, so a second tap on Play never starts with bots", async () => {
    await renderApp();
    fakeClock();
    click(findBtn());
    say(queued());
    expect(words(primary()!)).toBe("Start with bots");
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
    expect(sentTypes()).not.toContain("table_leave");
    expect(sentTypes()).not.toContain("open_table_wait");
    expect(q("[inert]")).toBeNull();
    act(() => (document.activeElement as HTMLElement | null)?.blur());
    key("Enter");
    expect(lastSent()).toEqual({ type: "table_start_bots" });
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
    expect(region.textContent).toBe("Table. You and Alice. 0 of 1 ready. Waiting for Alice.");
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
  it("a second person makes it shared: both teams, the joiners' ready count, and the owner's Start with the bots' ring", async () => {
    await renderApp();
    fakeClock();
    say(queued());
    say(atTable([seat("Jerry", { you: true }), seat("Alice", { since: nowSecs() }), null, null],
                { timer: { at: nowSecs() + 42, name: "Alice", you: false } }));
    const p = panel()!;
    expect(p.classList.contains("tp-shared")).toBe(true);
    expect(p.querySelector(".tp-title")?.textContent).toBe("You and Alice");
    // one status, the joiners' ready count; the bots' countdown is the ring on Start
    expect(lines()).toEqual(["0 of 1 ready"]);
    expect(ringSecs()).toBe("42");
    const [ours, theirs] = [...p.querySelectorAll(".tp-col")];
    expect([...ours.querySelectorAll(".tp-seat")].map((s) => s.getAttribute("aria-label")))
      .toEqual(["Open seat, your team. Move here", "You"]);
    expect(theirs.querySelector(".tp-seat")?.getAttribute("aria-label")).toBe("Alice, Just joined, other team. Move");
    expect(button("Wait for people", p)).toBeUndefined();  // a personal switch: only alone
    expect(p.querySelector(".tp-hint")).toBeNull();          // the open seat's label says Move here
    tick(6000);
    expect(theirs.querySelector(".tp-seat")?.getAttribute("aria-label")).toBe("Alice, other team. Move");
    expect(ringSecs()).toBe("36");
    // the owner has no Ready: its Start waits, quiet and not dimmed, for Alice's
    expect(words(primary()!)).toBe("Waiting for Alice");
    expect(primary()?.disabled).toBe(true);
    expect(primary()?.classList.contains("waiting")).toBe(true);
    say(atTable([seat("Jerry", { you: true }), seat("Alice", { ready: true }), null, null],
                { timer: { at: nowSecs() + 36, name: "Alice", you: false } }));
    expect(lines()).toEqual(["1 of 1 ready"]);
    expect(words(primary()!)).toBe("Start with bots");
    click(primary());
    expect(lastSent()).toEqual({ type: "table_start_now" });
    expect(primary()?.disabled).toBe(true);
    expect(q(".tabbar")).not.toBeNull();
  });

  it("the owner's Start needs no wait after an arrival, only every connected joiner's Ready; a joiner's button is Ready", async () => {
    await renderApp();
    say(atTable([seat("Jerry", { you: true }), seat("Alice", { ready: true, since: nowSecs() }), null, null]));
    await pastGuard();
    expect(words(primary()!)).toBe("Start with bots");
    expect(primary()?.disabled).toBe(false);
    click(primary());
    expect(lastSent()).toEqual({ type: "table_start_now" });
    expect(words(primary()!)).toBe("Starting…");
    // refused because a Ready was taken back meanwhile: quietly, and the panel looks again
    say({ type: "error", code: "panel_changed", message: "Your table changed. Look again before you tap." });
    expect(q(".toast")).toBeNull();
    // a joiner who is reconnecting does not hold it; one at the table does, by name or by count
    say(atTable([seat("Jerry", { you: true }), seat("Alice", { reconnecting: true }),
                 seat("Bobby Tables The Third", { since: nowSecs() }), null]));
    expect(words(primary()!)).toBe("Waiting for Bobby Tabl…");
    say(atTable([seat("Jerry", { you: true }), seat("Alice"), seat("Bobby Tables The Third"), null]));
    expect(words(primary()!)).toBe("Waiting for 2 players");
    expect(document.body.textContent).not.toContain("Start now");
    // a joiner's button is Ready
    say(atTable([seat("Jerry"), seat("Alice", { you: true }), null, null], { you: 1 }, { opener: false }));
    expect(words(primary()!)).toBe("Ready");
    click(primary());
    expect(lastSent()).toEqual({ type: "table_start" });
  });

  it("after a joiner's Ready the button waits for the owner by name; a newcomer keeps the tick", async () => {
    await renderApp();
    say(atTable([seat("Jerry"), seat("Alice", { you: true, ready: true }), null, null], { you: 1 }, { opener: false }));
    await pastGuard();
    expect(button("Waiting for Jerry", panel()!)?.disabled).toBe(false);   // a tap takes it back
    expect(panel()!.querySelector(".tp-seat.you")?.getAttribute("aria-label")).toBe("You, ready");
    expect(panel()!.querySelector(".tp-seat.you .tp-tick")).not.toBeNull();
    say(atTable([seat("Jerry"), seat("Alice", { you: true, ready: true }),
                 seat("Bobby Tables The Third", { since: nowSecs() }), null],
                { you: 1, timer: { at: nowSecs() + 18, name: "Jerry", you: false } }, { opener: false }));
    expect(button("Waiting for Jerry", panel()!)?.disabled).toBe(false);
    expect(panel()!.querySelector(".tp-title")?.textContent).toBe("You, Jerry and Bobby Tabl…");
    expect(lines()).toEqual(["1 of 2 ready"]);
    // the ring stays on the waiting button: the bots still come
    expect(ringSecs()).toMatch(/^1[789]$/);
    const names = [...panel()!.querySelectorAll(".tp-seat")].map((s) => s.getAttribute("aria-label"));
    expect(names.some((n) => n?.startsWith("Bobby Tables The Third, Just joined"))).toBe(true);
  });

  it("with every switch on there is no timer: no ring, no line and no Add bots row", async () => {
    await renderApp();
    say(atTable([seat("Jerry", { you: true }), seat("Alice")], {}, { bots_at: null, wait_players: true }));
    expect(lines()).toEqual(["0 of 1 ready"]);
    expect(ringSecs()).toBeNull();
    expect(panel()!.textContent).not.toMatch(/Add bots|Bots in/);
    say(atTable([seat("Jerry", { you: true }), seat("Alice")], { timer: { at: nowSecs() + 30, name: "Jerry", you: true } }));
    expect(lines()).toEqual(["0 of 1 ready"]);
    expect(ringSecs()).toMatch(/^(29|30|31)$/);
  });

  it("Leave frees your seat and puts you back on Play", async () => {
    await renderApp();
    say(atTable([seat("Jerry", { you: true }), seat("Alice"), null, null]));
    const before = sentCount();
    click(button("Leave", panel()!));
    expect(leaveSheetText()).toBe("Leave the table? / Alice stays at the table.");
    expect(sentCount()).toBe(before);
    confirmLeave();
    expect(lastSent()).toEqual({ type: "table_leave" });
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
    expect(q(".toast")?.textContent).toContain("Alice left the table.");
  });

  it("two minutes without a tap: one notice, back on Play, no cooldown", async () => {
    await renderApp();
    say(atTable([seat("Jerry", { you: true }), seat("Alice"), null, null]));
    say({ type: "queue_removed", reason: "idle", cooldown_until: null });
    expect(panel()).toBeNull();
    expect(q(".toast")?.textContent).toContain("You left the table.");
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
      .toEqual(["Sam, your Duo partner", "You"]);
    expect(primary()).toBeNull();
    expect(button("Leave", p)).toBeUndefined();
    expect(words(p.querySelector(".tp-led")!)).toBe("Sam leads");
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
    expect(q(".toast")?.textContent).toContain("The game could not start.");
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

  it("on a desktop or an iPad the art stays beside the panel", async () => {
    viewport(true);
    await renderApp();
    say(queued());
    expect(panel()).not.toBeNull();
    expect(q(".lobby-preview")).not.toBeNull();
    expect(q(".join-row")).toBeNull();
  });

  it("on a desktop or an iPad the shared table is the same inline panel with the team columns", async () => {
    viewport(true);
    await renderApp();
    say(atTable([seat("Jerry", { you: true }), seat("Alice"), null, null],
                { timer: { at: nowSecs() + 42, name: "Alice", you: false } }));
    const p = panel()!;
    expect(p.getAttribute("role")).toBeNull();
    const [ours, theirs] = p.querySelectorAll(".tp-teams .tp-col");
    expect(ours.children[1]?.getAttribute("aria-label")).toBe("You");
    expect(theirs.children[0]?.getAttribute("aria-label")).toBe("Alice, other team. Move");
    expect(ours.children[0]?.getAttribute("aria-label")).toBe("Open seat, your team. Move here");
    expect(ours.children[0]?.tagName).toBe("BUTTON");
    expect(q(".home-body")?.className).not.toContain("wt-behind");
    expect(q("[inert]")).toBeNull();
    expect(lines()).toEqual(["0 of 1 ready"]);
    expect(ringSecs()).toBe("42");
  });
});

describe("a pair the server forgot", () => {
  const PAIR = { type: "party", party_id: "p9", code: "FG3K", you_lead: true,
                 members: [{ name: "Jerry", leader: true, you: true }], expires_at: 0 };

  it("Leave answered not_in_party drops the pair without an error", async () => {
    await renderApp();
    const { queue } = await import("./store");
    say({ ...PAIR, expires_at: nowSecs() + 300 });
    expect(queue.view.party).not.toBeNull();
    say({ type: "error", code: "not_in_party", message: "You are not in a party." });
    expect(queue.view.party).toBeNull();
    expect(q(".toast")).toBeNull();
  });

  it("a reconnect that gets no pair back drops it", async () => {
    await renderApp();
    const { queue } = await import("./store");
    say({ ...PAIR, expires_at: nowSecs() + 300 });
    fakeClock();
    act(() => ws().close());
    tick(600);
    act(() => ws().onopen?.());
    expect(queue.view.party).not.toBeNull();      // the server may still hand it back
    tick(3000);
    expect(queue.view.party).toBeNull();
  });

  it("a reconnect that gets the pair back keeps it", async () => {
    await renderApp();
    const { queue } = await import("./store");
    say({ ...PAIR, expires_at: nowSecs() + 300 });
    fakeClock();
    act(() => ws().close());
    tick(600);
    act(() => ws().onopen?.());
    say({ ...PAIR, expires_at: nowSecs() + 300 });
    tick(3000);
    expect(queue.view.party).not.toBeNull();
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
    expect(q(".toast")?.textContent).toContain("You left the table while away.");
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
    expect(q(".toast")).toBeNull();
  });

  it("the server's away removal says so too", async () => {
    await renderApp();
    say(queued());
    say({ type: "queue_removed", reason: "away", cooldown_until: null });
    expect(q(".toast")?.textContent).toContain("You left the table while away.");
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

  it("a matched room says Ranked at the top of the ⋯ menu, not in the top bar; a casual room Casual", async () => {
    await renderApp();
    say({ type: "match_started", match_id: "m1", room: "ABCD", rated: true });
    say(state(true));
    expect(q(".table-screen .hud-bar")!.textContent).not.toMatch(/Ranked|Casual/);
    act(() => q(".hud-more-btn")!.click());
    const mode = q(".table-screen .hud-menu .hud-menu-mode");
    expect(mode?.textContent).toBe("Ranked");
    expect(mode?.classList.contains("ranked")).toBe(true);
    say(state(false));
    expect(q(".hud-menu-mode")?.textContent).toBe("Casual");
  });
});

describe("one code for rooms and tables", () => {
  const typeInto = (input: HTMLInputElement, value: string) => {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
    act(() => { setter.call(input, value); input.dispatchEvent(new Event("input", { bubbles: true })); });
  };
  const playBox = () => q("input[aria-label='Table code']") as HTMLInputElement;
  const playJoin = () => click(button(/^Join$/, q(".join-row")!));
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

  const MISS = (code: string) => ({ type: "error", code: "room_not_found", peek: code, message: "No table has that code." });

  it("the Play box opens a room code's Join panel, and Join goes into the room", async () => {
    await renderApp();
    typeInto(playBox(), "wxyz");
    playJoin();
    expect(lastSent()).toEqual({ type: "table_peek", code: "WXYZ" });
    say(seats("WXYZ"));
    await settle();
    expect(sentTypes()).not.toContain("table_join");
    click(button("Join", q(".tp-join-code")!));
    expect(lastSent()).toMatchObject({ type: "table_join", code: "WXYZ", expect: "room", name: "Jerry", seat: 2 });
  });

  it("the Play box with an older client's pair code: no table has it, and no pair is joined", async () => {
    await renderApp();
    typeInto(playBox(), "7F2K");
    playJoin();
    say(MISS("7F2K"));
    expect(q(".toast")?.textContent).toBe("No table has that code.");
    expect(sentTypes()).not.toContain("party_join");
    expect(button(/^Join$/, q(".join-row")!)?.disabled).toBe(false);
  });

  it("a code that names nothing says so in the Play box", async () => {
    await renderApp();
    typeInto(playBox(), "ZZZZ");
    playJoin();
    say(MISS("ZZZZ"));
    expect(q(".toast")?.textContent).toBe("No table has that code.");
    expect(q(".tp-join-code")).toBeNull();
    expect(sentTypes()).not.toContain("party_join");
  });

  const joinPanel = () => q(".tp-join-code");

  it("a ?code= link for a room opens its Join panel, and Join goes into the room", async () => {
    window.history.replaceState(null, "", "/?code=wxyz");
    await renderApp();
    expect(lastSent()).toEqual({ type: "table_peek", code: "WXYZ" });
    say(seats("WXYZ"));
    await settle();
    expect(sentTypes()).not.toContain("table_join");
    expect(joinPanel()?.querySelector(".tp-title")?.textContent).toBe("Join Host");
    click(button("Join", joinPanel()!));
    expect(lastSent()).toMatchObject({ type: "table_join", code: "WXYZ", expect: "room", name: "Jerry" });
  });

  it("an older ?room= link reads as ?code=, and its ?name= is dropped: the guest joins under the chip's name", async () => {
    signedIn = false;
    window.history.replaceState(null, "", "/?room=WXYZ&name=Ann");
    await renderApp();
    expect(lastSent()).toEqual({ type: "table_peek", code: "WXYZ" });
    expect(window.location.search).toBe("?code=WXYZ");
    say(seats("WXYZ"));
    await settle();
    expect(sentTypes()).not.toContain("table_join");
    // no name sheet: the chip already shows a random name
    expect(q(".q-layer:not(.q-out) .q-sheet")).toBeNull();
    // the chip's random name, kept for the next page load
    const chipName = q(".guest-pill .account-pill-name")?.textContent;
    expect(chipName).toBeTruthy();
    expect(chipName).not.toBe("Guest");
    expect(localStorage.getItem("shengji.name")).toBe(chipName);
    click(button("Join", joinPanel()!));
    expect(lastSent()).toMatchObject({ type: "table_join", code: "WXYZ", expect: "room", name: chipName });
    expect(lastSent()).not.toMatchObject({ name: "Ann" });
  });

  it("a name another tab saves after this page read its own: the guest joins under the chip's name", async () => {
    signedIn = false;
    let answerMe: () => void = () => {};
    const served = globalThis.fetch;
    globalThis.fetch = vi.fn((input: RequestInfo | URL) => String(input) === "/api/me"
      ? new Promise<Response>((r) => { answerMe = () => r({ status: 401, json: async () => ({}) } as Response); })
      : served(input)) as typeof fetch;
    window.history.replaceState(null, "", "/?code=WXYZ");
    await renderApp();
    // this page has read storage (empty); another tab now saves its own fill
    localStorage.setItem("shengji.name", "Other Tab");
    await act(async () => { answerMe(); });
    await settle();
    say(seats("WXYZ"));
    await settle();
    const chipName = q(".guest-pill .account-pill-name")?.textContent;
    expect(chipName).toBeTruthy();
    expect(chipName).not.toBe("Guest");
    expect(chipName).not.toBe("Other Tab");
    click(button("Join", joinPanel()!));
    expect(lastSent()).toMatchObject({ type: "table_join", code: "WXYZ", expect: "room", name: chipName });
    expect(localStorage.getItem("shengji.name")).toBe(chipName);
  });

  it("an older ?party= link is a ?code= link: a Duo's table code opens its Join panel", async () => {
    window.history.replaceState(null, "", "/?party=4n5z");
    await renderApp();
    expect(lastSent()).toEqual({ type: "table_peek", code: "4N5Z" });
    expect(q(".q-sheet")).toBeNull();
    await settle();
    expect(joinPanel()?.querySelector(".tp-title")?.textContent).toBe("Join 4N5Z");
    say({ type: "room_seats", room: "4N5Z", table: true, mode: "ranked", in_game: false, allow_joiners: true,
          full: false, closed: false,
          seats: [0, 1, 2, 3].map((seat) => ({ seat, team: seat % 2, state: seat === 0 ? "taken" : seat === 2 ? "held" : "open",
                                               name: seat ? null : "Ann", ready: false })) });
    await settle();
    expect(sentTypes()).not.toContain("table_join");
    // the Duo's held seat is yours, glowing
    expect(joinPanel()?.querySelector(".tp-seat.you.picked")).not.toBeNull();
    click(button("Join", joinPanel()!));
    expect(lastSent()).toEqual({ type: "table_join", code: "4N5Z", name: expect.any(String) });
    expect(sentTypes()).not.toContain("party_join");
  });

  it("an older ?party= link whose code no table has says so", async () => {
    window.history.replaceState(null, "", "/?party=7F2K");
    await renderApp();
    say(MISS("7F2K"));
    await settle();
    expect(q(".toast")?.textContent).toBe("No table has that code.");
    expect(sentTypes()).not.toContain("party_join");
  });

  it("a ?code= link that names nothing says so", async () => {
    window.history.replaceState(null, "", "/?code=ZZZZ");
    await renderApp();
    say(MISS("ZZZZ"));
    await settle();
    expect(q(".toast")?.textContent).toBe("No table has that code.");
    expect(window.location.search).toBe("");
  });

  it("share links are ?code= links", async () => {
    Object.defineProperty(navigator, "share", { configurable: true, value: undefined });
    await renderApp();
    click(button("Duo"));
    say(queued({ duo: true, held_seat: 2, code: "4N5Z", opener: true }));
    click(panel()!.querySelector<HTMLButtonElement>("button.tp-invite"));
    await settle();
    expect(clipboard).toEqual([`${window.location.origin}/?code=4N5Z`]);
    expect(panel()!.querySelector("button.tp-invite")?.textContent).toBe("4N5ZLink copied");
  });

  it("a Duo opener's Invite asks for a partner, the link after the message", async () => {
    const shared: unknown[] = [];
    Object.defineProperty(navigator, "share", { configurable: true,
      value: (d: unknown) => { shared.push(d); return Promise.resolve(); } });
    await renderApp();
    click(button("Duo"));
    say(queued({ duo: true, held_seat: 2, code: "4N5Z", opener: true }));
    click(panel()!.querySelector<HTMLButtonElement>("button.tp-invite"));
    await settle();
    Object.defineProperty(navigator, "share", { configurable: true, value: undefined });
    expect(shared).toEqual([{ title: "Sheng Ji", text: "Be my partner for Tractor? Code 4N5Z",
                              url: `${window.location.origin}/?code=4N5Z` }]);
  });
});

describe("a code peek that is interrupted or refused", () => {
  const typeInto = (input: HTMLInputElement, value: string) => {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
    act(() => { setter.call(input, value); input.dispatchEvent(new Event("input", { bubbles: true })); });
  };
  const peeks = () => FakeWS.all.flatMap((w) => w.sent).filter((m) => m.type === "table_peek");
  const LIMITED = { type: "error", code: "room_not_found", peek: "WXYZ", message: "Too many requests; wait a minute." };
  const reconnect = () => {
    fakeClock();
    act(() => ws().close());
    tick(600);                 // the reconnect backoff
    act(() => ws().onopen?.());
    vi.useRealTimers();
  };

  it("a ?code= link whose peek died with the socket is asked once more, its panel up, and Join waits for it", async () => {
    signedIn = false;
    window.history.replaceState(null, "", "/?code=WXYZ");
    await renderApp();
    expect(peeks()).toHaveLength(1);
    reconnect();
    await settle();
    expect(peeks()).toHaveLength(2);
    expect(ws().sent).toEqual([{ type: "table_peek", code: "WXYZ" }]);
    expect(button("Join", q(".tp-join-code")!)?.disabled).toBe(true);
    say({ type: "room_seats", room: "WXYZ", in_game: false, seats: [] });
    await settle();
    expect(button("Join", q(".tp-join-code")!)?.disabled).toBe(false);
  });

  it("a ?code= link already answered and opened is not peeked or opened again on reconnect", async () => {
    signedIn = false;
    window.history.replaceState(null, "", "/?code=WXYZ");
    await renderApp();
    expect(peeks()).toHaveLength(1);
    say({ type: "room_seats", room: "WXYZ", in_game: false, seats: [] });
    await settle();
    reconnect();
    await settle();
    expect(peeks()).toHaveLength(1);
    expect(sentTypes()).not.toContain("table_join");
  });

  it("a rate-limited Play peek says so, and the box is free again", async () => {
    await renderApp();
    typeInto(q("input[aria-label='Table code']") as HTMLInputElement, "WXYZ");
    click(button(/^Join$/, q(".join-row")!));
    say(LIMITED);
    expect(q(".toast")?.textContent).toBe("Too many requests; wait a minute.");
    expect(button(/^Join$/, q(".join-row")!)?.disabled).toBe(false);
  });

  it("a rate-limited ?code= peek says so", async () => {
    window.history.replaceState(null, "", "/?code=WXYZ");
    await renderApp();
    say(LIMITED);
    await settle();
    expect(q(".toast")?.textContent).toBe("Too many requests; wait a minute.");
  });

  it("an unrelated error while a peek waits does not cancel it", async () => {
    await renderApp();
    typeInto(q("input[aria-label='Table code']") as HTMLInputElement, "WXYZ");
    click(button(/^Join$/, q(".join-row")!));
    say({ type: "error", code: "room_full", message: "Room is full." });
    say({ type: "room_seats", room: "WXYZ", in_game: false, seats: [] });
    await settle();
    expect(q(".tp-join-code")).not.toBeNull();
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
    type: "state", room: "OPEN", you: 0, phase: "play", matched: true, opener: 0, allow_joiners: true, joining: [],
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
    expect(ring()?.querySelector(".timer-ring-band")?.getAttribute("style")).toContain("--ring-at: 0s");
    tick(GUARD_MS + 10);
    expect(primary()?.textContent).toBe(`${ring()?.textContent}Join`);
    expect(ring()?.className).not.toContain("low");
    tick(9300);                          // 10 s left
    expect(ring()?.textContent).toBe("10");
    expect(ring()?.className).toContain("low");
    expect(ring()?.querySelector(".timer-ring-band")?.getAttribute("style")).toContain("--ring-at: 0s");
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

  it("the title names the people staying, cut to ten characters; an away seat is open, with no sub-line", async () => {
    await open();
    tell(queued({ offer: offer({ pick: 1, seats: [offerSeat("Mei", false, false), offerSeat("Bot 1", true, true),
                                                  offerSeat("Samantha-Rose", false, false), offerSeat("Li", false, true)] }),
                  bots_paused: true, bots_at: null }));
    expect(panel()?.querySelector(".tp-title")?.textContent).toBe("Join Mei & Samantha-R…");
    // the away seat is an open seat, its "+" alone; only its label says whose it was
    const away = [...panel()!.querySelectorAll(".tp-seat")].find((s) => s.getAttribute("aria-label")?.includes("away"));
    expect(away?.getAttribute("aria-label")).toBe("Open seat, your team, Li is away. Sit here");
    expect(away?.textContent).toBe("+");
    expect(away?.querySelector(".tp-seat-sub")).toBeNull();
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
    expect(q(".toast")?.textContent).toContain("That seat was just taken.");
    expect([...panel()!.querySelectorAll(".tp-seat")].map((s) => s.getAttribute("aria-label")))
      .toContain("Bob, playing, other team");
    expect(panel()!.querySelector(".tp-seat.you")).not.toBeNull();
    expect(primary()?.disabled).toBe(false);
  });

  it("O6: Keep looking; your table comes back, and a re-sent offer shows again", async () => {
    await open();
    tell(queued({ offer: offer(), bots_paused: true, bots_at: null }));
    expect(panel()?.textContent).not.toMatch(/Bots paused/);
    click(button("Keep looking"));
    expect(sentLast()).toEqual({ type: "open_table_wait" });
    tell(queued({ offer: null, open_tables: 1, bots_paused: false, bots_at: nowSecs() + 35 }));
    expect(panel()?.classList.contains("tp-own")).toBe(true);
    expect(ringSecs()).toMatch(/^3[56]$/);
    expect(button(/table has a seat/)).toBeUndefined();   // the panel has no row back
    tell(queued({ offer: offer(), open_tables: 0, bots_paused: true, bots_at: null }));
    expect(panel()?.classList.contains("tp-join")).toBe(true);
    expect(button(/table has a seat/)).toBeUndefined();
  });

  it("on another tab while a table is offered, the pill says Your table and opens Play", async () => {
    await open();
    tell(queued({ offer: offer(), bots_paused: true, bots_at: null }));
    const { openTab } = await import("../home/route");
    act(() => openTab("leaderboard"));
    expect(q(".table-pill")?.textContent).toBe("Your table");
    click(q(".table-pill"));
    expect(panel()?.classList.contains("tp-join")).toBe(true);
  });

  it("on a desktop the offer's seats are the phone's team columns; a green seat is a button", async () => {
    viewport(true);
    await open();
    tell(queued({ offer: offer(), bots_paused: true, bots_at: null }));
    const p = panel()!;
    const cols = () => p.querySelectorAll(".tp-teams .tp-col");
    expect(cols()[0].children[1]?.getAttribute("aria-label")).toBe("You, your team");
    expect(cols()[0].children[0]?.getAttribute("aria-label")).toBe("Jerry, playing, your team");
    const open1 = [...cols()[1].querySelectorAll<HTMLButtonElement>("button.tp-seat")]
      .find((b) => b.getAttribute("aria-label") === "Open seat, other team. Sit here")!;
    expect(open1).toBeDefined();
    click(open1);
    expect(cols()[0].children[1]?.getAttribute("aria-label")).toBe("You, your team");
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
    expect(q(".join-pill .away-pill-text")?.textContent).toBe("Joining after this trick");   // no sub-line
    expect(q(".join-notice")).toBeNull();
    expect(button(/^Play/)).toBeUndefined();
    click(button("Leave", q(".join-pill")!));
    expect(leaveSheetText()).toBe("Leave the game? / Stay until this round ends, or wait 1 minute to play again.");
    expect(sentLast()).not.toEqual({ type: "table_leave" });
    confirmLeave();
    expect(sentLast()).toEqual({ type: "table_leave" });
  });

  it("O2: the table is told once per join, as the toast: next trick then next round", async () => {
    await open();
    tell({ type: "match_started", match_id: "m1", room: "OPEN", rated: true });
    tell(state({ joining: [{ seat: 2, name: "Alice", when: "trick" }] }));
    expect(q(".toast.at-table")?.textContent).toBe("Alice joins next trick");
    expect(q(".toast .toast-dot.team0")).not.toBeNull();
    const { clearToast } = await import("../toast");
    act(() => { clearToast(); });
    // the same join again is no news
    tell(state({ joining: [{ seat: 2, name: "Alice", when: "trick" }] }));
    expect(q(".toast")).toBeNull();
    tell(state({ joining: [{ seat: 2, name: "Alice", when: "round" }] }));
    expect(q(".toast.at-table")?.textContent).toBe("Alice joins next round");
    expect(q(".join-notice")).toBeNull();
  });

  it("O2: a join that went and came back is told again", async () => {
    await open();
    const { clearToast } = await import("../toast");
    tell({ type: "match_started", match_id: "m1", room: "OPEN", rated: true });
    tell(state({ joining: [{ seat: 2, name: "Alice", when: "trick" }] }));
    expect(q(".toast.at-table")?.textContent).toBe("Alice joins next trick");
    act(() => { clearToast(); });
    // Alice took her seat (or left); later the same seat opens to her again
    tell(state({ joining: [] }));
    expect(q(".toast")).toBeNull();
    tell(state({ joining: [{ seat: 2, name: "Alice", when: "trick" }] }));
    expect(q(".toast.at-table")?.textContent).toBe("Alice joins next trick");
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
    expect(sentLast()).toEqual({ type: "table_allow_joiners", on: false });
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
    typeInto(q("input[aria-label='Table code']") as HTMLInputElement, "rank");
    click(button(/^Join$/, q(".join-row")!));
    expect(lastSent()).toEqual({ type: "table_peek", code: "RANK" });
  };

  const joinInPanel = () => click(button("Join", q(".tp-join-code")!));

  it("signed in: the panel chooses you a bot's seat, and Join names it", async () => {
    await open();
    viaPlayBox();
    tell(rankedSeats());
    expect(document.body.textContent).not.toContain("Take a seat");
    joinInPanel();
    expect(lastSent()).toMatchObject({ type: "table_join", code: "RANK", expect: "room", seat: 1 });
  });

  it("a guest takes a ranked table's seat as an account does", async () => {
    signedIn = false;
    await open();
    viaPlayBox();
    tell(rankedSeats());
    expect(q(".ranked-gate")).toBeNull();
    joinInPanel();
    expect(lastSent()).toMatchObject({ type: "table_join", code: "RANK", expect: "room" });
  });

  it("same_device shows the server's message", async () => {
    await open();
    viaPlayBox();
    tell(rankedSeats());
    joinInPanel();
    tell({ type: "error", code: "same_device", message: "Someone on this device is already at that table." });
    expect(document.body.textContent).toContain("Someone on this device is already at that table.");
  });

  it("a ranked table with no bot seat shows its Join panel with Join disabled", async () => {
    await open();
    viaPlayBox();
    tell(rankedSeats(true));
    await settle();
    const p = q(".tp-join-code")!;
    expect(p.querySelector(".tp-title")?.textContent).toBe("Join Host");
    expect(p.querySelector(".tp-line")?.textContent).toBe("Table is full");
    expect(button("Join", p)?.disabled).toBe(true);
    expect(q(".ranked-gate")).toBeNull();
    expect(sentTypes()).not.toContain("table_join");
    click(button("Not now", p));
    expect(q(".tp-join-code")).toBeNull();
    expect(q("button.play-main")).not.toBeNull();
  });

  it("a ranked table's menu has both Copy invite link and Allow joiners", async () => {
    await open();
    tell({ type: "match_started", match_id: "m1", room: "RANK", rated: true });
    tell({
      type: "state", room: "RANK", you: 0, phase: "play", matched: true, opener: 0, allow_joiners: false, joining: [],
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
    expect(rows).toContain("Invite link");
    expect(rows).toContain("Allow joiners");
    expect(q(".joiners-row")?.getAttribute("aria-checked")).toBe("false");
  });

  it("a created ranked table's menu has Allow joiners too", async () => {
    await open();
    tell({
      type: "state", room: "RANK", you: 0, phase: "play", ranked: true, opener: 0, allow_joiners: true, joining: [],
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
    expect(rows).toContain("Allow joiners");
    expect(q(".joiners-row")?.getAttribute("aria-checked")).toBe("true");
  });

  it("a Duo's offer: Join, both partner seats fixed, no lines", async () => {
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
    expect(join.textContent).toMatch(/^(9|10)Join$/);
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
      expect(q(".toast")?.textContent).toContain("Couldn't open a table.");
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
    expect(q(".toast")).toBeNull();
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
    expect(q(".toast")?.textContent).toContain("You're no longer at a table.");
    expect(q(".toast")?.textContent).toContain("Press Play to find one.");
  });

  it.each([true, false])("an elsewhere-held table can be reclaimed with leader=%s", async (leader) => {
    await renderApp();
    say({ type: "queue_state", queued: true, elsewhere: true, count: 2, since: nowSecs(), leader,
          table: null, offer: null });
    expect(panel()?.querySelector(".tp-title")?.textContent).toBe("Your table is open on another device.");
    expect(q(".q-find")).toBeNull();
    await pastGuard();
    expect(Boolean(button("Leave", panel()!))).toBe(leader);
    click(button("I’m back", panel()!));
    expect(lastSent()).toEqual({ type: "queue_join", mode: "ranked" });
    say({ type: "queue_state", queued: false, count: 1 });
    expect(panel()).toBeNull();
    expect(q(".toast")).toBeNull();
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
    click(q(".hud-more-btn"));
    click(q(".hud-menu-row.leave"));
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

  it("a cooldown refusal is told once (the toast), and Play counts it down", async () => {
    await renderApp();
    click(findBtn());
    say({ type: "error", code: "cooldown", message: "You left a table you joined. Play again in 4:59.",
          cooldown_until: nowSecs() + 299 });
    expect(q(".toast")?.textContent).toBe("You left a table you joined. Play again in 4:59.");
    expect(document.body.textContent?.match(/You left a table you joined/g)?.length).toBe(1);
    expect(findBtn().textContent).toBe("Play in 4:59");
  });

  it("leaving a round joined from an open table: a 1-minute wait", async () => {
    await renderApp();
    say({ type: "match_started", match_id: null, room: "OPEN", rated: true, joining: true, seat: 2 });
    say(state({ joining_you: true }));
    say(state());
    expect(leaveAlertText()).toBe(
      "Leave the game? / Stay until this round ends, or wait 1 minute to play again.");
    // the round over, the next one is an ordinary ranked round
    say(state({ phase: "round_end" }));
    say(state({ phase: "deal" }));
    expect(leaveAlertText()).toBe(
      "Leave the game? / This round counts as at best a draw.");
  });

  it("after a reload, state frames alone (no match_started) carry the joined round's warning", async () => {
    // a fresh module load is a reload: the client never saw this seat's match_started
    await renderApp();
    say(state({ joined_round: true }));
    expect(leaveAlertText()).toBe(
      "Leave the game? / Stay until this round ends, or wait 1 minute to play again.");
    // the server omits the flag once the round is over; the round end clears it
    say(state({ phase: "round_end" }));
    say(state({ phase: "deal" }));
    expect(leaveAlertText()).toBe(
      "Leave the game? / This round counts as at best a draw.");
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
      "Leave the game? / This round counts as at best a draw.");
  });

  it("after a reconnect, the new socket's joined_round frame keeps the joined round's warning", async () => {
    await renderApp();
    const first = ws();
    say(state({ joined_round: true }));
    act(() => first.close());
    await act(async () => { await new Promise((r) => setTimeout(r, 1600)); });
    expect(ws()).not.toBe(first);
    say(state({ joined_round: true }));
    expect(leaveAlertText()).toMatch(/Stay until this round ends, or wait 1 minute to play again/);
  });

  it("a seat taken at a round end, or a server flag saying otherwise, gets the ranked warning", async () => {
    await renderApp();
    say({ type: "match_started", match_id: null, room: "OPEN", rated: true, joining: true, seat: 2 });
    say(state({ joining_you: true, phase: "round_end" }));
    say(state({ phase: "round_end" }));
    say(state({ phase: "deal" }));
    expect(leaveAlertText()).toMatch(/at best a draw\.$/);
    say({ type: "match_started", match_id: null, room: "OPEN", rated: true, joining: true, seat: 2 });
    say(state({ joined_round: false }));
    expect(leaveAlertText()).toMatch(/at best a draw\.$/);
    say(state({ joined_round: true }));
    expect(leaveAlertText()).toMatch(/wait 1 minute to play again/);
  });

  it("Leave table on another device: the holder says the table was closed there", async () => {
    await renderApp();
    say(queued());
    say({ type: "queue_state", queued: false, count: 0, replaced: true, by: "device", stopped: true });
    expect(q(".toast")?.textContent).toContain("Your table was closed from another device.");
    expect(q(".toast")?.textContent).not.toContain("window");
    say(queued());
    say({ type: "queue_state", queued: false, count: 0, replaced: true, by: "window" });
    expect(q(".toast")?.textContent).toContain("Your table moved to another window.");
  });

  it("a guest is never called ranked: search, table, Duo table, offer and the table's top bar", async () => {
    signedIn = false;
    await renderApp();
    say(queued({ duo: true, held_seat: 2, code: "4N5Z" }));
    expect(panel()?.textContent).not.toMatch(/ranked/i);
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
    act(() => q(".hud-more-btn")!.click());
    expect(q(".table-screen .hud-menu")).not.toBeNull();
    expect(q(".table-screen .hud-menu-mode")).toBeNull();
    // a table that is not rated at all sends no guest flag: still no Ranked for a signed-out player
    say(state());
    expect(q(".table-screen .hud-menu-mode")?.textContent ?? "").not.toBe("Ranked");
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
    expect(presence()?.textContent).toBe("2 ranked tables have a seat · 3 playing");
    say({ type: "presence", tables: 1, playing: 1, waiting: 0, ranked: 0, casual: 1 });
    expect(presence()?.textContent).toBe("1 casual table has a seat · 1 playing");
    say({ type: "presence", tables: 3, playing: 5, waiting: 0, ranked: 2, casual: 1 });
    expect(presence()?.textContent).toBe("3 tables have a seat · 2 ranked, 1 casual · 5 playing");
    expect(presence()?.querySelector(".play-presence-hl")?.textContent).toBe("2 ranked");
    say({ type: "presence", tables: 1, playing: 1, waiting: 1, ranked: 1, casual: 0 });
    expect(presence()?.textContent).toBe("1 person is waiting for a game");
    say({ type: "presence", tables: 0, playing: 0, waiting: 3, ranked: 0, casual: 0 });
    expect(presence()?.textContent).toBe("3 people are waiting for a game");
    // an older server sends no split
    say({ type: "presence", tables: 2, playing: 4, waiting: 0 });
    expect(presence()?.textContent).toBe("2 tables have a seat · 4 playing");
    say({ type: "presence", tables: 0, playing: 0, waiting: 0 });
    expect(presence()?.textContent).toBe("Nobody is playing right now");
    // the panel takes Play's place, and the line with it
    say(queued());
    expect(presence()).toBeNull();
  });

  it("the presence line splits by mode only when both have tables, the selected mode's count lit", async () => {
    await renderApp();
    say({ type: "presence", tables: 2, playing: 3, waiting: 0, ranked: 1, casual: 1 });
    expect(presence()?.textContent).toBe("2 tables have a seat · 1 ranked, 1 casual · 3 playing");
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
    expect(presence()?.textContent).toBe("1 ranked table has a seat · 2 playing");
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
    act(() => { vi.advanceTimersByTime(1000); });
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

  it("a queue table's panel has no mode tag: the Ranked / Casual switch above it says the mode", async () => {
    await renderApp();
    say(queued({ mode: "casual" }));
    expect(panel()!.querySelector(".tp-tag")).toBeNull();
    expect(q(".play-mode-opt.on")?.textContent).toBe("Casual");
    expect(panel()!.firstElementChild?.className).toBe("tp-title");
    say(atTable([seat("Jerry", { you: true }), seat("Alice"), null, null], {}, { mode: "casual" }));
    expect(panel()!.querySelector(".tp-tag")).toBeNull();
    expect(q(".play-mode-opt.on")?.textContent).toBe("Casual");
    say(atTable([seat("Jerry", { you: true }), seat("Alice"), null, null], {}, { mode: "ranked" }));
    expect(panel()!.querySelector(".tp-tag")).toBeNull();
    say(queued({ mode: "ranked" }));
    expect(panel()!.querySelector(".tp-tag")).toBeNull();
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
    const open = [...p.querySelectorAll<HTMLButtonElement>("button.tp-seat.open")];
    expect(open.map((b) => b.getAttribute("aria-label")))
      .toEqual(["Open seat, your team. Move here", "Open seat, other team. Move here"]);
    click(open[1]);
    expect(lastSent()).toEqual({ type: "table_move", seat: 3 });
    // seat refusals in a few words
    say({ type: "error", code: "seat_taken", message: "That seat was just taken. Pick another." });
    expect(q(".toast")?.textContent).toBe("That seat was just taken.Pick another.");
    say({ type: "error", code: "already_ready", message: "You tapped Ready, so your seat is set." });
    expect(q(".toast")?.textContent).toBe("You tapped Ready, so your seat is set.");
    say({ type: "error", code: "pair_seats_fixed", message: "A Duo's seats stay together." });
    expect(q(".toast")?.textContent).toBe("A Duo's seats stay together.");
    // after your Start your seat is set: no open seat buttons (the opener
    // may still move Alice)
    say(atTable([seat("Jerry", { you: true, ready: true }), seat("Alice"), null, null]));
    expect(panel()!.querySelector(".tp-hint")).toBeNull();
    expect(panel()!.querySelector("button.tp-seat.open")).toBeNull();
  });

  it("a Duo's seats never move", async () => {
    await renderApp();
    say(atTable([seat("Jerry", { you: true, pair: true }), seat("Li"), seat("Kai", { pair: true }), null],
                {}, { party_id: "p1" }));
    expect(panel()!.querySelector(".tp-hint")).toBeNull();
    expect(panel()!.querySelector("button.tp-seat.open")).toBeNull();
    // the partner's seat is never a button; the opener may still pick Li
    expect([...panel()!.querySelectorAll("button.tp-seat")].map((b) => b.getAttribute("aria-label")))
      .toEqual(["Li, other team. Move"]);
  });

  it("table_moved tells the table which team the mover joined", async () => {
    await renderApp();
    say(atTable([seat("Jerry", { you: true }), null, seat("Alice"), null]));
    say({ type: "table_moved", name: "Alice", seat: 2, your_team: true });
    expect(q(".toast")?.textContent).toBe("Alice moved to your team.");
    expect(q(".toast")?.getAttribute("role")).toBe("status");
    say({ type: "table_moved", name: "Alice", seat: 1, your_team: false });
    expect(q(".toast")?.textContent).toBe("Alice moved to the other team.");
  });

  it("still here?: a countdown and I’m back; the automatic check is not an answer", async () => {
    await renderApp();
    fakeClock();
    const table = [seat("Jerry", { you: true }), seat("Alice"), null, null];
    say(atTable(table, {}, { still_here_until: nowSecs() + 30 }));
    const p = panel()!;
    expect(lines()).toEqual(["You leave the table in 0:30."]);
    expect(p.querySelector(".tp-line.warn")?.textContent).toBe("You leave the table in 0:30.");
    expect(p.querySelector(".tp-hint")).toBeNull();
    expect(live()?.textContent).toBe("Tap I’m back to stay at the table.");
    tick(GUARD_MS + 10);
    expect(primary()?.textContent).toBe("I’m back");
    tick(15_000);
    expect(lines()).toEqual(["You leave the table in 0:15."]);
    // the periodic check went out, and the prompt is still up
    expect(sentOf("queue_status").length).toBeGreaterThan(0);
    expect(sentOf("table_here")).toHaveLength(0);
    expect(primary()?.textContent).toBe("I’m back");
    click(primary());
    expect(lastSent()).toEqual({ type: "table_here" });
    say(atTable([seat("Jerry", { you: true }), seat("Alice", { ready: true }), null, null], {},
                { still_here_until: null }));
    expect(lines()).toEqual(["1 of 1 ready"]);
    // Start takes the place under a fresh guard: a second tap cannot start
    expect(primary()?.textContent).toBe("Start with bots");
    expect(primary()?.disabled).toBe(true);
    tick(GUARD_MS + 10);
    expect(primary()?.disabled).toBe(false);
  });

  it("still here?: any tap or key on the page counts as I’m back, once; a lone modifier does not", async () => {
    await renderApp();
    const table = [seat("Jerry", { you: true }), seat("Alice"), null, null];
    say(atTable(table, {}, { still_here_until: nowSecs() + 30 }));
    act(() => { document.dispatchEvent(new KeyboardEvent("keydown", { key: "Shift" })); });
    expect(sentOf("table_here")).toHaveLength(0);
    act(() => { document.body.dispatchEvent(new MouseEvent("pointerdown", { bubbles: true })); });
    expect(sentOf("table_here")).toHaveLength(1);
    act(() => { document.dispatchEvent(new KeyboardEvent("keydown", { key: "a" })); });
    expect(sentOf("table_here")).toHaveLength(1);
    // with no prompt up, a tap sends nothing
    say(atTable(table, {}, { still_here_until: null }));
    act(() => { document.body.dispatchEvent(new MouseEvent("pointerdown", { bubbles: true })); });
    expect(sentOf("table_here")).toHaveLength(1);
  });

  it("panel_seq goes back with Start with bots, Start and Join; panel_changed refreshes quietly", async () => {
    await renderApp();
    say(queued({ panel_seq: 7 }));
    await pastGuard();
    click(primary());
    expect(lastSent()).toEqual({ type: "table_start_bots", panel_seq: 7 });
    const before = sentOf("queue_status").length;
    say({ type: "error", code: "panel_changed", message: "Your table changed. Look again before you tap." });
    expect(q(".toast")).toBeNull();
    expect(sentOf("queue_status").length).toBe(before + 1);
    expect(words(primary()!)).toBe("Start with bots");
    say(atTable([seat("Jerry"), seat("Alice", { you: true }), null, null], { you: 1 }, { panel_seq: 8, opener: false }));
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

  it("account_in_game with a room on this device: the message in Play's place and I’m back", async () => {
    await renderApp();
    localStorage.setItem("shengji.room", "GAME");
    await pastGuard();
    click(findBtn());
    say({ type: "error", code: "account_in_game", message: "You are already in a game on another device." });
    expect(q(".play-in-game-line")?.textContent).toBe("You are already in a game on another device.");
    expect(document.body.textContent?.match(/already in a game/g)?.length).toBe(1);   // no toast as well
    expect(q(".q-find")).toBeNull();
    click(button("I’m back"));
    expect(lastSent()).toMatchObject({ type: "table_join", code: "GAME", expect: "room" });
    expect(findBtn().textContent).toBe("Play");
  });

  it("account_in_game with no room to go back to: just the message, and OK puts Play back", async () => {
    await renderApp();
    await pastGuard();
    click(findBtn());
    say({ type: "error", code: "account_in_game", message: "You are already in a game on another device." });
    expect(q(".play-in-game-line")?.textContent).toBe("You are already in a game on another device.");
    expect(button("I’m back")).toBeUndefined();
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
    expect(button("I’m back")).toBeUndefined();
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


describe("deferred mock items: take back a Ready, the opener moves people", () => {
  it("a Ready is taken back with one more tap: Waiting for Alice sends table_start off, then Ready shows again", async () => {
    await renderApp();
    say(atTable([seat("Jerry", { you: true }), seat("Alice"), seat("Li"), null], {}, { opener: false }));
    await pastGuard();
    click(primary());
    expect(lastSent()).toEqual({ type: "table_start" });
    say(atTable([seat("Jerry", { you: true, ready: true }), seat("Alice"), seat("Li", { ready: true }), null], {},
                { opener: false }));
    expect(words(primary()!)).toBe("Waiting for Alice");
    expect(lines()).toEqual(["2 of 2 ready"]);
    expect(primary()!.className).toContain("waiting");
    click(primary());
    expect(lastSent()).toEqual({ type: "table_start", on: false });
    say(atTable([seat("Jerry", { you: true }), seat("Alice"), seat("Li", { ready: true }), null], {}, { opener: false }));
    expect(words(primary()!)).toBe("Ready");
    expect(lines()).toEqual(["1 of 2 ready"]);
    expect(primary()!.className).not.toContain("waiting");
  });

  it("only the opener taps a person, then a seat, then confirms once: table_move with from", async () => {
    await renderApp();
    say(atTable([seat("Jerry", { you: true }), seat("Alice"), seat("Li"), null]));
    await pastGuard();
    const alice = () => [...panel()!.querySelectorAll<HTMLButtonElement>("button.tp-seat")]
      .find((b) => b.getAttribute("aria-label")?.startsWith("Alice"))!;
    expect(alice().getAttribute("aria-label")).toBe("Alice, other team. Move");
    expect(alice().getAttribute("aria-pressed")).toBe("false");
    click(alice());
    expect(alice().getAttribute("aria-pressed")).toBe("true");
    expect(alice().className).toContain("picked");
    // the empty seat is now where Alice goes; nothing is sent yet
    const before = lastSent();
    const dest = panel()!.querySelector<HTMLButtonElement>("button.tp-seat.open")!;
    expect(dest.getAttribute("aria-label")).toBe("Open seat, other team. Move Alice here");
    click(dest);
    expect(lastSent()).toBe(before);
    const dialog = q("[role='alertdialog']")!;
    expect(dialog.querySelector("h2")?.textContent).toBe("Move Alice here?");
    expect(buttons(dialog).map((b) => b.textContent)).toEqual(["Cancel", "Move"]);
    click(button("Cancel", dialog));
    expect(q("[role='alertdialog']")).toBeNull();
    expect(lastSent()).toBe(before);
    click(panel()!.querySelector<HTMLButtonElement>("button.tp-seat.open"));
    click(button("Move", q("[role='alertdialog']")!));
    expect(lastSent()).toEqual({ type: "table_move", seat: 3, from: 1, who: "sit-Alice" });
    expect(q("[role='alertdialog']")).toBeNull();
    // a second tap on the picked person drops the pick
    click(alice());
    click(alice());
    expect(alice().getAttribute("aria-pressed")).toBe("false");
    // anyone else at the table sees people, not buttons
    say(atTable([seat("Jerry"), seat("Alice", { you: true }), seat("Li"), null], { you: 1 }, { opener: false }));
    expect([...panel()!.querySelectorAll("button.tp-seat")].map((b) => b.getAttribute("aria-label")))
      .toEqual(["Open seat, your team. Move here"]);
  });

  it("a new sitting in the picked seat drops the pick and its confirm, even under the same name", async () => {
    await renderApp();
    say(atTable([seat("Jerry", { you: true }), seat("Alice"), seat("Li"), null]));
    await pastGuard();
    const alice = () => [...panel()!.querySelectorAll<HTMLButtonElement>("button.tp-seat")]
      .find((b) => b.getAttribute("aria-label")?.startsWith("Alice"))!;
    click(alice());
    click(panel()!.querySelector<HTMLButtonElement>("button.tp-seat.open"));
    expect(q("[role='alertdialog']")).not.toBeNull();
    const before = lastSent();
    // Alice left and another "Alice" sat down before Move was tapped
    say(atTable([seat("Jerry", { you: true }), seat("Alice", { sit: "sit-Alice-2" }), seat("Li"), null]));
    expect(q("[role='alertdialog']")).toBeNull();
    expect(alice().getAttribute("aria-pressed")).toBe("false");
    expect(lastSent()).toBe(before);
    // a fresh pick sends the new sitting
    click(alice());
    click(panel()!.querySelector<HTMLButtonElement>("button.tp-seat.open"));
    click(button("Move", q("[role='alertdialog']")!));
    expect(lastSent()).toEqual({ type: "table_move", seat: 3, from: 1, who: "sit-Alice-2" });
  });

  it("a held seat is never a destination and a Duo goes only to a whole free team", async () => {
    const { moveTargets } = await import("./tableText");
    expect(moveTargets([{}, { pair: true }, null, { pair: true }], [], 1)).toEqual([]);
    expect(moveTargets([null, { pair: true }, null, { pair: true }], [], 3)).toEqual([0, 2]);
    expect(moveTargets([{}, {}, null, null], [2], 1)).toEqual([3]);
    await renderApp();
    say(atTable([seat("Jerry", { you: true }), seat("Alice"), null, seat("Li")], { held_seats: [2], held_seat: 2 }));
    await pastGuard();
    click([...panel()!.querySelectorAll<HTMLButtonElement>("button.tp-seat")].find((b) => b.getAttribute("aria-label")?.startsWith("Alice")));
    expect(panel()!.querySelector("button.tp-seat.open, button.tp-seat.held")).toBeNull();
    expect(panel()!.querySelector(".tp-seat.held")?.getAttribute("aria-label")).toBe("Partner seat, held for your friend");
  });

  it("the one moved hears it through the one toast", async () => {
    await renderApp();
    say(atTable([seat("Jerry"), null, null, seat("Alice", { you: true })], { you: 3 }, { opener: false }));
    say({ type: "table_moved", name: "Alice", seat: 3, your_team: true, by: "Jerry", you: true, team_changed: true });
    expect(q(".toast")?.textContent).toBe("Jerry moved you to the other team.");
    say({ type: "table_moved", name: "Alice", seat: 1, your_team: true, by: "Jerry", you: true, team_changed: false });
    expect(q(".toast")?.textContent).toBe("Jerry moved your seat.");
    say({ type: "table_moved", name: "Li", seat: 1, your_team: false, by: "Jerry" });
    expect(q(".toast")?.textContent).toBe("Jerry moved Li to the other team.");
  });
});

describe("the table frame is the table", () => {
  /** One frame as the socket sends it, with no table frame added. */
  const raw = (msg: unknown) => act(() => ws().onmessage?.({ data: JSON.stringify(msg) }));
  const title = () => panel()?.querySelector(".tp-title")?.textContent ?? null;

  /** The share sheet's text after a tap on Invite, for frames as the server sent them. */
  async function shareFrom(...frames: unknown[]): Promise<string[]> {
    const shared: { text: string }[] = [];
    Object.defineProperty(navigator, "share", { configurable: true,
      value: (d: { text: string }) => { shared.push(d); return Promise.resolve(); } });
    try {
      await renderApp();
      for (const f of frames) raw(f);
      click(panel()!.querySelector<HTMLButtonElement>("button.tp-invite"));
      await settle();
    } finally {
      Object.defineProperty(navigator, "share", { configurable: true, value: undefined });
    }
    return shared.map((d) => d.text);
  }

  // The server's own frames (server/tests/test_table_frame.py): a Duo table, its
  // partner seat (2) held, with the opener at seat 0 and a stranger at seat 1.
  const duoPair = (you: number) => SERVER_FRAMES.find((p) =>
    p.scenario === "a_duo_partner_leaving_holds_the_seat_again" && p.table.you === you
    && p.table.seats.map((s) => s.state).join() === "taken,taken,held,open")!;

  it("a stranger at a Duo table shares the table's code with the plain ask: that code takes the held seat", async () => {
    const p = duoPair(1);
    expect(p.table.opener).toBe(0);
    const code = p.table.code;
    expect(await shareFrom(p.queue_state, p.table)).toEqual([`Play Tractor with me? Code ${code}`]);
  });

  it("the Duo opener shares the same code asking for a partner", async () => {
    const p = duoPair(0);
    expect(p.table.code).toBe(duoPair(1).table.code);
    expect(await shareFrom(p.queue_state, p.table)).toEqual([`Be my partner for Tractor? Code ${p.table.code}`]);
  });

  it("the panel draws the table frame, never queue_state's own copy of the table", async () => {
    await renderApp();
    const state = atTable([seat("Jerry", { you: true }), seat("Alice"), null, null], { code: "4N5Z" },
                          { code: "4N5Z", mode: "ranked", allow_joiners: true, start_level: "2", opener: true });
    // queue_state's copy says something else: Ghost sits there, under another code
    const table = (state as unknown as { table: Record<string, unknown> }).table;
    const stale = { ...state, code: "OLD1", table: { ...table, code: "OLD1", seats: [
      seat("Jerry", { you: true }), seat("Ghost"), null, null], ready: 0, of: 2, waiting_for: ["Ghost"] } };
    raw(stale);
    expect(panel()).toBeNull();                     // nothing until its table frame
    raw(tableFrameFor(state));
    expect(title()).toBe("You and Alice");
    expect(panel()!.querySelector(".tp-code")?.textContent).toBe("4N5Z");
    expect(panel()!.textContent).not.toContain("Ghost");
  });

  it("alone, your own table's seats come from the frame: a lone queue_state draws nothing", async () => {
    await renderApp();
    raw(queued({ duo: true, held_seat: 2, code: "4N5Z", opener: true }));
    expect(panel()).toBeNull();
    // the stash is dropped by the search's end, so a late frame changes nothing
    raw({ type: "queue_state", queued: false, count: 0 });
    raw(tableFrameFor(queued({ duo: true, held_seat: 2, code: "4N5Z", opener: true })));
    expect(panel()).toBeNull();
    say(queued({ duo: true, held_seat: 2, code: "4N5Z", opener: true }));
    expect(title()).toBe("Your Duo");
    expect(panel()!.querySelector(".tp-seat.held")?.getAttribute("aria-label")).toBe("Partner seat, held for your friend");
  });

  it("a game's table frame leaves the queue's panel alone", async () => {
    await renderApp();
    say(atTable([seat("Jerry", { you: true }), seat("Alice"), null, null]));
    raw({ ...tableFrameFor(queued()), phase: "playing" });
    expect(title()).toBe("You and Alice");
  });
});
