// Me, its saved games and the leaderboard in Simplified Chinese: the same
// surfaces as their English tests, drawn from the zh table.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import type { AuthState } from "../auth";

const { authState } = vi.hoisted(() => ({
  authState: { current: { status: "loading", clientId: null, user: null } as AuthState },
}));
vi.mock("../ws", () => ({ conn: { send: () => {}, reconnect: () => {} } }));
vi.mock("../auth", async (importOriginal) => {
  const real = await importOriginal<typeof import("../auth")>();
  return { ...real, useAuth: () => authState.current,
           auth: { signOut: vi.fn(() => Promise.resolve()), deleted: vi.fn(), updated: vi.fn(), signedIn: vi.fn() } };
});

import MePage from "../components/MePage";
import Leaderboard from "../components/Leaderboard";
import GamesList from "../components/GamesList";
import { forgetHomeSession } from "../home/session";
import { guestName } from "../guestName";
import { setLanguageChoice } from ".";

const JERRY = { name: "Jerry Yu", email: "j@x", picture: null, display_name: null, name_shown: "Jerry" };
const STATS = { name: "Jerry", rating: 1532, rank: 12, rounds: 412, provisional: false, levels_per_round: 0.41,
                won_pct: 58.2, defender_won_pct: 61, attacker_won_pct: 54, best_streak: 7, games_won: 34,
                week_delta: 8, history: [1491, 1532], visible: true, recent_games: [] };
const GAME = { id: "g1", room_code: "KQ4X", started_at: Math.floor(Date.now() / 1000) - 60, ended_at: null, seat: 0,
               players: ["Jerry", "Sam", "Mei", "Wen"], rounds: [1, 2], final_levels: ["4", "3"],
               games_won: [0, 0], incomplete: true };
const DETAIL = { ...GAME, round_results: [{ round: 1, seat: 0, level: "2", banker: 0, result: { winner_team: 0 } }] };
const row = (over: object) => ({ rank: 1, name: "Ann", rating: 1700, rounds: 120, levels_per_round: 0.31,
                                 week_rank_move: 3, provisional: false, you: false, ...over });
const BOARD = { period: "week", players: [row({ rank: 1, name: "Bold", provisional: true })],
                me: row({ rank: 26, name: "Jerry", rating: 1210, you: true }), anchor: { name: "bot", rating: 1500 } };

beforeAll(() => {
  class SilentAudioContext { state = "running"; currentTime = 0; async resume() {} }
  (window as unknown as { AudioContext: unknown }).AudioContext = SilentAudioContext;
});

beforeEach(() => {
  forgetHomeSession();
  guestName.reset();
  authState.current = { status: "in", clientId: "cid", user: JERRY };
  setLanguageChoice("zh-Hans");
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    const body = url === "/api/me/stats" ? STATS
      : url.startsWith("/api/me/games?") ? { games: [GAME], next_before: null }
      : url === "/api/me/games/g1" ? DETAIL
      : url.startsWith("/api/leaderboard") ? BOARD : null;
    return { status: body ? 200 : 404, json: async () => body ?? {} } as Response;
  }) as typeof fetch;
});

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
afterEach(() => {
  setLanguageChoice("system");
  act(() => root.unmount());
  host.remove();
  window.history.replaceState(null, "", "/");
});

async function render(node: React.ReactNode) {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => { root.render(node); });
  await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
}
const rowLabels = () => [...host.querySelectorAll(".grp-row .grp-label")].map((e) => e.textContent);

describe("Me in Simplified Chinese", () => {
  it("Stats: the identity line, the tiles, the counts and the account rows", async () => {
    await render(<MePage section="stats" />);
    expect(host.querySelector(".large-title")?.textContent).toBe("我");
    expect(host.querySelector(".me-sub")?.textContent).toBe("1,532 · 总榜第 12 · 本周 ▲ 8");
    expect(host.querySelector(".me-sub b")?.textContent).toBe("▲ 8");
    expect([...host.querySelectorAll(".segmented-btn")].map((b) => b.textContent)).toEqual(["战绩", "对局"]);
    expect([...host.querySelectorAll(".me-tile")].map((t) => t.textContent))
      .toEqual(["58%局胜率", "+0.41级/局", "7最长连胜"]);
    expect(host.querySelector(".me-spark")?.getAttribute("aria-label")).toBe("最近 1 局的积分，从 1,491 到 1,532");
    expect(rowLabels()).toEqual(["赢的盘数", "总局数", "坐庄胜率", "闲家胜率",
      "新手提示", "音效", "语言", "怎么玩", "在排行榜上显示我", "改昵称", "隐私政策",
      "使用条款", "帮助", "iPhone 版", "退出登录", "注销账号"]);
    // the player's name and the App Store's device are the only Latin words
    expect(host.textContent!.replace(/Jerry|iPhone/g, "")).not.toMatch(/[A-Za-z]{2,}/);
  });

  it("the delete sheet asks in Chinese", async () => {
    await render(<MePage section="stats" />);
    act(() => host.querySelector<HTMLButtonElement>(".me-delete")!.click());
    const sheet = document.querySelector(".me-delete-confirm")!;
    expect(sheet.textContent).toContain("注销账号？");
    expect(sheet.textContent).toContain("积分和对局都会删除。");
    expect(sheet.querySelector(".me-delete-yes")?.textContent).toBe("注销");
  });

  it("Games: a saved game's row reads in Chinese", async () => {
    await render(<MePage section="games" />);
    const r = host.querySelector(".games-day-row")!;
    expect(r.querySelector(".games-row-title")?.textContent).toBe("我和 Mei 对 Sam、Wen");
    expect(r.querySelector(".games-row-sub")?.textContent).toMatch(/ · 2 局 · 级数 4–3未打完$/);
  });

  it("a guest's Me names them 游客 until they have a name", async () => {
    authState.current = { status: "out", clientId: null, user: null };
    await render(<MePage section="stats" />);
    expect(host.querySelector(".me-sub")?.textContent).toBe("游客");
  });
});

describe("a saved game in Simplified Chinese", () => {
  it("shows its teams, rounds and actions", async () => {
    await render(<GamesList route={{ page: "game", id: "g1" }} />);
    expect(host.querySelector(".games-title")?.textContent).toBe("对局详情");
    expect(host.querySelector(".games-back")?.textContent).toBe("‹ 对局");
    expect(host.querySelector(".games-team.mine")?.textContent).toBe("Jerry（我）和 Mei");
    expect(host.querySelector(".games-vs")?.textContent).toBe("对");
    expect(host.querySelector(".games-meta")?.textContent).toBe("2 局级数 4–3赢的盘数：0–0未打完");
    expect([...host.querySelectorAll(".games-round-n")].map((e) => e.textContent)).toEqual(["第 1 局", "第 2 局"]);
    expect([...host.querySelectorAll(".games-round-res")].map((e) => e.textContent))
      .toEqual(["打 2 · 坐庄 · 赢", "未打完"]);
    expect(host.querySelector(".games-remove")?.textContent).toBe("从我的对局中删除");
  });
});

describe("the leaderboard in Simplified Chinese", () => {
  it("names the periods, marks the viewer and the provisional rows", async () => {
    await render(<Leaderboard />);
    expect(host.querySelector(".large-title")?.textContent).toBe("排行榜");
    expect([...host.querySelectorAll(".segmented-btn")].map((b) => b.textContent)).toEqual(["本周", "总榜"]);
    const bold = host.querySelector(".lb-new")!;
    expect(bold.textContent).toBe("新");
    expect(bold.getAttribute("title")).toBe("排位不到 20 局");
    expect(host.querySelector(".lb-pin .lb-name")?.textContent).toBe("Jerry（我）");
    // This week's movement is read out in Chinese
    expect([...host.querySelectorAll(".lb-move .sr-only")].map((s) => s.textContent)).toContain("，本周上升 3 名");
  });
});
