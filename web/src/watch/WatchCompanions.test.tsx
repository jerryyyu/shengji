// Companions on the watch screen: each person's look at their seat as the
// feed sends it (a masked seat's is the default Tractor, a bot has none), the
// watcher's own on the felt as yours stands at the table, and none at all with the
// Collection off or Show companions at the table off.
import { act } from "react";
import { createRoot } from "react-dom/client";
import type { Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import fixture from "../replay/server-round-finished.fixture.json";
import { TABLES } from "../companion/seatZones.fixtures";
import type { Rect } from "../companion/seatZones";
import WatchScreen, { load, watchState } from "./WatchScreen";
import TableCompanions, { WATCHER, WATCHER_CHEER_GAP_MS } from "../companion/TableCompanions";

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
  "watch-controls": { x: m.row!.x + 160, y: m.row!.y, w: 160, h: m.row!.h },
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
const seats = () => figures().map(([s]) => s).filter((s) => s !== WATCHER).sort();
const own = () => host.querySelector<HTMLElement>(`.table-companions .tc-seat[data-seat="${WATCHER}"]`);

describe("the players' companions", () => {
  it("stand at the people's seats, each in its look; the bots have none", async () => {
    await open();
    expect(seats()).toEqual([0, 2]);
    // nobody at the table is you: no seat is tagged, only the watcher's own
    const tags = [...host.querySelectorAll(".table-companions .tc-you")].map((t) => t.closest(".tc-seat")?.getAttribute("data-seat"));
    expect(tags).toEqual([String(WATCHER)]);
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
  it("stands on the felt, tagged You, a tap away from walking, left of the watcher's controls", async () => {
    await open();
    const fig = own()!;
    expect(fig).not.toBeNull();
    expect(fig.querySelector(".tc-you")!.textContent).toBe("You");
    // it takes taps (its special) as yours does; the players' figures take none
    expect(fig.querySelector(".tc-walk")!.classList.contains("tc-mine")).toBe(true);
    expect(host.querySelectorAll(".table-companions .tc-mine")).toHaveLength(1);
    expect(host.querySelector(".watch-own")).toBeNull();
  });

  it("cheers a big trick, at most once per gap, and keeps still when quiet", async () => {
    const loaded = load(feed as never)!;
    const beat = loaded.beats[loaded.beats.length - 2];
    const state = watchState(loaded, beat, loaded.doc.seat ?? 0, []);
    const cheers: string[] = [];
    const draw = async (cheer: number | null, quiet = false) => {
      await act(async () => {
        root.render(<div className="felt"><div className="watch-controls" />
          <TableCompanions state={state} watch={{ quiet, cheer }} /></div>);
      });
      await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
      const move = own()?.querySelector(".tc-move")?.getAttribute("data-move") ?? "none";
      cheers.push(move);
    };
    const now = vi.spyOn(Date, "now");
    try {
      now.mockReturnValue(100_000);
      await draw(null);
      await draw(5);
      await draw(5);                                   // the same trick again: nothing new
      now.mockReturnValue(100_000 + WATCHER_CHEER_GAP_MS - 1);
      await draw(9);                                   // another big trick inside the gap
      now.mockReturnValue(100_000 + 3 * WATCHER_CHEER_GAP_MS);
      await draw(12, true);                            // fast play, a step back or a turn
      await draw(14);
    } finally {
      now.mockRestore();
    }
    expect(cheers).toEqual(["idle", "cheer", "cheer", "cheer", "cheer", "cheer"]);
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
