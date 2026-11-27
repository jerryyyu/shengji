// The watch screen against a real finished round: the tabs, the turn to
// another player, the controls, the kitty peek, and the watcher's round end
// with the caught-up line. Every read is a stubbed fetch of the feed.
import { act } from "react";
import { createRoot } from "react-dom/client";
import type { Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import fixture from "../replay/server-round-finished.fixture.json";
import WatchScreen from "./WatchScreen";
import { watch } from "./store";
import { canWatch } from "./store";
import { setLanguageChoice } from "../i18n";

// a watcher shown the Collection still sees no portraits: the feed carries no looks
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
let root: Root;
let host: HTMLDivElement;

beforeEach(() => {
  // jsdom has no modal top layer: the round end's dialog only needs to open
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", { configurable: true,
    value: function (this: HTMLDialogElement) { this.setAttribute("open", ""); } });
  Object.defineProperty(HTMLDialogElement.prototype, "close", { configurable: true,
    value: function (this: HTMLDialogElement) { this.removeAttribute("open"); } });
  urls.length = 0;
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
    // nor any companion on the felt
    expect(document.querySelector(".table-companions, .cmp")).toBeNull();
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

  it("offers no Next table, only Leave", async () => {
    await open();
    await act(async () => { button("More").click(); });
    expect([...host.querySelectorAll("[role=menuitem]")].map((b) => b.textContent)).toEqual(["Leave"]);
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
    expect(host.querySelector(".watch-round")!.textContent).toBe("Round 3");
    await act(async () => { button("More").click(); });
    expect([...host.querySelectorAll("[role=menuitem]")].map((b) => b.textContent)).toEqual(["Next table", "Leave"]);
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
