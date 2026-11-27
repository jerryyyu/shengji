// Companions on the watch screen: each person's look at their seat as the
// feed sends it (a masked seat's is the default Tractor, a bot has none), the
// watcher's own in the gallery spot by the row, and none at all with the
// Collection off or Show companions at the table off.
import { act } from "react";
import { createRoot } from "react-dom/client";
import type { Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import fixture from "../replay/server-round-finished.fixture.json";
import { TABLES } from "../companion/seatZones.fixtures";
import type { Rect } from "../companion/seatZones";
import WatchScreen from "./WatchScreen";
import WatcherCompanion, { OWN_CHEER_GAP_MS } from "./WatcherCompanion";

const collection = vi.hoisted(() => ({ on: true }));
vi.mock("../companion/feature", () => ({ useCollection: () => collection.on }));
vi.mock("../audio", () => ({ prewarmAudio: () => {}, isMuted: () => true, setMuted: () => {},
  subscribeMuted: () => () => {}, play: () => {}, resetAnnouncer: () => {}, announceState: () => {} }));
vi.mock("../queue/store", () => ({ queue: { setPlayMode: () => {}, join: () => {} } }));
vi.mock("../codeJoin", () => ({ codes: { open: () => true } }));
vi.mock("../roundTelemetry", () => ({ rounds: { noteEntry: () => {} } }));
vi.mock("../ws", () => ({ conn: { send: () => true, subscribe: () => () => {}, subscribeStatus: () => () => {},
  status: "open", generation: 1, chatHistory: () => [] } }));

const banker = (fixture.events.find((e) => e.e === "trump") as { banker: number }).banker;
type P = { seat: number; name: string; is_bot: boolean };
const start = fixture.events[0] as { players: P[] };
// seat 0 a listed player in a panda, seat 2 masked ("Player 3": the default
// Tractor, as the server masks it), seats 1 and 3 bots
const LOOKS: (string | null)[] = ["panda/gilded", null, "tractor/red", null];
const players = start.players.map((p) => ({ ...p, is_bot: p.seat % 2 === 1, name: p.seat === 2 ? "Player 3" : p.name,
  look: LOOKS[p.seat] }));
const events = fixture.events.map((e, i) => (i === 0 ? { ...e, players } : e));
const feed = {
  table: "abc123", watcher: "w".repeat(32), mode: "ranked", live_round: 4, code: null, watchers: 2,
  rerun: false, waiting: false, round: 3, seat: banker, players: players.map((p) => p.name), finished: true, events,
};

const m = TABLES["phone-land-w2"];
const rects: Record<string, Rect> = {
  felt: { x: 0, y: 0, ...m.felt }, "pos-left": m.plates.left!, "pos-top": m.plates.top!, "pos-right": m.plates.right!,
  "watch-tabs-row": m.row!, hand: m.hand!, "hand-slot": m.firstCard,
};
let spy: ReturnType<typeof vi.spyOn>;
let root: Root;
let host: HTMLDivElement;
beforeEach(() => {
  collection.on = true;
  window.localStorage.removeItem("shengji.companions");
  spy = vi.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(function (this: Element) {
    const cls = [...this.classList];
    const k = Object.keys(rects).find((c) => cls.includes(c));
    const r = k ? rects[k] : { x: 0, y: 0, w: 0, h: 0 };
    return { left: r.x, top: r.y, width: r.w, height: r.h, right: r.x + r.w, bottom: r.y + r.h, x: r.x, y: r.y, toJSON: () => ({}) } as DOMRect;
  });
  vi.stubGlobal("fetch", vi.fn(async (url: string) => new Response(JSON.stringify(
    url.startsWith("/api/watch/") ? { ...feed, waiting: true, events: undefined } : feed), { status: 200 })));
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  spy.mockRestore();
  vi.unstubAllGlobals();
  vi.useRealTimers();
  window.localStorage.removeItem("shengji.companions");
});

async function open() {
  await act(async () => { root.render(<WatchScreen mode="ranked" />); });
  for (let i = 0; i < 3; i++) await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
}
const figures = () => [...host.querySelectorAll<HTMLElement>(".table-companions .tc-seat")]
  .map((s) => [Number(s.dataset.seat), s.querySelector("svg")?.getAttribute("data-look") ?? s.querySelector("[data-look]")?.getAttribute("data-look") ?? "?"]);
const seats = () => figures().map(([s]) => s).sort();

describe("the players' companions", () => {
  it("stand at the people's seats, each in its look; the bots have none", async () => {
    await open();
    expect(seats()).toEqual([0, 2]);
    // nobody at the table is you: no seat is tagged
    expect(host.querySelector(".table-companions .tc-you")).toBeNull();
  });

  it("draw a masked seat as the default Tractor and a listed one in its own look", async () => {
    await open();
    const kindOf = (seat: number) => host.querySelector(`.table-companions .tc-seat[data-seat="${seat}"] svg`)?.getAttribute("class") ?? "";
    expect(kindOf(2)).toContain("tractor");
    expect(kindOf(0)).toContain("panda");
  });

  it("draw none for a person whose look the feed left out", async () => {
    players[0].look = null as unknown as string;
    try {
      await open();
      expect(seats()).toEqual([2]);
    } finally {
      players[0].look = LOOKS[0]!;
    }
  });
});

describe("the watcher's own companion", () => {
  it("stands in the gallery spot in the watcher's row, tagged You, never on the felt", async () => {
    await open();
    const own = host.querySelector(".watch-tabs-row > .watch-own")!;
    expect(own).not.toBeNull();
    expect(own.querySelector(".tc-you")!.textContent).toBe("You");
    expect(own.closest(".table-companions")).toBeNull();
  });

  it("cheers a big trick, at most once per gap, and keeps still when quiet", async () => {
    const cheers = () => Number(host.querySelector(".watch-own")!.getAttribute("data-cheers"));
    const draw = (cheer: number | null, quiet = false) =>
      act(async () => { root.render(<WatcherCompanion cheer={cheer} quiet={quiet} />); });
    const now = vi.spyOn(Date, "now");
    try {
      now.mockReturnValue(100_000);
      await draw(null);
      expect(cheers()).toBe(0);
      await draw(5);
      expect(cheers()).toBe(1);
      expect(host.querySelector(".watch-own svg")!.getAttribute("data-pose")).toBe("cheer");
      await draw(5);                                   // the same trick again: nothing new
      now.mockReturnValue(100_000 + OWN_CHEER_GAP_MS - 1);
      await draw(9);                                   // another big trick inside the gap
      expect(cheers()).toBe(1);
      now.mockReturnValue(100_000 + 3 * OWN_CHEER_GAP_MS);
      await draw(12, true);                            // fast play, a step back or a turn
      expect(cheers()).toBe(1);
      await draw(14);
      expect(cheers()).toBe(2);
    } finally {
      now.mockRestore();
    }
  });
});

describe("the setting", () => {
  it("off at the table: no figures at all", async () => {
    window.localStorage.setItem("shengji.companions", "off");
    await open();
    expect(host.querySelector(".table-companions, .watch-own")).toBeNull();
  });

  it("with the Collection off: no figures at all", async () => {
    collection.on = false;
    await open();
    expect(host.querySelector(".table-companions, .watch-own")).toBeNull();
  });
});
