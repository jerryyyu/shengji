// The copy rule (docs/design/FLOWS.md, "Copy rule"), held on every kind of the
// table panel: a switch or setting row is its label only, a panel carries at
// most one status line, and a countdown is the ring, never clock text.
// copyCuts.test.ts keeps the strings the rule cut out of the source.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { WIDE } from "../home/HomeShell";
import { SHORT_VIEWPORT } from "../phoneLayout";

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
const ROWS = "[role='switch'], .tp-switch, .tp-set, .tp-row, .tp-code-row, .tp-chat";
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
    deliver(msg: unknown) { this.onmessage?.({ data: JSON.stringify(msg) }); }
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

  /** Each panel kind, as the server's frames put it on screen. */
  const KINDS: { kind: string; sel: string; frames: () => unknown[] }[] = [
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
  ];

  for (const wide of [false, true]) {
    for (const { kind, sel, frames } of KINDS) {
      it(`${kind}${wide ? ", wide" : ", phone"}: labels only, one status, the ring is the clock`, async () => {
        viewport(wide);
        await renderApp();
        for (const f of frames()) tell(f);
        await settle();
        expectCopyRule(host.querySelector(sel), kind);
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
  afterEach(() => {
    act(() => root.unmount());
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
