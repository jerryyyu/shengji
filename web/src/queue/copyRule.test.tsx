// The copy rule (docs/design/FLOWS.md, "Copy rule"), held on every kind of the
// table panel: a switch or setting row is its label only, a panel carries at
// most one status line, and a countdown is the ring, never clock text.
// copyCuts.test.ts keeps the strings the rule cut out of the source.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { WIDE } from "../home/HomeShell";
import { SHORT_VIEWPORT } from "../phoneLayout";
import { framer } from "./testFrames";

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
const realMatchMedia = window.matchMedia;
const settle = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });

function viewport(wide: boolean) {
  window.matchMedia = ((q: string) => ({
    matches: q === WIDE ? wide : q === SHORT_VIEWPORT ? false : false,
    media: q, addEventListener() {}, removeEventListener() {},
  })) as unknown as typeof window.matchMedia;
}

/** The rule's three checks on one rendered panel; each returns what breaks it. */
const ROWS = "[role='switch'], .tp-switch, .tp-set, .tp-settings, .tp-row, .tp-code-row, .tp-chat";
const SUB_LINE = "small, [class*='-sub']";
const STATUS = ".tp-line, .tp-led, .tp-hint";
const CLOCK = /\d:\d\d/;

function subLines(p: Element): string[] {
  return [...p.querySelectorAll(ROWS)].flatMap((row) =>
    [...row.querySelectorAll(SUB_LINE)].map((s) => `${row.className}: ${s.textContent}`));
}
function statuses(p: Element): string[] {
  return [...p.querySelectorAll(STATUS)].map((s) => s.textContent ?? "");
}
/** Visible text outside the timer rings (and outside screen-reader-only text). */
function clockText(p: Element): string | null {
  const copy = p.cloneNode(true) as Element;
  for (const r of copy.querySelectorAll(".timer-ring, .sr-only")) r.remove();
  return copy.textContent?.match(CLOCK)?.[0] ?? null;
}
function expectCopyRule(p: Element | null, kind: string) {
  expect(p, `the ${kind} panel is on screen`).not.toBeNull();
  expect(subLines(p!), `${kind}: switches and setting rows take a label only, no sub-line`).toEqual([]);
  expect(statuses(p!).length, `${kind}: at most one status line, got ${JSON.stringify(statuses(p!))}`)
    .toBeLessThanOrEqual(1);
  expect(clockText(p!), `${kind}: a countdown is the ring, not clock text`).toBeNull();
}

describe("online panels", () => {
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
  // frames go to every socket opened in this test, as queue.test.tsx does
  const tell = (msg: unknown) => act(() => { for (const w of FakeWS.all) w.deliver(msg); });
  const nowSecs = () => Date.now() / 1000;

  beforeEach(() => {
    FakeWS.all = [];
    localStorage.clear();
    (globalThis as unknown as { WebSocket: unknown }).WebSocket = FakeWS;
    (window as unknown as { AudioContext: unknown }).AudioContext = class {
      state = "running";
      resume() { return Promise.resolve(); }
    };
    Object.defineProperty(Element.prototype, "scrollIntoView", { configurable: true, value: () => {} });
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

  async function renderApp() {
    const { default: App } = await import("../App");
    host = document.createElement("div");
    document.body.appendChild(host);
    root = createRoot(host);
    await act(async () => { root.render(<App />); });
    act(() => { for (const w of FakeWS.all) w.onopen?.(); });
    await settle();
    await settle();
  }

  type Seat = { name: string; you?: boolean; ready?: boolean; since?: number } | null;
  const seat = (name: string, over: Partial<NonNullable<Seat>> = {}) => ({
    name, you: false, ready: false, reconnecting: false, since: nowSecs() - 30, pair: false, leader: true, ...over,
  });
  const queued = (over: Record<string, unknown> = {}) => ({
    type: "queue_state", queued: true, count: 3, since: nowSecs(), front: false, party_id: null,
    leader: true, bots_at: nowSecs() + 60, mode: "ranked", code: "4N5Z", allow_joiners: true,
    start_level: "2", opener: true, ...over,
  });
  const offerSeat = (name: string, bot: boolean, open: boolean) => ({ name, bot, open });

  /** Each panel kind, as the server's frames put it on screen (a code's
   *  Join panel from a link, then its peek's answer). */
  const KINDS: { kind: string; sel: string; frames: () => unknown[]; link?: string }[] = [
    { kind: "join", sel: ".tp-join", frames: () => [queued({
      offer: { room: "OPEN", pick: 2, expires_at: nowSecs() + 20, round_end: false,
               seats: [offerSeat("Mei", false, false), offerSeat("Bot 1", true, true),
                       offerSeat("Bot 2", true, true), offerSeat("Bot 3", true, true)] },
      bots_paused: true, bots_at: null, code: null })] },
    { kind: "own (ranked)", sel: ".tp-own", frames: () => [queued({ count: 1 })] },
    { kind: "own (casual)", sel: ".tp-own", frames: () => [queued({ count: 1, mode: "casual" })] },
    { kind: "own, waiting for people", sel: ".tp-own", frames: () => [queued({ count: 1, wait_players: true, bots_at: null })] },
    { kind: "shared", sel: ".tp-shared", frames: () => [queued(), queued({
      count: 2, opener: false,
      table: { id: "t1", code: "4N5Z", opener: 0, you: 2, timer: { at: nowSecs() + 42, name: "Mei", you: false },
               ready: 0, of: 2, you_ready: false, waiting_for: ["Mei"],
               seats: [seat("Mei"), null, seat("Jerry", { you: true }), null] } })] },
    { kind: "shared, one ready", sel: ".tp-shared", frames: () => [queued(), queued({
      count: 2, opener: true,
      table: { id: "t1", code: "4N5Z", opener: 0, you: 0, timer: null, ready: 1, of: 2, you_ready: true,
               waiting_for: ["Alice"],
               seats: [seat("Jerry", { you: true, ready: true }), seat("Alice"), null, null] } })] },
    { kind: "join-code", sel: ".tp-join-code", link: "/?code=4N5Z", frames: () => [{
      type: "room_seats", room: "4N5Z", table: true, mode: "casual", in_game: false, allow_joiners: true,
      full: true, closed: false,
      seats: ["Mei", "Li", "Sam", "Ana"].map((name, at) => ({ seat: at, team: at % 2, state: "taken", name, ready: false })) }] },
  ];

  for (const wide of [false, true]) {
    for (const { kind, sel, frames, link } of KINDS) {
      it(`${kind}${wide ? ", wide" : ", phone"}: labels only, one status, the ring is the clock`, async () => {
        viewport(wide);
        if (link) window.history.replaceState(null, "", link);
        await renderApp();
        for (const f of frames()) tell(f);
        await settle();
        expectCopyRule(host.querySelector(sel), kind);
        // and with Table settings open, its rows held to the same rule
        const settings = host.querySelector<HTMLButtonElement>(`${sel} .tp-settings`);
        if (settings) {
          act(() => settings.click());
          expect(host.querySelector(`${sel} .tp-settings-body`)).not.toBeNull();
          expectCopyRule(host.querySelector(sel), `${kind}, settings open`);
        }
      });
    }
  }
});

describe("offline panel", () => {
  const realLocation = window.location;
  const realFetch = globalThis.fetch;
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    Object.defineProperty(window, "location", { configurable: true,
      value: { ...realLocation, search: "?offline=1&table=1", protocol: "http:", pathname: "/", assign: vi.fn(), reload: vi.fn() } });
    globalThis.fetch = vi.fn(() => Promise.reject(new Error("no network in this test"))) as typeof fetch;
    (window as unknown as { AudioContext: unknown }).AudioContext = class {
      state = "running";
      resume() { return Promise.resolve(); }
    };
    vi.resetModules();
  });
  afterEach(async () => {
    act(() => root.unmount());
    // The on-device socket opens on the host's timers, which outlive this
    // file's DOM: end the connection, then nothing it started may open.
    const { conn } = await import("../ws");
    conn.stop();
    await vi.dynamicImportSettled();
    await new Promise((r) => setTimeout(r, 0));
    expect(conn.status).toBe("closed");
    host.remove();
    Object.defineProperty(window, "location", { configurable: true, value: realLocation });
    globalThis.fetch = realFetch;
    window.matchMedia = realMatchMedia;
    sessionStorage.clear();
  });

  for (const wide of [false, true]) {
    it(`offline${wide ? ", wide" : ", phone"}: labels only, one status, no clock text`, async () => {
      viewport(wide);
      const { saveName } = await import("../ws");
      saveName("Cheerful Tractor");
      const { default: App } = await import("../App");
      host = document.createElement("div");
      document.body.appendChild(host);
      root = createRoot(host);
      act(() => root.render(<App />));
      const end = Date.now() + 5000;
      while (!host.querySelector(".tp-offline") && Date.now() < end) {
        await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
      }
      expectCopyRule(host.querySelector(".tp-offline"), "offline");
    });
  }
});

/** The copy rule's one listed exception (FLOWS.md "Play nearby"): under the
 *  code box, for a nearby code only, one passive line before iOS has asked
 *  for Local Network access, or after a denial one line with its Settings
 *  link. No other text sits under a control. */
const UNDER_CONTROL_EXCEPTION = {
  where: "the code box (Lobby.tsx NearbyCodeLine)",
  lines: [
    "This is a nearby table. Sheng Ji will ask to use your local network to find it.",
    "Nearby tables need Local Network access. Open Settings",
  ],
};

describe("nearby panels and the code box's one exception", () => {
  beforeEach(() => {
    localStorage.clear();
    host = document.createElement("div");
    document.body.appendChild(host);
    root = createRoot(host);
  });
  afterEach(() => {
    act(() => root.unmount());
    host.remove();
  });

  const room = (over: Record<string, unknown> = {}) => ({
    type: "room" as const, room: "K7Q2M", you: 0, host: 0, start_level: "2" as const,
    players: [{ seat: 0, name: "Jerry", is_bot: false, connected: true }, { seat: 2, name: "Mei", is_bot: false, connected: true }],
    nearby: { ready: [0], bots_in: 42, locked: true }, ...over,
  });

  for (const [kind, r] of [["nearby host", room()], ["nearby joiner", room({ you: 2 })],
                           ["nearby host alone", room({ players: [room().players[0]], nearby: { ready: [], bots_in: null, locked: false } })]] as const) {
    it(`${kind}: labels only, one status, the ring is the clock`, async () => {
      const { NearbyRoomPanel } = await import("../nearbyUi");
      act(() => root.render(<NearbyRoomPanel room={r} onLeave={() => {}} />));
      expectCopyRule(host.querySelector(".tp-offline"), kind);
      expect(host.querySelector(".tp-invite"), "no Invite link offline").toBeNull();
      expect(host.querySelector(".tp-chat"), "no chat at a nearby table").toBeNull();
      expect(!!host.querySelector("[role='switch']"), "only the host has the Nearby switch").toBe(r.you === r.host);
    });
  }

  it("a panel with one setting shows that row itself, not Table settings: Bots offline and at a nearby table", async () => {
    const { OfflinePanel } = await import("./TablePanel");
    const { NearbyRoomPanel } = await import("../nearbyUi");
    const picked: string[] = [];
    act(() => root.render(<OfflinePanel ready starting={false} bots="standard" onBots={(b) => picked.push(b)}
                                        onStart={() => {}} onLeave={() => {}} />));
    expect(host.querySelector(".tp-settings"), "offline: no Table settings row").toBeNull();
    const bots = host.querySelector<HTMLSelectElement>(".tp-offline select[aria-label='Bots']")!;
    expect(bots.value).toBe("standard");
    act(() => { bots.value = "advanced"; bots.dispatchEvent(new Event("change", { bubbles: true })); });
    expect(picked).toEqual(["advanced"]);
    act(() => root.render(<NearbyRoomPanel room={room()} onLeave={() => {}} />));
    expect(host.querySelector(".tp-settings"), "nearby host: no Table settings row").toBeNull();
    expect(host.querySelector(".tp-offline select[aria-label='Bots']"), "the host picks Bots in place").not.toBeNull();
    act(() => root.render(<NearbyRoomPanel room={room({ you: 2 })} onLeave={() => {}} />));
    expect(host.querySelector(".tp-settings"), "nearby joiner: no Table settings row").toBeNull();
    expect(host.querySelector("[role='group'][aria-label='Bots Standard']"), "a joiner reads Bots in place").not.toBeNull();
    expect(host.querySelector("button.tp-invite"), "a nearby code is not a share control").toBeNull();
    expect(host.querySelector(".tp-code")?.textContent).toBe("K7Q2M");
  });

  it("the offline panel's denied line: one status line, its link inside it", async () => {
    const { OfflinePanel } = await import("./TablePanel");
    const { nearbySwitch } = await import("./nearbyModel");
    act(() => root.render(<OfflinePanel ready starting={false} bots="standard" onBots={() => {}} onStart={() => {}} onLeave={() => {}}
                                        nearby={nearbySwitch({ on: false, line: "denied" })} />));
    expectCopyRule(host.querySelector(".tp-offline"), "offline, denied");
    expect(host.querySelector(".tp-line")!.textContent).toBe(UNDER_CONTROL_EXCEPTION.lines[1]);
    expect(host.querySelector(".tp-chat"), "the greyed Chat row while Nearby is off").not.toBeNull();
    expect(host.textContent, "the Bots row while Nearby is off").toContain("Bots");
    act(() => root.render(<OfflinePanel ready starting={false} bots="standard" onBots={() => {}} onStart={() => {}} onLeave={() => {}}
                                        nearby={nearbySwitch({ on: true, line: null })} />));
    expect(host.querySelector(".tp-chat"), "no Chat row while Nearby is on").toBeNull();
    expect(host.textContent, "the Bots row, read-only, while Nearby is on").toContain("Bots");
    expect(host.querySelector("select[aria-label='Bots']"), "picked in the nearby lobby, not here").toBeNull();
  });

  it("the code box's lines are exactly the listed exception", async () => {
    const { CodeRow } = await import("../components/Lobby");
    const nearby = await import("../nearbyUi");
    const lines = () => [...host.querySelectorAll(".join-line")].map((p) => p.textContent);
    act(() => root.render(<CodeRow disabled={false} code="K7Q2" nearby={nearby} />));
    expect(lines(), "an online code: no line").toEqual([]);
    act(() => root.render(<CodeRow disabled={false} code="K7Q2M" nearby={nearby} />));
    expect(lines()).toEqual([UNDER_CONTROL_EXCEPTION.lines[0]]);
    act(() => root.render(<CodeRow disabled={false} code="K7Q2M" nearby={nearby}
                                   nearbyJoinView={{ code: "K7Q2M", step: "denied", peek: null, seat: null }} />));
    expect(lines()).toEqual([UNDER_CONTROL_EXCEPTION.lines[1]]);
    localStorage.setItem("shengji.nearbyAllowed", "1");
    act(() => root.render(<CodeRow disabled={false} code="K7Q2Y" nearby={nearby} />));
    expect(lines(), "once iOS has asked, no line").toEqual([]);
    act(() => root.render(<CodeRow disabled={false} code="K7Q2M" />));
    expect(lines(), "no nearby play: no line, and the box stops at four").toEqual([]);
    expect(host.querySelector("input")!.maxLength).toBe(4);
  });
});
