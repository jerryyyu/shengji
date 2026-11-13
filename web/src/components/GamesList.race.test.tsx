// Response ordering for the saved games' first page: a pull to refresh's
// response is never undone by an older first-page request landing after it.
import { act } from "react";
import type { MutableRefObject } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

vi.mock("../ws", () => ({ conn: { send: () => {}, reconnect: () => {} } }));

import { SavedGames } from "./GamesList";
import { cached, forgetHomeSession } from "../home/session";

const game = (id: string, room: string) => ({
  id, room_code: room, started_at: Math.floor(Date.now() / 1000) - 60, ended_at: null, seat: 0,
  players: ["Jerry", "Sam", "Mei", "Wen"], rounds: [1, 2], final_levels: ["4", "3"], games_won: [0, 0],
  incomplete: false,
});
const OLD = { games: [game("g-old", "OLD1")], next_before: null };
const FRESH = { games: [game("g-new", "NEW1"), game("g-old", "OLD1")], next_before: null };

let pending: ((body: unknown) => void)[];
let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
beforeEach(() => {
  forgetHomeSession();
  pending = [];
  globalThis.fetch = vi.fn((input: RequestInfo | URL) => {
    if (!String(input).startsWith("/api/me/games?")) return Promise.resolve({ status: 404, json: async () => ({}) } as Response);
    return new Promise<Response>((r) => {
      pending.push((body) => r({ status: 200, json: async () => body } as Response));
    });
  }) as typeof fetch;
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

const KEY = "user:j@x#0:games";
const rooms = () => [...host.querySelectorAll(".games-row-title")].map((e) => e.textContent?.match(/^(\w+) ·/)?.[1]);
type Cached = { status: string; games: { room_code: string }[] };

async function mountThenPull(order: "fresh-first" | "old-first") {
  const refresh: MutableRefObject<(() => Promise<void>) | null> = { current: null };
  await act(async () => { root.render(<SavedGames onPlay={() => {}} cacheKey={KEY} refreshRef={refresh} />); });
  let pulled: Promise<void> | undefined;
  await act(async () => { pulled = refresh.current!(); });
  expect(pending.length).toBe(2);
  const [mountReq, pullReq] = pending;
  const steps = order === "fresh-first" ? [() => pullReq(FRESH), () => mountReq(OLD)]
    : [() => mountReq(OLD), () => pullReq(FRESH)];
  for (const step of steps) {
    await act(async () => { step(); await new Promise((r) => setTimeout(r, 0)); });
  }
  await act(async () => { await pulled; });
}

it("keeps the pull's fresh first page and cache when the older request lands after it", async () => {
  await mountThenPull("fresh-first");
  expect(rooms()).toEqual(["NEW1", "OLD1"]);
  expect(cached<Cached>(KEY)?.games.map((g) => g.room_code)).toEqual(["NEW1", "OLD1"]);
});

it("ends on the pull's fresh first page when the older request lands first", async () => {
  await mountThenPull("old-first");
  expect(rooms()).toEqual(["NEW1", "OLD1"]);
  expect(cached<Cached>(KEY)?.games.map((g) => g.room_code)).toEqual(["NEW1", "OLD1"]);
});
