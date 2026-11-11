import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import Leaderboard from "./Leaderboard";
import type { Leaderboard as Board, LeaderRow } from "../ratings/api";

function row(over: Partial<LeaderRow>): LeaderRow {
  return { rank: 1, name: "Ann", rating: 1700, rounds: 120, levels_per_round: 0.31, week_delta: 24,
           provisional: false, you: false, ...over };
}

const week: Board = {
  period: "week",
  players: [
    row({ rank: 1, name: "Shrewd", rating: 1712, week_delta: 24 }),
    row({ rank: 2, name: "sk", rating: 1694 }),
    row({ rank: 3, name: "Bold", rating: 1540, rounds: 14, provisional: true, week_delta: 40 }),
    row({ rank: 4, name: "Quiet", rating: 1480, levels_per_round: -0.04, week_delta: -8 }),
  ],
  me: row({ rank: 26, name: "Jerry", rating: 1210, rounds: 58, levels_per_round: -0.2, week_delta: -12, you: true }),
  anchor: { name: "Sheng Ji bot", rating: 1500 },
};

const calls: string[] = [];
let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
beforeEach(() => {
  calls.length = 0;
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    calls.push(url);
    const body = url.endsWith("period=week") ? week
      : { ...week, period: "all", players: [row({ rank: 1, name: "Jerry", you: true })], me: row({ rank: 1, name: "Jerry", you: true }) };
    return { status: 200, json: async () => body } as Response;
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
  await act(async () => { root.render(<Leaderboard inGame={false} />); });
  await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
}

it("lists the players with the bot anchor in rating order and pins the viewer's own row", async () => {
  await render();
  expect(calls).toEqual(["/api/leaderboard?period=week"]);
  const rows = [...host.querySelectorAll(".lb-row")];
  const names = rows.map((r) => r.querySelector(".lb-name-text")!.textContent);
  expect(names).toEqual(["Shrewd", "sk", "Bold", "Sheng Ji bot", "Quiet", "You"]);
  expect(rows[3].className).toContain("anchor");
  expect(rows[3].textContent).toContain("fixed anchor");
  const me = rows[5];
  expect(me.className).toContain("me");
  expect(me.querySelector(".lb-rank")!.textContent).toBe("26");
  expect(me.textContent).toContain("58 rounds · −0.20 lv/round");
  expect(me.textContent).toContain("▼ 12");
  expect(host.querySelector(".lb-gap")).not.toBeNull();
  expect(rows[0].textContent).toContain("120 rounds · +0.31 lv/round");
  expect(rows[0].textContent).toContain("▲ 24");
});

it("marks provisional players with a new chip", async () => {
  await render();
  const chips = [...host.querySelectorAll(".lb-new")];
  expect(chips).toHaveLength(1);
  expect(chips[0].closest(".lb-row")!.textContent).toContain("Bold");
  expect(chips[0].closest(".lb-row")!.textContent).toContain("14 rounds · provisional");
});

it("switches to all time and does not pin a row already in the list", async () => {
  await render();
  const all = [...host.querySelectorAll<HTMLButtonElement>(".lb-seg-btn")].find((b) => b.textContent === "All time")!;
  expect(all.getAttribute("aria-pressed")).toBe("false");
  await act(async () => { all.click(); await new Promise((r) => setTimeout(r, 0)); });
  expect(calls).toEqual(["/api/leaderboard?period=week", "/api/leaderboard?period=all"]);
  expect(all.getAttribute("aria-pressed")).toBe("true");
  expect(host.querySelectorAll(".lb-row.me")).toHaveLength(1);
  expect(host.querySelector(".lb-gap")).toBeNull();
});
