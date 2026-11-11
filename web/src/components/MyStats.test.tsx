import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import MyStats from "./MyStats";
import type { MyStats as Stats } from "../ratings/api";

const now = Math.floor(Date.now() / 1000);
const stats: Stats = {
  name: "Jerry", rating: 1712, rank: 1, rounds: 212, provisional: false, levels_per_round: 0.31,
  won_pct: 58, defender_won_pct: 63.2, attacker_won_pct: 49, best_streak: 7, games_won: 11,
  week_delta: 24, history: [1500, 1520, 1510, 1600, 1712],
  recent_games: [
    { started_at: now - 600, ended_at: now, rounds: 14, delta: 18, games_won: 1, partner: "sk",
      partner_bot: false, opponents_bots: 2 },
    { started_at: now - 90000, ended_at: now - 86400 * 3, rounds: 9, delta: -6, games_won: 0, partner: null,
      partner_bot: true, opponents_bots: 2 },
  ],
  visible: true,
};

const posts: unknown[] = [];
let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
beforeEach(() => {
  posts.length = 0;
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    if (init?.method === "POST") {
      const body = JSON.parse(String(init.body));
      posts.push(body);
      return { status: 200, json: async () => body } as Response;
    }
    expect(String(input)).toBe("/api/me/stats");
    return { status: 200, json: async () => stats } as Response;
  }) as typeof fetch;
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

async function render() {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => { root.render(<MyStats inGame={false} />); });
  await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
}

it("shows the rating, rank, sparkline, tiles and recent games", async () => {
  await render();
  expect(host.querySelector(".stats-rating")!.textContent).toBe("1712");
  expect(host.querySelector(".stats-big")!.textContent).toContain("#1 all time · 212 rounds");
  const line = host.querySelector(".stats-spark polyline")!;
  expect(line.getAttribute("points")!.split(" ")).toHaveLength(5);
  const tiles = [...host.querySelectorAll(".stats-tile")].map((t) => t.textContent);
  expect(tiles).toEqual(["+0.31levels per round", "58%rounds won", "63%won as defenders",
                         "49%won as attackers", "7best win streak", "11games won (to A)"]);
  const games = [...host.querySelectorAll(".lb-row.game")].map((g) => g.textContent);
  expect(games[0]).toContain("With sk vs bots");
  expect(games[0]).toContain("Today · 14 rounds · won a game");
  expect(games[0]).toContain("+18");
  expect(games[1]).toContain("With a bot partner vs bots");
  expect(games[1]).toContain("−6");
});

it("the leaderboard toggle stores the choice", async () => {
  await render();
  const toggle = host.querySelector<HTMLButtonElement>(".stats-toggle")!;
  expect(toggle.getAttribute("aria-checked")).toBe("true");
  await act(async () => { toggle.click(); await new Promise((r) => setTimeout(r, 0)); });
  expect(posts).toEqual([{ visible: false }]);
  expect(toggle.getAttribute("aria-checked")).toBe("false");
});
