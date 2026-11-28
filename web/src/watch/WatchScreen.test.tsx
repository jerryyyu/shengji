// The watch screen against a real finished round: the tabs, the turn to
// another player, the controls, the kitty peek, and the watcher's round end
// with the caught-up line. Every read is a stubbed fetch of the feed.
import { act } from "react";
import { createRoot } from "react-dom/client";
import type { Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import fixture from "../replay/server-round-finished.fixture.json";
import WatchScreen, { CARD_HOLD_MS, FOLLOW_MS, RETRY_MS } from "./WatchScreen";
import { TO_PLAY_MS, watchUsage } from "./usage";
import { telemetry } from "../telemetry";
import { clearToast, currentToast } from "../toast";
import { watch } from "./store";
import { canWatch } from "./store";
import { forgetWatcherToken } from "./api";
import { setLanguageChoice } from "../i18n";

// a watcher shown the Collection: companions on the felt, no portrait on the round end
vi.mock("../companion/feature", () => ({ useCollection: () => true }));

const joined: string[] = [];
vi.mock("../audio", () => ({ prewarmAudio: () => {}, isMuted: () => true, setMuted: () => {},
  subscribeMuted: () => () => {}, play: () => {}, resetAnnouncer: () => {}, announceState: () => {} }));
vi.mock("../queue/store", () => ({ queue: { setPlayMode: () => {}, join: () => { joined.push("queue"); } } }));
vi.mock("../codeJoin", () => ({ codes: { open: (c: string) => { joined.push(c); return true; } } }));
vi.mock("../roundTelemetry", () => ({ rounds: { noteEntry: () => {} } }));
vi.mock("../ws", () => ({ conn: { send: () => true, subscribe: () => () => {}, subscribeStatus: () => () => {},
  status: "open", generation: 1, chatHistory: () => [] } }));

const banker = (fixture.events.find((e) => e.e === "trump") as { banker: number }).banker;
const names = ((fixture.events[0] as { players: { name: string }[] }).players).map((p) => p.name);
const feed = {
  table: "abc123", watcher: "w".repeat(32), mode: "casual", live_round: 4, code: "CSUL",
  rerun: false, waiting: false, round: 3, seat: banker, players: ["Mei", "Li", "Alice", "Lin"],
  finished: true, events: fixture.events,
};
const urls: string[] = [];
const beacons: string[] = [];
let root: Root;
let host: HTMLDivElement;

beforeEach(() => {
  // jsdom has no modal top layer: the round end's dialog only needs to open
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", { configurable: true,
    value: function (this: HTMLDialogElement) { this.setAttribute("open", ""); } });
  Object.defineProperty(HTMLDialogElement.prototype, "close", { configurable: true,
    value: function (this: HTMLDialogElement) { this.removeAttribute("open"); } });
  urls.length = 0;
  beacons.length = 0;
  sessionStorage.clear();
  forgetWatcherToken();
  Object.defineProperty(navigator, "sendBeacon", { configurable: true,
    value: (url: string) => { beacons.push(url); return true; } });
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    urls.push(url);
    const body = url.startsWith("/api/watch/") ? { ...feed, waiting: true, events: undefined } : feed;
    return new Response(JSON.stringify(body), { status: 200 });
  }));
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

async function open() {
  await act(async () => { root.render(<WatchScreen mode="ranked" />); });
  await act(async () => { await Promise.resolve(); });
}

const tabs = () => [...host.querySelectorAll<HTMLButtonElement>("[role=tab]")];
const button = (label: string) => host.querySelector<HTMLButtonElement>(`button[aria-label="${label}"]`)!;

describe("the watch screen", () => {
  it("asks the feed for the selected mode and lands behind the banker", async () => {
    await open();
    expect(urls[0]).toMatch(/^\/api\/watch\?mode=ranked/);
    expect(tabs()).toHaveLength(4);
    const on = tabs().find((b) => b.getAttribute("aria-selected") === "true")!;
    expect(on.textContent).toContain(names[banker]);
    expect(on.querySelector(".banker-crown")).not.toBeNull();
    // the bury: the banker holds the dealt hand and the kitty
    expect(host.querySelectorAll(".watch-hand .hand-slot, .watch-hand .card").length).toBeGreaterThanOrEqual(33);
  });

  it("a tab turns the table to that player and opens their hand", async () => {
    await open();
    const other = tabs()[1];
    await act(async () => { other.click(); });
    expect(other.getAttribute("aria-selected")).toBe("true");
    // the banker's seat is no longer at the bottom: it is one of the panels round the table
    expect(host.querySelector(`.opponent[data-seat="${banker}"]`)).not.toBeNull();
    expect(host.querySelector(`.opponent[data-seat="${(banker + 1) % 4}"]`)).toBeNull();
  });

  it("has icon controls with names, a speed toggle and no step past the end", async () => {
    await open();
    for (const name of ["Previous trick", "Pause", "Next trick", "Speed 1×"]) expect(button(name)).not.toBeNull();
    await act(async () => { button("Speed 1×").click(); });
    expect(button("Speed 2×")).not.toBeNull();
    expect(localStorage.getItem("shengji.watch.speed")).toBe("2");
    await act(async () => { button("Pause").click(); });
    expect(button("Play").getAttribute("aria-pressed")).toBe("true");
    for (let i = 0; i < 40; i++) await act(async () => { button("Next trick")?.click(); });
    expect(button("Next trick").disabled).toBe(true);
    localStorage.removeItem("shengji.watch.speed");
  });

  it("the kitty peek shows the eight buried cards and closes", async () => {
    await open();
    await act(async () => { button("Pause").click(); });
    await act(async () => { button("Next trick").click(); });
    await act(async () => { button("Kitty").click(); });
    const peek = host.querySelector("[role=dialog]")!;
    expect(peek.querySelectorAll(".card")).toHaveLength(8);
    await act(async () => { button("Close the kitty").click(); });
    expect(host.querySelector(".watch-kitty-peek")).toBeNull();
  });

  it("the round end is the game's card with Take a seat and Leave, and says the next round is in play", async () => {
    await open();
    await act(async () => { button("Pause").click(); });
    for (let i = 0; i < 40; i++) await act(async () => { button("Next trick")?.click(); });
    await act(async () => { await Promise.resolve(); });
    const card = document.querySelector(".round-end")!;
    expect(card).not.toBeNull();
    expect(card.textContent).toContain("Round 4 in play");
    // another table's round end reads nothing of the watcher's account, and draws no portrait
    expect(urls.filter((u) => u.startsWith("/api/me"))).toEqual([]);
    expect(document.querySelector(".portrait")).toBeNull();
    // the companions stay on the felt, the watcher's own among them
    // (WatchCompanions.test.tsx)
    expect(document.querySelector(".table-companions")).not.toBeNull();
    const labels = [...card.querySelectorAll(".round-end-actions button:not(.round-end-view-btn)")].map((b) => b.textContent);
    expect(labels).toEqual(["Take a seat", "Leave"]);
    await act(async () => { (card.querySelectorAll(".round-end-actions button:not(.round-end-view-btn)")[0] as HTMLButtonElement).click(); });
    expect(joined).toContain("CSUL");
    expect(card.textContent).not.toContain("Next round");
    // Details swaps the lanes for the kitty and the last trick, as for a player
    expect(card.querySelector(".round-end-view-btn")).not.toBeNull();
    // caught up: it follows the table for the round after this one
    expect(urls.some((u) => u.startsWith("/api/watch/abc123?after=3"))).toBe(true);
    watch.open("casual");
    await act(async () => { (card.querySelectorAll(".round-end-actions button:not(.round-end-view-btn)")[1] as HTMLButtonElement).click(); });
    expect(watch.get()).toBeNull();
  });
});

describe("a replay", () => {
  const rerun = { ...feed, table: "rerun", rerun: true, live_round: null, code: null, mode: "ranked",
    // seat 1's player is on the leaderboard and keeps their name; the server
    // names everyone else by seat
    players: ["Mei", "Player 2", "Player 3", "Player 4"],
    events: fixture.events.map((e) => (e.e !== "round_start" ? e : {
      ...e, players: (e as { players: { seat: number; is_bot: boolean }[] }).players
        .map((p) => ({ ...p, name: p.seat === 0 ? "Mei" : `Player ${p.seat + 1}` })) })) };
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      urls.push(url);
      return new Response(JSON.stringify(rerun), { status: 200 });
    }));
  });

  it("says Replay in the strip, never a round number", async () => {
    await open();
    const chip = host.querySelector(".watch-round")!;
    expect(chip.textContent).toBe("Replay");
    expect(chip.closest(".hud")).not.toBeNull();
  });

  it("has no menu: the top right is one Leave control", async () => {
    await open();
    expect(host.querySelector("button[aria-label='More']")).toBeNull();
    expect(host.querySelector("[aria-haspopup=menu], [role=menu], [role=menuitem]")).toBeNull();
    const close = host.querySelector<HTMLButtonElement>(".watch-hud .hud-more-btn")!;
    expect(close.getAttribute("aria-label")).toBe("Leave");
    expect(close.querySelector("svg")).not.toBeNull();
  });

  it("one tap on the Leave control leaves at once and walks its history entry back once", async () => {
    window.history.replaceState(null, "", "/");
    watch.open("ranked");
    await open();
    const back = vi.spyOn(window.history, "back");
    const close = vi.spyOn(watch, "close");
    await act(async () => { button("Leave").click(); });
    expect(watch.get()).toBeNull();
    expect(close).toHaveBeenCalledTimes(1);
    expect(back).toHaveBeenCalledTimes(1);
    expect(host.querySelector("[role=menu]")).toBeNull();
    close.mockRestore();
    back.mockRestore();
  });

  it("names the control 离开 and 離開 in Chinese", async () => {
    for (const [choice, label] of [["zh-Hans", "离开"], ["zh-Hant", "離開"]] as const) {
      setLanguageChoice(choice);
      try {
        await open();
        expect(host.querySelector(".watch-hud .hud-more-btn")!.getAttribute("aria-label")).toBe(label);
      } finally {
        setLanguageChoice("system");
      }
    }
  });

  it("keeps a leaderboard player's name and reads the others' seats in the viewer's language", async () => {
    setLanguageChoice("zh-Hans");
    try {
      await open();
      expect(tabs().map((b) => b.querySelector(".watch-tab-name")!.textContent).sort())
        .toEqual(["Mei", "玩家 2", "玩家 3", "玩家 4"]);
    } finally {
      setLanguageChoice("system");
    }
  });

  it("shows the names as the server sends them", async () => {
    await open();
    expect(tabs().map((b) => b.querySelector(".watch-tab-name")!.textContent))
      .toEqual(["Mei", "Player 2", "Player 3", "Player 4"].slice(banker).concat(
        ["Mei", "Player 2", "Player 3", "Player 4"].slice(0, banker)));
  });
});

describe("a live table", () => {
  it("says its round in the strip and offers Next table", async () => {
    await open();
    expect(host.querySelector(".watch-round")!.textContent).toBe("Round 3 · previous round");
    await act(async () => { button("More").click(); });
    expect([...host.querySelectorAll("[role=menuitem]")].map((b) => b.textContent)).toEqual(["Next table", "Leave"]);
  });

  it("counts the table's watchers in the strip, in every language", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ ...feed, watchers: 3 }), { status: 200 })));
    for (const [choice, text, label] of [["en", "3Round 3 · previous round", "3 watching"],
      ["zh-Hans", "3第 3 局 · 上一局", "3 人观战"], ["zh-Hant", "3第 3 局 · 上一局", "3 人觀戰"]] as const) {
      setLanguageChoice(choice);
      try {
        await open();
        const chip = host.querySelector(".watch-round")!;
        expect(chip.textContent).toBe(text);
        expect(chip.querySelector(".watch-count")!.getAttribute("aria-label")).toBe(label);
      } finally {
        setLanguageChoice("system");
      }
    }
  });

  it("puts the transport, the tabs and the kitty in one row above the hand", async () => {
    await open();
    const row = host.querySelector(".watch-tabs-row")!;
    expect(row.querySelector(".watch-controls [aria-label='Pause']")).not.toBeNull();
    expect(row.querySelector("[role=tablist]")).not.toBeNull();
    expect(row.querySelector(".watch-kitty-slot")).not.toBeNull();
    expect(host.querySelector(".hud .watch-ctl")).toBeNull();
    expect(row.nextElementSibling?.classList.contains("watch-hand")).toBe(true);
  });
});

describe("back and Escape", () => {
  beforeEach(async () => {
    // let any back an earlier test queued land first
    await new Promise((r) => setTimeout(r, 0));
    window.history.replaceState(null, "", "/");
  });
  afterEach(() => { watch.close(); });

  const escape = () => act(async () => {
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  });

  it("opening a watch adds one history entry at the same address, and back leaves it", async () => {
    const href = window.location.href;
    const push = vi.spyOn(window.history, "pushState");
    watch.open("casual");
    expect(push).toHaveBeenCalledTimes(1);
    push.mockRestore();
    expect(window.location.href).toBe(href);
    await open();
    await act(async () => {
      window.history.back();
      await new Promise<void>((r) => window.addEventListener("popstate", () => r(), { once: true }));
    });
    expect(watch.get()).toBeNull();
    expect(window.location.href).toBe(href);
  });

  /** Walk history by `delta` and wait for its popstate. */
  const go = (delta: number) => act(async () => {
    const landed = new Promise<void>((r) => window.addEventListener("popstate", () => r(), { once: true }));
    window.history.go(delta);
    await landed;
  });

  it("Back then Forward opens the watch again, and Back then leaves it again", async () => {
    watch.open("ranked");
    await open();
    await go(-1);
    expect(watch.get()).toBeNull();
    await go(1);
    expect(watch.get()).toEqual({ mode: "ranked" });
    await go(-1);
    expect(watch.get()).toBeNull();
  });

  it("an Escape then Forward opens the watch again", async () => {
    watch.open("casual");
    await open();
    const landed = new Promise<void>((r) => window.addEventListener("popstate", () => r(), { once: true }));
    await escape();
    expect(watch.get()).toBeNull();
    // the close walks its own entry back
    await act(async () => { await landed; });
    expect(watch.get()).toBeNull();
    await go(1);
    expect(watch.get()).toEqual({ mode: "casual" });
  });

  it("a close then an immediate reopen keeps the new watch, and Back leaves it", async () => {
    watch.open("casual");
    const landed = new Promise<void>((r) => window.addEventListener("popstate", () => r(), { once: true }));
    watch.close();
    watch.open("ranked");
    await act(async () => { await landed; });
    expect(watch.get()).toEqual({ mode: "ranked" });
    await go(-1);
    expect(watch.get()).toBeNull();
    expect(window.location.pathname + window.location.hash).toBe("/");
  });

  it("Escape leaves", async () => {
    watch.open("casual");
    await open();
    await escape();
    expect(watch.get()).toBeNull();
  });

  it("Escape over the kitty peek closes only the peek", async () => {
    watch.open("casual");
    await open();
    await act(async () => { button("Pause").click(); });
    await act(async () => { button("Next trick").click(); });
    await act(async () => { button("Kitty").click(); });
    await escape();
    expect(host.querySelector(".watch-kitty-peek")).toBeNull();
    expect(watch.get()).not.toBeNull();
    await escape();
    expect(watch.get()).toBeNull();
  });

  it("Escape with the live table's menu open closes only the menu", async () => {
    watch.open("casual");
    await open();
    await act(async () => { button("More").click(); });
    await escape();
    expect(host.querySelector("[role=menu]")).toBeNull();
    expect(watch.get()).not.toBeNull();
  });

  it("Escape over the round end card leaves the watch alone", async () => {
    watch.open("casual");
    await open();
    await act(async () => { button("Pause").click(); });
    for (let i = 0; i < 40; i++) await act(async () => { button("Next trick")?.click(); });
    expect(document.querySelector(".round-end")).not.toBeNull();
    await escape();
    expect(watch.get()).not.toBeNull();
  });
});

describe("the watcher's round end", () => {
  it("closes on a backdrop tap, and Previous trick then steps back into the last trick", async () => {
    await open();
    await act(async () => { button("Pause").click(); });
    for (let i = 0; i < 40; i++) await act(async () => { button("Next trick")?.click(); });
    await act(async () => { await Promise.resolve(); });
    const dialog = document.querySelector("dialog.modal-backdrop")!;
    expect(dialog).not.toBeNull();
    await act(async () => { dialog.dispatchEvent(new MouseEvent("click", { bubbles: true })); });
    expect(document.querySelector(".round-end")).toBeNull();
    expect(button("Next trick").disabled).toBe(true);
    await act(async () => { button("Previous trick").click(); });
    expect(button("Next trick").disabled).toBe(false);
    expect(host.querySelectorAll(".trick-play").length).toBeGreaterThan(0);
    // playback reaching the end again brings the card back
    await act(async () => { button("Next trick").click(); });
    await act(async () => { await Promise.resolve(); });
    expect(document.querySelector(".round-end")).not.toBeNull();
  });
});

describe("the entry", () => {
  it("leads somewhere only with the server's feed on and something to show", () => {
    expect(canWatch(null)).toBe(false);
    expect(canWatch({})).toBe(false);
    expect(canWatch({ watch: 0, rerun: false })).toBe(false);
    expect(canWatch({ watch: 0, rerun: true })).toBe(true);
    expect(canWatch({ watch: 2 })).toBe(true);
  });
});

const GONE = Symbol("404");

describe("caught up", () => {
  type Reply = (url: string) => unknown | Promise<unknown>;
  let reply: Reply;
  const roots: { root: Root; host: HTMLDivElement }[] = [];
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "Date"] });
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      urls.push(url);
      const body = await reply(url);
      if (body === GONE) return new Response("{}", { status: 404 });
      return new Response(JSON.stringify(body), { status: 200 });
    }));
  });
  afterEach(() => {
    for (const r of roots.splice(0)) { act(() => r.root.unmount()); r.host.remove(); }
  });
  const flush = async () => { for (let i = 0; i < 5; i++) await act(async () => { await Promise.resolve(); }); };
  async function screen() {
    const h = document.createElement("div");
    document.body.appendChild(h);
    const r = createRoot(h);
    roots.push({ root: r, host: h });
    await act(async () => { r.render(<WatchScreen mode="ranked" />); });
    await flush();
    return h;
  }
  const btn = (h: HTMLElement, label: string) => h.querySelector<HTMLButtonElement>(`button[aria-label="${label}"]`);
  async function toEnd(h: HTMLElement) {
    await act(async () => { btn(h, "Pause")?.click(); });
    for (let i = 0; i < 40; i++) await act(async () => { btn(h, "Next trick")?.click(); });
    await flush();
  }
  const follows = (table = "abc123") => urls.filter((u) => u.startsWith(`/api/watch/${table}`)).length;

  it("keeps its place while the round plays back: one read per FOLLOW_MS in the foreground, none hidden", async () => {
    reply = (url) => url.startsWith("/api/watch/") ? { ...feed, waiting: true, events: undefined } : feed;
    const h = await screen();
    await act(async () => { btn(h, "Pause")?.click(); });     // mid-round, never at its end
    urls.length = 0;
    for (let s = 0; s < 120; s++) await act(async () => { vi.advanceTimersByTime(1000); });
    await flush();
    // the server's lease is 90 s; a round plays back for longer than that
    expect(follows()).toBe(Math.floor(120000 / FOLLOW_MS));
    expect(urls.every((u) => u.startsWith("/api/watch/abc123?after=3"))).toBe(true);
    const hidden = vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
    urls.length = 0;
    for (let s = 0; s < 60; s++) await act(async () => { vi.advanceTimersByTime(1000); });
    hidden.mockRestore();
    expect(follows()).toBe(0);
  });

  it("updates the live round and the seat from a waiting reply", async () => {
    reply = (url) => url.startsWith("/api/watch/")
      ? { ...feed, waiting: true, events: undefined, live_round: 5, code: null } : feed;
    const h = await screen();
    await toEnd(h);
    const card = document.querySelector(".round-end")!;
    expect(card.textContent).toContain("Round 5 in play");
    expect([...card.querySelectorAll(".round-end-actions button:not(.round-end-view-btn)")].map((b) => b.textContent)).toEqual(["Play", "Leave"]);
  });

  it("polls on one timer: two viewers behind one address stay well under its 30 reads a minute", async () => {
    reply = (url) => url.startsWith("/api/watch/") ? { ...feed, waiting: true, events: undefined } : feed;
    const a = await screen();
    const b = await screen();
    await toEnd(a);
    await toEnd(b);
    urls.length = 0;
    for (let s = 0; s < 60; s++) await act(async () => { vi.advanceTimersByTime(1000); });
    await flush();
    expect(urls.length).toBeLessThanOrEqual(10);
    expect(follows()).toBeGreaterThanOrEqual(4);
  });

  it("a round that arrives during the hold still plays after the card is closed, stepped back from and reached again", async () => {
    reply = (url) => (url.startsWith("/api/watch/abc123") ? { ...feed, round: 4, live_round: 5 } : feed);
    const h = await screen();
    await toEnd(h);                        // round 4 comes back at once and waits out the hold
    expect(follows()).toBeGreaterThanOrEqual(1);
    await act(async () => { vi.advanceTimersByTime(1000); });
    const dialog = document.querySelector("dialog.modal-backdrop")!;
    await act(async () => { dialog.dispatchEvent(new MouseEvent("click", { bubbles: true })); });
    await act(async () => { btn(h, "Previous trick")!.click(); });
    await act(async () => { btn(h, "Next trick")!.click(); });
    await flush();
    expect(document.querySelector(".round-end")).not.toBeNull();
    for (let s = 0; s < 20; s++) await act(async () => { vi.advanceTimersByTime(1000); });
    await flush();
    expect(h.querySelector(".watch-round")!.textContent).toContain("Round 4");
  });

  it("a switch to another table drops the old table's buffered round", async () => {
    const other = { ...feed, table: "zzz999", round: 7 };
    reply = (url) => url.startsWith("/api/watch/abc123") ? { ...feed, round: 4 }
      : url.startsWith("/api/watch/zzz999") ? { ...other, waiting: true, events: undefined }
      : url.includes("skip=abc123") ? other : feed;
    const h = await screen();
    await toEnd(h);                        // round 4 of abc123 is buffered behind the card
    await act(async () => { vi.advanceTimersByTime(1000); });
    await flush();
    expect(follows()).toBeGreaterThanOrEqual(1);
    await act(async () => { btn(h, "More")!.click(); });
    await act(async () => { [...h.querySelectorAll<HTMLButtonElement>("[role=menuitem]")][0].click(); });
    await flush();
    expect(h.querySelector(".watch-round")!.textContent).toContain("Round 7");
    await toEnd(h);                        // the new table's round ends; its next is still in play
    for (let s = 0; s < 20; s++) await act(async () => { vi.advanceTimersByTime(1000); });
    await flush();
    expect(h.querySelector(".watch-round")!.textContent).toContain("Round 7");
  });

  it("ignores a pick that answers after a later one", async () => {
    let release: (() => void) | null = null;
    const slow = new Promise<void>((r) => { release = r; });
    reply = async (url) => {
      if (url.includes("skip=abc123")) { await slow; return { ...feed, table: "old111", round: 9 }; }
      if (url.includes("skip=")) return { ...feed, table: "new222", round: 8 };
      return url.startsWith("/api/watch/") ? { ...feed, waiting: true, events: undefined } : feed;
    };
    const h = await screen();
    await act(async () => { btn(h, "Pause")!.click(); });
    const next = async () => {
      await act(async () => { btn(h, "More")!.click(); });
      await act(async () => { [...h.querySelectorAll<HTMLButtonElement>("[role=menuitem]")][0].click(); });
      await flush();
    };
    await next();                          // skip=abc123: slow
    await next();                          // still on abc123, so skip=abc123 again: also slow
    reply = async (url) => (url.includes("skip=") ? { ...feed, table: "new222", round: 8 } : feed);
    await next();
    expect(h.querySelector(".watch-round")!.textContent).toContain("Round 8");
    release!();
    await flush();
    expect(h.querySelector(".watch-round")!.textContent).toContain("Round 8");
  });

  const actions = () => [...document.querySelectorAll(".round-end .round-end-actions button:not(.round-end-view-btn)")].map((b) => b.textContent);

  it("a table that is gone and no replacement leaves no seat offer for it", async () => {
    reply = (url) => (url.startsWith("/api/watch/") || url.includes("skip=") ? GONE : feed);
    const h = await screen();
    await toEnd(h);
    expect(urls.some((u) => u.includes("skip=abc123"))).toBe(true);
    expect(actions()).toEqual(["Play", "Leave"]);
    expect(document.querySelector(".round-end")!.textContent).not.toContain("in play");
  });

  const nextTable = async (h: HTMLElement) => {
    await act(async () => { btn(h, "More")!.click(); });
    await act(async () => { [...h.querySelectorAll<HTMLButtonElement>("[role=menuitem]")][0].click(); });
    await flush();
  };

  it("a Next table that brings back the only table keeps it as it is: its round, its beat and its seat", async () => {
    reply = (url) => url.startsWith("/api/watch/") ? { ...feed, waiting: true, events: undefined }
      : url.includes("skip=abc123") ? { ...feed, round: 3, seat: (banker + 2) % 4 } : feed;
    const h = await screen();
    await act(async () => { btn(h, "Pause")!.click(); });
    for (let i = 0; i < 3; i++) await act(async () => { btn(h, "Next trick")!.click(); });
    const tab = [...h.querySelectorAll<HTMLButtonElement>("[role=tab]")][1];
    await act(async () => { tab.click(); });
    const before = { felt: h.querySelector(".felt")!.innerHTML, hand: h.querySelector(".watch-hand")!.innerHTML };
    await nextTable(h);
    expect(urls.some((u) => u.includes("skip=abc123"))).toBe(true);
    expect(tab.getAttribute("aria-selected")).toBe("true");
    expect(h.querySelector(".watch-hand")!.innerHTML).toBe(before.hand);
    expect(h.querySelector(".felt")!.innerHTML).toBe(before.felt);
    expect(btn(h, "Previous trick")!.disabled).toBe(false);
  });

  it("Next table goes on to the table the server picks, each in turn", async () => {
    const order = ["abc123", "bbb222", "ccc333"];
    reply = (url) => {
      if (url.startsWith("/api/watch/")) return { ...feed, waiting: true, events: undefined };
      const skip = new URL(url, "http://x").searchParams.get("skip");
      const table = skip ? order[(order.indexOf(skip) + 1) % order.length] : "abc123";
      return { ...feed, table, round: 3 + order.indexOf(table) };
    };
    const h = await screen();
    const seen = [];
    for (let i = 0; i < 4; i++) {
      await nextTable(h);
      seen.push(h.querySelector(".watch-round")!.textContent);
    }
    expect(seen).toEqual(["Round 4 · previous round", "Round 5 · previous round",
                          "Round 3 · previous round", "Round 4 · previous round"]);
    // a move to another table needs no leave: the server moves the watcher's count with it
    expect(beacons).toEqual([]);
  });

  const wOf = (url: string) => new URL(url, "http://x").searchParams.get("w");
  const eOf = (url: string) => new URL(url, "http://x").searchParams.get("e");
  const leaveOf = (e: number) => `/api/watch/leave?w=${sessionStorage.getItem("shengji.watcher")}&e=${e}`;

  it("opening the watch again is the same watcher in a new session, and each close tells the server once", async () => {
    reply = (url) => url.startsWith("/api/watch/") ? { ...feed, waiting: true, events: undefined }
      : { ...feed, watcher: wOf(url) };
    await screen();
    // the token is made before the first read, and kept for the session
    const mine = sessionStorage.getItem("shengji.watcher")!;
    expect(mine).toMatch(/^[0-9a-f]{32}$/);
    expect([wOf(urls[0]), eOf(urls[0])]).toEqual([mine, "1"]);
    const first = roots.pop()!;
    act(() => first.root.unmount());
    first.host.remove();
    expect(beacons).toEqual([leaveOf(1)]);
    urls.length = 0;
    await screen();
    expect([wOf(urls[0]), eOf(urls[0])]).toEqual([mine, "2"]);
    // the page going away tells it too, in its own session
    window.dispatchEvent(new Event("pagehide"));
    expect(beacons).toEqual([leaveOf(1), leaveOf(2)]);
  });

  const close = () => {
    const r = roots.pop()!;
    act(() => r.root.unmount());
    r.host.remove();
  };
  const held = () => {
    let deliver: (() => void) | null = null;
    const gate = new Promise<void>((res) => { deliver = res; });
    return { gate, deliver: async () => { deliver!(); await flush(); } };
  };

  it("an answer that lands after the screen closed sends that session's leave again", async () => {
    const first = held();
    reply = async (url) => {
      if (url.startsWith("/api/watch/")) return { ...feed, waiting: true, events: undefined };
      await first.gate;
      return feed;
    };
    const h = await screen();
    expect(h.querySelector(".watch-tabs")).toBeNull();      // still loading: its Leave
    close();
    expect(beacons).toEqual([leaveOf(1)]);
    await first.deliver();
    expect(beacons).toEqual([leaveOf(1), leaveOf(1)]);
  });

  it("closing while Next's answer is on its way: the leave names the session, whatever table it counts at", async () => {
    const b = held();
    reply = async (url) => {
      if (url.startsWith("/api/watch/")) return { ...feed, waiting: true, events: undefined };
      if (url.includes("skip=abc123")) { await b.gate; return { ...feed, table: "bbb222", round: 8 }; }
      return feed;
    };
    const h = await screen();
    await nextTable(h);
    // a follow of the table still drawn, sent while Next's answer is on its way, is the same session
    await act(async () => { vi.advanceTimersByTime(FOLLOW_MS); });
    expect(urls.filter((u) => u.startsWith("/api/watch/abc123")).every((u) => eOf(u) === "1")).toBe(true);
    close();
    await b.deliver();
    expect(beacons).toEqual([leaveOf(1), leaveOf(1)]);
  });

  it("a fresh tab left and opened again before its first answer: one token, and the late leave is the old session's", async () => {
    const first = held();
    let reads = 0;
    reply = async (url) => {
      if (url.startsWith("/api/watch/")) return { ...feed, waiting: true, events: undefined };
      const n = ++reads;
      if (n === 1) await first.gate;
      // the server echoes a token it is sent, and mints one for a read without
      return { ...feed, watcher: wOf(url) ?? `m${n}`.padEnd(32, "0") };
    };
    await screen();
    close();
    const h = await screen();
    expect(h.querySelector(".watch-tabs")).not.toBeNull();
    await first.deliver();
    const picks = urls.filter((u) => u.startsWith("/api/watch?"));
    expect(picks.map((u) => [wOf(u), eOf(u)])).toEqual([[wOf(picks[0]), "1"], [wOf(picks[0]), "2"]]);
    expect(wOf(picks[0])).toMatch(/^[0-9a-f]{32}$/);
    expect(sessionStorage.getItem("shengji.watcher")).toBe(wOf(picks[0]));
    // the late answer's leave names session 1: the server keeps session 2's watch
    expect(beacons).toEqual([leaveOf(1), leaveOf(1)]);
  });

  it("a replay's end that finds a live table, left during the card, tells the server", async () => {
    const rerun = { ...feed, table: "rerun", rerun: true, live_round: null, code: null };
    let picks = 0;
    reply = (url) => url.startsWith("/api/watch/") ? { ...feed, waiting: true, events: undefined }
      : picks++ === 0 ? rerun : feed;
    const h = await screen();
    await toEnd(h);                        // the next pick lands on abc123, buffered behind the card
    expect(picks).toBe(2);
    expect(h.querySelector(".watch-round")!.textContent).toBe("Replay");
    close();
    expect(beacons).toEqual([leaveOf(1)]);
  });

  it("a table that 404s and is found live again by the recovery pick plays on", async () => {
    let follows404 = 1;
    reply = (url) => {
      if (url.startsWith("/api/watch/abc123")) {
        if (follows404-- > 0) return GONE;
        return { ...feed, round: 4, waiting: true, events: undefined };
      }
      return url.includes("skip=abc123") ? { ...feed, round: 4 } : feed;
    };
    const h = await screen();
    await toEnd(h);
    expect(urls.some((u) => u.includes("skip=abc123"))).toBe(true);
    await act(async () => { vi.advanceTimersByTime(CARD_HOLD_MS + 100); });
    await flush();
    expect(h.querySelector(".watch-round")!.textContent).toContain("Round 4");
    // and it is followed again
    const before = follows();
    await toEnd(h);
    for (let s = 0; s < 3; s++) await act(async () => { vi.advanceTimersByTime(FOLLOW_MS); });
    await flush();
    expect(follows()).toBeGreaterThan(before);
  });

  it("Next on the only table keeps the round buffered behind the card, and its hold", async () => {
    reply = (url) => url.startsWith("/api/watch/abc123") ? { ...feed, round: 4 } : feed;
    const h = await screen();
    await toEnd(h);                        // round 4 of abc123 is buffered behind the card
    expect(follows()).toBeGreaterThanOrEqual(1);
    await act(async () => { vi.advanceTimersByTime(1000); });
    await flush();
    await nextTable(h);
    expect(urls.some((u) => u.includes("skip=abc123"))).toBe(true);
    expect(h.querySelector(".watch-round")!.textContent).toContain("Round 3");
    await act(async () => { vi.advanceTimersByTime(CARD_HOLD_MS - 1000 + 100); });
    await flush();
    expect(h.querySelector(".watch-round")!.textContent).toContain("Round 4");
  });

  it("a replay's close sends its one leave too: the server knows what it counts", async () => {
    reply = () => ({ ...feed, table: "rerun", rerun: true, live_round: null, code: null });
    await screen();
    close();
    expect(beacons).toEqual([leaveOf(1)]);
  });

  it("a Next table that finds nothing keeps the table and its seat offer", async () => {
    reply = (url) => url.includes("skip=") ? GONE
      : url.startsWith("/api/watch/") ? { ...feed, waiting: true, events: undefined } : feed;
    const h = await screen();
    await act(async () => { btn(h, "More")!.click(); });
    await act(async () => { [...h.querySelectorAll<HTMLButtonElement>("[role=menuitem]")][0].click(); });
    await flush();
    await toEnd(h);
    expect(h.querySelector(".watch-round")!.textContent).toContain("Round 3");
    expect(actions()).toEqual(["Take a seat", "Leave"]);
  });
});

// A live table changes under the watcher on every play, and iOS WebKit holds
// back the click of a tap while the page changes under it (its hover
// heuristic), letting it land only after the change has settled: a control
// that answers only the click toggles on a later play, not on the tap. A
// control that answers the touch acts on the tap and cancels the click.
describe("the menu while plays arrive", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "Date"] });
  });
  // a close's history back lands on the fake clock before the real one returns
  afterEach(() => { watch.close(); vi.runOnlyPendingTimers(); });

  const felt = () => host.querySelector(".felt")!.innerHTML;
  const menuOpen = () => {
    const more = button("More");
    const shown = host.querySelector("[role=menu]") !== null;
    expect(more.getAttribute("aria-expanded")).toBe(String(shown));
    return shown;
  };
  /** Time runs until the next play changes the table. */
  async function nextPlay() {
    const was = felt();
    for (let i = 0; i < 200 && felt() === was; i++) await act(async () => { vi.advanceTimersByTime(50); });
    expect(felt()).not.toBe(was);
  }
  /** A tap as iOS WebKit delivers it while plays arrive: the touch now, and
   *  its click, unless the touch cancelled it, only after the next play. */
  async function tap(el: Element) {
    const touch = { identifier: 1, clientX: 10, clientY: 10, target: el };
    const fire = (type: string, touches: unknown[]) => {
      const e = new Event(type, { bubbles: true, cancelable: true });
      Object.defineProperty(e, "touches", { value: touches });
      Object.defineProperty(e, "changedTouches", { value: [touch] });
      Object.defineProperty(e, "targetTouches", { value: touches });
      el.dispatchEvent(e);
      return e;
    };
    let end: Event | null = null;
    await act(async () => { fire("touchstart", [touch]); end = fire("touchend", []); });
    return async () => {
      if (end!.defaultPrevented) return;
      await act(async () => { (el as HTMLElement).click(); });
    };
  }

  it("stays closed across plays with no tap", async () => {
    await open();
    for (let i = 0; i < 6; i++) {
      await nextPlay();
      expect(menuOpen()).toBe(false);
    }
  });

  it("opens on the tap and stays open across plays until a tap closes it", async () => {
    await open();
    await nextPlay();
    const late = await tap(button("More"));
    expect(menuOpen()).toBe(true);
    await nextPlay();
    await late();
    for (let i = 0; i < 6; i++) {
      expect(menuOpen()).toBe(true);
      await nextPlay();
    }
    const lateClose = await tap(button("More"));
    expect(menuOpen()).toBe(false);
    await nextPlay();
    await lateClose();
    for (let i = 0; i < 6; i++) {
      expect(menuOpen()).toBe(false);
      await nextPlay();
    }
  });

  it("Next table and Leave act on the tap, once", async () => {
    watch.open("casual");
    await open();
    await (await tap(button("More")))();
    const rows = () => [...host.querySelectorAll<HTMLButtonElement>("[role=menuitem]")];
    const picks = urls.length;
    const lateNext = await tap(rows()[0]);
    expect(host.querySelector("[role=menu]")).toBeNull();
    expect(urls.length).toBe(picks + 1);
    await nextPlay();
    await lateNext();
    expect(urls.length).toBe(picks + 1);
    await (await tap(button("More")))();
    const close = vi.spyOn(watch, "close");
    await tap(rows()[1]);
    expect(watch.get()).toBeNull();
    expect(close).toHaveBeenCalledTimes(1);
    close.mockRestore();
  });

  it("a replay's Leave acts on the tap, once", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ ...feed, table: "rerun", rerun: true,
      live_round: null, code: null }), { status: 200 })));
    watch.open("ranked");
    await open();
    const close = vi.spyOn(watch, "close");
    const late = await tap(button("Leave"));
    expect(watch.get()).toBeNull();
    await late();
    expect(close).toHaveBeenCalledTimes(1);
    close.mockRestore();
  });
});

describe("a failed read", () => {
  type Answer = number | "offline";
  let answers: Answer[];
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "Date"] });
    clearToast();
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      urls.push(url);
      const a = answers.length > 1 ? answers.shift()! : answers[0];
      if (a === "offline") throw new TypeError("Failed to fetch");
      if (a !== 200) return new Response("{}", { status: a });
      const body = url.startsWith("/api/watch/") ? { ...feed, waiting: true, events: undefined } : feed;
      return new Response(JSON.stringify(body), { status: 200 });
    }));
  });
  // a close's history back lands on the fake clock before the real one returns
  afterEach(() => { watch.close(); clearToast(); vi.runOnlyPendingTimers(); });
  const flush = async () => { for (let i = 0; i < 5; i++) await act(async () => { await Promise.resolve(); }); };
  const nobody = () => host.querySelector(".watch-none");
  const reads = () => urls.filter((u) => u.startsWith("/api/watch?")).length;

  for (const status of [429, 500, 503, "offline"] as const) {
    it(`${status}: tried once more, and a table that then answers is shown`, async () => {
      answers = [status, 200];
      watch.open("ranked");
      await open();
      expect(nobody()).toBeNull();
      expect(reads()).toBe(1);
      await act(async () => { vi.advanceTimersByTime(RETRY_MS); });
      await flush();
      expect(reads()).toBe(2);
      expect(tabs()).toHaveLength(4);
      expect(nobody()).toBeNull();
      expect(watch.get()).not.toBeNull();
      expect(currentToast()).toBeNull();
    });

    it(`${status} twice: back to the Play tab with one toast, never the nobody line`, async () => {
      answers = [status];
      watch.open("ranked");
      await open();
      expect(nobody()).toBeNull();
      await act(async () => { vi.advanceTimersByTime(RETRY_MS); });
      await flush();
      expect(reads()).toBe(2);
      expect(nobody()).toBeNull();
      expect(watch.get()).toBeNull();
      expect(currentToast()?.text).toBe("Couldn't open a table");
      // nothing more is asked
      await act(async () => { vi.advanceTimersByTime(60_000); });
      expect(reads()).toBe(2);
    });
  }

  // a 200 whose round cannot be drawn (cut short) is a failed read, not an empty feed
  const cut = { ...feed, events: fixture.events.slice(0, 12) };
  it("a 200 with a round that cannot be drawn twice: back to the Play tab with one toast, never the nobody line", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      urls.push(url);
      return new Response(JSON.stringify(cut), { status: 200 });
    }));
    watch.open("ranked");
    await open();
    expect(nobody()).toBeNull();
    expect(watch.get()).not.toBeNull();
    await act(async () => { vi.advanceTimersByTime(RETRY_MS); });
    await flush();
    expect(reads()).toBe(2);
    expect(nobody()).toBeNull();
    expect(watch.get()).toBeNull();
    expect(currentToast()?.text).toBe("Couldn't open a table");
  });

  it("a 200 with a round that cannot be drawn, then a good one: the table", async () => {
    let n = 0;
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      urls.push(url);
      return new Response(JSON.stringify(n++ === 0 ? cut : feed), { status: 200 });
    }));
    watch.open("ranked");
    await open();
    expect(nobody()).toBeNull();
    await act(async () => { vi.advanceTimersByTime(RETRY_MS); });
    await flush();
    expect(tabs()).toHaveLength(4);
    expect(nobody()).toBeNull();
    expect(currentToast()).toBeNull();
  });

  it("404: the nobody line at once, with no second read", async () => {
    answers = [404];
    watch.open("ranked");
    await open();
    expect(nobody()).not.toBeNull();
    await act(async () => { vi.advanceTimersByTime(RETRY_MS * 4); });
    expect(reads()).toBe(1);
    expect(watch.get()).not.toBeNull();
    expect(currentToast()).toBeNull();
  });

  it("a Next table that fails keeps the table on screen and says nothing", async () => {
    answers = [200];
    watch.open("ranked");
    await open();
    answers = [500];
    await act(async () => { button("More").click(); });
    await act(async () => { [...host.querySelectorAll<HTMLButtonElement>("[role=menuitem]")][0].click(); });
    await act(async () => { vi.advanceTimersByTime(RETRY_MS); });
    await flush();
    expect(reads()).toBe(3);
    expect(tabs()).toHaveLength(4);
    expect(watch.get()).not.toBeNull();
    expect(currentToast()).toBeNull();
  });

  it("a read still waiting when the watch closes is not tried again", async () => {
    answers = [500];
    watch.open("ranked");
    await open();
    act(() => root.unmount());
    root = createRoot(host);
    await act(async () => { vi.advanceTimersByTime(RETRY_MS * 4); });
    expect(reads()).toBe(1);
    expect(currentToast()).toBeNull();
  });
});

describe("watch telemetry", () => {
  let open_: ReturnType<typeof vi.spyOn>;
  let leave: ReturnType<typeof vi.spyOn>;
  let toPlay: ReturnType<typeof vi.spyOn>;
  beforeEach(async () => {
    await new Promise((r) => setTimeout(r, 0));
    window.history.replaceState(null, "", "/");
    watchUsage.reset();
    open_ = vi.spyOn(telemetry, "watchOpen");
    leave = vi.spyOn(telemetry, "watchLeave");
    toPlay = vi.spyOn(telemetry, "watchToPlay");
  });
  afterEach(() => { watch.close(); vi.restoreAllMocks(); watchUsage.reset(); });

  it("a live table's open says live and the presence link; its Leave says close and the seconds", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "Date"] });
    watch.open("casual");
    await open();
    expect(open_).toHaveBeenCalledExactlyOnceWith("live", "presence");
    await act(async () => { vi.advanceTimersByTime(42_000); });
    await act(async () => { button("More").click(); });
    await act(async () => { [...host.querySelectorAll<HTMLButtonElement>("[role=menuitem]")][1].click(); });
    expect(leave).toHaveBeenCalledExactlyOnceWith("close", 42, "live");
    // a round begun within half an hour is the watch's lead to play
    await act(async () => { vi.advanceTimersByTime(90_000); });
    watchUsage.roundStarted();
    watchUsage.roundStarted();
    expect(toPlay).toHaveBeenCalledExactlyOnceWith(90, "close");
  });

  it("Escape, back and a seat taken say so; a round long after says nothing", async () => {
    watch.open("casual");
    await open();
    await act(async () => { window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })); });
    expect(leave).toHaveBeenLastCalledWith("escape", expect.any(Number), "live");
    act(() => root.unmount());
    root = createRoot(host);
    // the Escape's own back lands first
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });

    watch.open("casual");
    await open();
    await act(async () => {
      window.history.back();
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(leave).toHaveBeenLastCalledWith("back", expect.any(Number), "live");
    act(() => root.unmount());
    root = createRoot(host);

    vi.useFakeTimers({ toFake: ["Date"] });
    watch.open("casual");
    await open();
    watch.close("seat");
    expect(leave).toHaveBeenLastCalledWith("seat", 0, "live");
    vi.advanceTimersByTime(TO_PLAY_MS + 1000);
    watchUsage.roundStarted();
    expect(toPlay).not.toHaveBeenCalled();
    expect(leave).toHaveBeenCalledTimes(3);
  });

  it("Next table ends one table's watch and opens the next by next", async () => {
    let n = 0;
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      const body = url.startsWith("/api/watch/") ? { ...feed, waiting: true, events: undefined }
        : { ...feed, table: `t${n++}` };
      return new Response(JSON.stringify(body), { status: 200 });
    }));
    watch.open("ranked");
    await open();
    await act(async () => { button("More").click(); });
    await act(async () => { [...host.querySelectorAll<HTMLButtonElement>("[role=menuitem]")][0].click(); });
    await act(async () => { await Promise.resolve(); });
    expect(leave).toHaveBeenCalledExactlyOnceWith("next", expect.any(Number), "live");
    expect(open_.mock.calls).toEqual([["live", "presence"], ["live", "next"]]);
  });

  it("a replay that ends and is followed by a live table: each is opened and left by its own kind", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "Date"] });
    const rerun = { ...feed, table: "rerun", rerun: true, live_round: null, code: null };
    let reads = 0;
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      const body = url.startsWith("/api/watch/") ? { ...feed, waiting: true, events: undefined }
        : reads++ === 0 ? rerun : feed;
      return new Response(JSON.stringify(body), { status: 200 });
    }));
    watch.open("ranked");
    await open();
    expect(open_.mock.calls).toEqual([["replay", "presence"]]);
    await act(async () => { button("Pause").click(); });
    for (let i = 0; i < 40; i++) await act(async () => { button("Next trick")?.click(); });
    for (let i = 0; i < 5; i++) await act(async () => { await Promise.resolve(); });
    await act(async () => { vi.advanceTimersByTime(CARD_HOLD_MS); });
    for (let i = 0; i < 5; i++) await act(async () => { await Promise.resolve(); });
    expect(host.querySelector(".watch-round")!.textContent).toBe("Round 3 · previous round");
    expect(open_.mock.calls).toEqual([["replay", "presence"], ["live", "next"]]);
    expect(leave.mock.calls).toEqual([["ended", 5, "replay"]]);
    await act(async () => { vi.advanceTimersByTime(30_000); });
    await act(async () => { button("More").click(); });
    await act(async () => { [...host.querySelectorAll<HTMLButtonElement>("[role=menuitem]")][1].click(); });
    expect(leave.mock.calls).toEqual([["ended", 5, "replay"], ["close", 30, "live"]]);
  });

  it("the next round of the same table keeps its watch", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "Date"] });
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      const body = url.startsWith("/api/watch/") ? { ...feed, round: 4, live_round: 5 } : feed;
      return new Response(JSON.stringify(body), { status: 200 });
    }));
    watch.open("ranked");
    await open();
    await act(async () => { button("Pause").click(); });
    for (let i = 0; i < 40; i++) await act(async () => { button("Next trick")?.click(); });
    for (let i = 0; i < 5; i++) await act(async () => { await Promise.resolve(); });
    await act(async () => { vi.advanceTimersByTime(CARD_HOLD_MS); });
    for (let i = 0; i < 5; i++) await act(async () => { await Promise.resolve(); });
    expect(host.querySelector(".watch-round")!.textContent).toBe("Round 4 · previous round");
    expect(open_.mock.calls).toEqual([["live", "presence"]]);
    expect(leave).not.toHaveBeenCalled();
  });

  it("a replay says replay; a failed read's leave says error and no kind", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ ...feed, table: "rerun", rerun: true,
      live_round: null, code: null }), { status: 200 })));
    watch.open("ranked");
    await open();
    expect(open_).toHaveBeenLastCalledWith("replay", "presence");
    act(() => root.unmount());
    root = createRoot(host);
    watch.close();

    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "Date"] });
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 500 })));
    open_.mockClear();
    watch.open("ranked");
    await open();
    await act(async () => { vi.advanceTimersByTime(RETRY_MS); });
    for (let i = 0; i < 5; i++) await act(async () => { await Promise.resolve(); });
    expect(open_).not.toHaveBeenCalled();
    expect(leave).toHaveBeenLastCalledWith("error", 2, null);
  });
});
