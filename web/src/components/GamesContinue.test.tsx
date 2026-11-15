// A saved game's row only opens it; its page holds Continue (only when the
// record has both teams' levels, and only while no room is open) and a
// Replay per round.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import GamesList, { SavedGames } from "./GamesList";
import { navigate } from "../replay/route";
import { hasLevels, setContinueHandler } from "../replay/continueGame";
import type { GameRow } from "../replay/api";

function row(id: string, extra: Partial<GameRow> = {}): GameRow {
  return {
    id, room_code: "ABCD", started_at: 1790000000, ended_at: 1790001800, seat: 0,
    players: ["Ana", "Bot 1", "Bea", "Bot 3"], rounds: [2, 3],
    final_levels: ["5", "3"], games_won: [0, 0], incomplete: false, ...extra,
  };
}

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
let continued: string[];
let games: GameRow[];
beforeEach(() => {
  continued = [];
  setContinueHandler((id) => continued.push(id), true);
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    const one = games.find((g) => url === `/api/me/games/${g.id}`);
    const body = url.startsWith("/api/me/games?") ? { games, next_before: null }
      : one ? { ...one, round_results: [] } : null;
    return { status: body ? 200 : 404, json: async () => body ?? {} } as Response;
  }) as typeof fetch;
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  setContinueHandler(null, false);
  act(() => navigate(null));
});

async function render(node: React.ReactNode) {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => { root.render(node); });
  await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
}

describe("a saved game's row", () => {
  it("is one tap target that opens the game: no Continue or Replay on it", async () => {
    games = [row("g1"), row("old", { final_levels: null })];
    await render(<SavedGames onPlay={() => {}} />);
    const items = [...host.querySelectorAll(".games-day-item")];
    expect(items.map((li) => li.querySelectorAll("button").length)).toEqual([1, 1]);
    expect(host.querySelector(".games-continue, .games-replay")).toBeNull();
    act(() => items[0].querySelector<HTMLButtonElement>("button.games-day-row")!.click());
    expect(window.location.hash).toBe("#/games/g1");
  });
});

describe("a saved game's page", () => {
  it("offers one gold Continue under the summary, and Replay only per round", async () => {
    games = [row("g1")];
    await render(<GamesList route={{ page: "game", id: "g1" }} />);
    const btns = [...host.querySelectorAll<HTMLButtonElement>(".games-actions button")];
    expect(btns.map((b) => b.textContent)).toEqual(["Continue"]);
    expect(btns[0].classList.contains("gold")).toBe(true);
    expect(host.querySelectorAll(".btn.gold")).toHaveLength(1);
    act(() => btns[0].click());
    expect(continued).toEqual(["g1"]);
    const replays = [...host.querySelectorAll<HTMLButtonElement>(".games-round button")];
    expect(replays.map((b) => b.textContent)).toEqual(["Replay", "Replay"]);
    act(() => replays[0].click());
    expect(window.location.hash).toBe("#/games/g1/rounds/2");
  });

  it("Continue is disabled while a room is open", async () => {
    setContinueHandler((id) => continued.push(id), false);
    games = [row("g1")];
    await render(<GamesList route={{ page: "game", id: "g1" }} />);
    const btn = host.querySelector<HTMLButtonElement>(".games-continue")!;
    expect(btn.disabled).toBe(true);
    act(() => btn.click());
    expect(continued).toEqual([]);
  });

  it("an old record without both levels offers no Continue", async () => {
    games = [row("old", { final_levels: null }), row("odd", { final_levels: ["5", "Z"] })];
    await render(<GamesList route={{ page: "game", id: "old" }} />);
    expect(host.querySelector(".games-continue")).toBeNull();
    expect(host.querySelectorAll(".games-round button")).toHaveLength(2);
  });
});

it("hasLevels needs two known ranks", () => {
  expect(hasLevels({ final_levels: ["2", "A"] })).toBe(true);
  expect(hasLevels({ final_levels: { team0: "10", team1: "J" } })).toBe(true);
  expect(hasLevels({ final_levels: null })).toBe(false);
  expect(hasLevels({ final_levels: ["2"] })).toBe(false);
  expect(hasLevels({ final_levels: ["2", "1"] })).toBe(false);
});
