// "My games": the history list, a game's rounds, removal, and the replay,
// against a mocked `/api/me/games*` (the contract the server implements).
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import GamesList, { SavedGames } from "./GamesList";
import { remember } from "../home/session";
import { dayLabel } from "../home/dayLabel";
import { navigate, useGamesRoute } from "../replay/route";
import roundFixture from "../replay/round.fixture.json";
import type { GameRow } from "../replay/api";

vi.mock("../ws", () => ({ conn: { send: () => {}, reconnect: () => {} } }));

function row(id: string, started: number, extra: Partial<GameRow> = {}): GameRow {
  return {
    id, room_code: "ABCD", started_at: started, ended_at: started + 1800, seat: 0,
    players: ["Ana", "Bot 1", "Bea", "Bot 3"], rounds: [1, 2, 3],
    final_levels: ["5", "3"], games_won: [1, 0], incomplete: false, ...extra,
  };
}

type Route = { status: number; body?: unknown };
let routes: Record<string, Route>;
let calls: { url: string; method: string }[];

beforeEach(() => {
  calls = [];
  routes = {};
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    calls.push({ url, method });
    const r = routes[`${method} ${url}`] ?? { status: 404, body: { detail: "not found" } };
    return {
      status: r.status,
      json: async () => {
        if (r.body === undefined) throw new Error("no body");
        return r.body;
      },
    } as Response;
  }) as typeof fetch;
});

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  act(() => navigate(null));
});

function Host() {
  const route = useGamesRoute();
  if (!route) return <div className="no-route" />;
  // the list is the Me tab's Games section; a game and its replays are pages
  return route.page === "list" ? <SavedGames onPlay={() => {}} /> : <GamesList route={route} />;
}

async function settle() {
  await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
}

async function mount(start: Parameters<typeof navigate>[0] = { page: "list" }) {
  act(() => navigate(start));
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  act(() => root.render(<Host />));
  await settle();
}

const q = (sel: string) => host.querySelector<HTMLElement>(sel);
const qa = (sel: string) => Array.from(host.querySelectorAll<HTMLElement>(sel));
const button = (label: string) =>
  qa("button").find((b) => b.textContent?.trim() === label || b.getAttribute("aria-label") === label) as HTMLButtonElement;
const click = async (el: HTMLElement) => { act(() => el.click()); await settle(); };

describe("the games list", () => {
  it("renders rows from the API grouped by day, each naming the other three seats", async () => {
    const day = (y: number, m: number, d: number, h: number) => new Date(y, m, d, h).getTime() / 1000;
    routes["GET /api/me/games?limit=20"] = { status: 200, body: {
      games: [row("g1", day(2026, 10, 8, 21)), row("g3", day(2026, 10, 8, 20)),
              row("g2", day(2026, 10, 7, 9), { seat: 1, incomplete: true,
                                                final_levels: null, games_won: null, rounds: [2] })],
      next_before: null } };
    await mount();
    const days = qa(".grp-section");
    expect(days).toHaveLength(2);
    expect(days[0].querySelectorAll(".games-day-row")).toHaveLength(2);
    expect(days[1].querySelectorAll(".games-day-row")).toHaveLength(1);
    const rows = qa(".games-day-row");
    expect(rows[0].querySelector(".games-row-title")?.textContent).toBe("ABCD · Bot 1, Bea, Bot 3");
    expect(rows[0].textContent).toContain("3 rounds");
    expect(rows[0].textContent).toContain("Levels 5–3");
    expect(rows[0].parentElement!.querySelector(".games-replay")?.textContent).toBe("Replay");
    expect(rows[0].querySelector(".games-tag")).toBeNull();
    // seat 1: the others are seats 2, 3 and 0
    expect(rows[2].querySelector(".games-row-title")?.textContent).toBe("ABCD · Bea, Bot 3, Ana");
    expect(rows[2].textContent).toContain("1 round");
    expect(rows[2].querySelector(".games-tag")?.textContent).toBe("incomplete");
    expect(button("Load more")).toBeUndefined();
    expect(calls[0]).toEqual({ url: "/api/me/games?limit=20", method: "GET" });
    const init = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0][1] as RequestInit;
    expect(init.credentials).toBe("same-origin");
  });

  it("names a day Today, Yesterday or by its date", () => {
    const now = new Date(2026, 10, 11, 15);
    expect(dayLabel(new Date(2026, 10, 11, 1).getTime() / 1000, now)).toBe("Today");
    expect(dayLabel(new Date(2026, 10, 10, 23).getTime() / 1000, now)).toBe("Yesterday");
    expect(dayLabel(new Date(2026, 10, 8, 12).getTime() / 1000, now)).not.toMatch(/Today|Yesterday|2026/);
    expect(dayLabel(new Date(2025, 10, 8, 12).getTime() / 1000, now)).toContain("2025");
  });

  it("loads more with next_before until the server has no more", async () => {
    // The cursor is opaque: sent back exactly as the server gave it.
    routes["GET /api/me/games?limit=20"] = { status: 200, body: { games: [row("g1", 300)], next_before: "300:g1" } };
    routes["GET /api/me/games?limit=20&before=300%3Ag1"] = { status: 200, body: { games: [row("g0", 300)], next_before: null } };
    await mount();
    expect(qa(".games-day-row")).toHaveLength(1);
    await click(button("Load more"));
    expect(calls.map((c) => c.url)).toContain("/api/me/games?limit=20&before=300%3Ag1");
    expect(qa(".games-day-row")).toHaveLength(2);
    expect(button("Load more")).toBeUndefined();
  });

  it("asks a signed-out visitor to sign in (401)", async () => {
    routes["GET /api/me/games?limit=20"] = { status: 401, body: { detail: "not signed in" } };
    await mount();
    expect(q(".games-status")?.textContent).toContain("Sign in to see your saved games.");
    expect(qa(".games-day-row")).toHaveLength(0);
  });

  it("says an unknown game is unavailable (404)", async () => {
    routes["GET /api/me/games?limit=20"] = { status: 200, body: { games: [], next_before: null } };
    await mount({ page: "game", id: "nope" });
    expect(q(".games-status")?.textContent).toContain("This game isn't available");
  });
});

describe("a game", () => {
  beforeEach(() => {
    routes["GET /api/me/games?limit=20"] = { status: 200, body: {
      games: [row("g1", 1_790_000_000), row("g2", 1_789_000_000)], next_before: null } };
    routes["GET /api/me/games/g1"] = { status: 200, body: { ...row("g1", 1_790_000_000), round_results: [
      { round: 1, seat: 0, level: "2", banker: 0, result: { winner_team: 0, level_change: 2, attacker_points: 35 } },
      { round: 2, seat: 0, level: "J", banker: 1, result: { winner_team: 1, level_change: 1, attacker_points: 90 } },
    ] } };
  });

  it("lists its rounds with results and a Replay for each", async () => {
    await mount();
    await click(qa(".games-day-row")[0]);
    const rounds = qa(".games-round");
    expect(rounds.map((r) => r.querySelector(".games-round-n")?.textContent)).toEqual(["Round 1", "Round 2", "Round 3"]);
    expect(rounds[0].querySelector(".games-round-res")?.textContent).toBe("Level 2 · Defender · Won");
    expect(rounds[1].querySelector(".games-round-res")?.textContent).toBe("Level J · Attacker · Lost");
    expect(rounds[2].querySelector(".games-round-res")?.textContent).toBe("Unfinished");
    expect(rounds.every((r) => r.querySelector("button")?.textContent === "Replay")).toBe(true);
  });

  it("Remove from my games needs two taps, sends DELETE and drops the row", async () => {
    routes["DELETE /api/me/games/g1"] = { status: 204 };
    await mount();
    await click(qa(".games-day-row")[0]);
    await click(button("Remove from my games"));
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);
    routes["GET /api/me/games?limit=20"] = { status: 200, body: { games: [row("g2", 1_789_000_000)], next_before: null } };
    await click(button("Tap again to remove"));
    expect(calls.filter((c) => c.method === "DELETE")).toEqual([{ url: "/api/me/games/g1", method: "DELETE" }]);
    const rows = qa(".games-day-row");
    expect(rows).toHaveLength(1);
    expect(window.location.hash).toBe("#/games");
  });

  it("a failed DELETE keeps the game and says so", async () => {
    routes["DELETE /api/me/games/g1"] = { status: 500 };
    await mount({ page: "game", id: "g1" });
    await click(button("Remove from my games"));
    await click(button("Tap again to remove"));
    expect(q("[role=alert]")?.textContent).toContain("Could not remove the game (500)");
    expect(q(".games-title")?.textContent).toBe("Game");
  });

  it("the game page goes back to Games", async () => {
    await mount({ page: "game", id: "g1" });
    expect(q(".games-back")?.textContent).toBe("‹ Games");
  });
});

describe("rating change", () => {
  it("a ranked row shows the viewer's net change and rating after; an unranked row shows none", async () => {
    routes["GET /api/me/games?limit=20"] = { status: 200, body: {
      games: [row("up", 1_790_000_300, { rating_change: 12, rating_after: 1042, rated_rounds: 3 }),
              row("dn", 1_790_000_200, { rating_change: -8, rating_after: 1030, rated_rounds: 2 }),
              row("un", 1_790_000_100)],
      next_before: null } };
    await mount();
    const rows = qa(".games-day-row");
    const up = rows[0].querySelector(".rating-change")!;
    expect(up.textContent).toBe("▲ 12");
    expect(up.classList.contains("delta-up")).toBe(true);
    expect(rows[0].querySelector(".games-row-rating-after")?.textContent).toBe((1042).toLocaleString());
    const dn = rows[1].querySelector(".rating-change")!;
    expect(dn.textContent).toBe("▼ 8");
    expect(dn.classList.contains("delta-dn")).toBe(true);
    expect(rows[2].querySelector(".games-row-rating")).toBeNull();
    expect(rows[2].querySelector(".rating-change")).toBeNull();
  });

  it("the game page shows the net change and each rated round's change", async () => {
    routes["GET /api/me/games/g1"] = { status: 200, body: {
      ...row("g1", 1_790_000_000, { rating_change: 5, rating_after: 1005, rated_rounds: 2 }),
      round_results: [
        { round: 1, seat: 0, result: { winner_team: 0, level_change: 2 }, rating_delta: 9 },
        { round: 2, seat: 0, result: { winner_team: 1, level_change: 1 }, rating_delta: -4 },
        { round: 3, seat: 0, result: { winner_team: 0, level_change: 0 } },
      ] } };
    await mount({ page: "game", id: "g1" });
    const head = q(".games-meta-rating")!;
    expect(head.textContent).toBe(`Rating ▲ 5 · ${(1005).toLocaleString()}`);
    const rounds = qa(".games-round");
    expect(rounds.map((r) => r.querySelector(".games-round-delta")?.textContent ?? null))
      .toEqual(["▲ 9", "▼ 4", null]);
    expect(rounds[1].querySelector(".games-round-delta")!.classList.contains("delta-dn")).toBe(true);
  });

  it("an unranked game page shows no rating", async () => {
    routes["GET /api/me/games/g1"] = { status: 200, body: { ...row("g1", 1_790_000_000), round_results: [
      { round: 1, seat: 0, result: { winner_team: 0, level_change: 2 } }] } };
    await mount({ page: "game", id: "g1" });
    expect(q(".games-meta-rating")).toBeNull();
    expect(q(".rating-change")).toBeNull();
  });
});

describe("the replay page", () => {
  it("opens from a round, steps plays and tricks, and ends on the result", async () => {
    routes["GET /api/me/games/g1/rounds/3"] = { status: 200, body: roundFixture };
    await mount({ page: "replay", id: "g1", round: 3 });
    expect(calls.map((c) => c.url)).toContain("/api/me/games/g1/rounds/3");
    expect(q(".replay-caption")?.textContent).toContain("Bot 3 declared ♣4");
    expect(qa(".replay-hand .hand-slot")).toHaveLength(25);
    await click(button("Next play"));
    expect(q(".replay-caption")?.textContent).toContain("You buried");
    await click(button("Next play"));
    expect(q(".replay-caption")?.textContent).toMatch(/^Trick 1: You led/);
    expect(qa(".trick-area .trick-play")).toHaveLength(1);
    const handAfterLead = qa(".replay-hand .hand-slot").length;
    expect(handAfterLead).toBeLessThan(25);
    await click(button("Next trick"));
    expect(qa(".trick-area .trick-play")).toHaveLength(4);
    expect(q(".trick-area .win-tag")).not.toBeNull();
    await click(button("Previous play"));
    expect(qa(".trick-area .trick-play")).toHaveLength(3);
    // jump to the last trick, then step to the end
    const jump = q(".replay-jump") as HTMLSelectElement;
    const lastTrick = jump.options[jump.options.length - 1].value;
    act(() => {
      jump.value = lastTrick;
      jump.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(q(".replay-caption")?.textContent).toContain(`Trick ${lastTrick}:`);
    while (!button("Next play").disabled) await click(button("Next play"));
    expect(q(".replay-result")?.textContent).toContain("Your team lost the round");
    expect(q(".replay-result")?.textContent).toContain("Attackers scored 110 points");
    expect(qa(".replay-hand .hand-slot")).toHaveLength(0);
    expect(button("Show other hands")).toBeDefined();
    expect(q(".chat-launch")).toBeNull();
  });

  it("an unfinished round shows only the played cards and says so", async () => {
    const events = (roundFixture.events as { e: string; deck?: (string | null)[] }[]);
    const cut = events.findIndex((e) => e.e === "trick") + 2;
    routes["GET /api/me/games/g1/rounds/3"] = { status: 200, body: { ...roundFixture, finished: false,
      events: events.slice(0, cut).map((e) => (e.e === "round_start"
        ? { ...e, deck: e.deck!.map((c, i) => (i < 100 && i % 4 === 0 ? c : null)) } : e)) } };
    await mount({ page: "replay", id: "g1", round: 3 });
    expect(q(".replay-note")?.textContent).toContain("did not finish");
    while (!button("Next play").disabled) await click(button("Next play"));
    expect(q(".replay-result")).toBeNull();
    expect(qa(".trick-area .trick-play")).toHaveLength(1);
    expect(button("Show other hands")).toBeUndefined();
  });

  it("a round outside the account's interval is unavailable (404)", async () => {
    await mount({ page: "replay", id: "g1", round: 9 });
    expect(q(".games-status")?.textContent).toContain("This game isn't available");
  });
});

it("review: an authoritative empty refresh removes the last deleted cached game", async () => {
  const key = "review:deleted-game";
  remember(key, {status:"ready", games:[row("deleted",100)], next:null, more:false, moreError:false});
  routes["GET /api/me/games?limit=20"] = {status:200,body:{games:[],next_before:null}};
  host=document.createElement("div"); document.body.appendChild(host); root=createRoot(host);
  await act(async()=>{root.render(<SavedGames cacheKey={key} onPlay={()=>{}} />);});
  await settle();
  expect(host.textContent).toContain("No saved games yet");
  expect(host.textContent).not.toContain("ABCD");
});

it("review: remove last game through cached Me history reaches empty state", async () => {
  function CachedHost() {
    const route=useGamesRoute();
    return route?.page === "list" ? <SavedGames cacheKey="review:actual-delete" onPlay={()=>{}} /> : route ? <GamesList route={route} /> : null;
  }
  routes["GET /api/me/games?limit=20"]={status:200,body:{games:[row("g1",1790000000)],next_before:null}};
  routes["GET /api/me/games/g1"]={status:200,body:{...row("g1",1790000000),round_results:[]}};
  routes["DELETE /api/me/games/g1"]={status:204};
  act(()=>navigate({page:"list"}));
  host=document.createElement("div");document.body.appendChild(host);root=createRoot(host);
  await act(async()=>{root.render(<CachedHost />);});await settle();
  await click(qa(".games-day-row")[0]);
  await click(button("Remove from my games"));
  routes["GET /api/me/games?limit=20"]={status:200,body:{games:[],next_before:null}};
  await click(button("Tap again to remove"));
  expect(calls.some(c=>c.method === "DELETE")).toBe(true);
  expect(host.textContent).toContain("No saved games yet");
});

describe("a cached list on refresh", () => {
  const ready = (games: GameRow[], next: string | null) =>
    ({ status: "ready", games, next, more: false, moreError: false });
  const renderList = async (key: string) => {
    act(() => navigate({ page: "list" }));
    host = document.createElement("div");
    document.body.appendChild(host);
    root = createRoot(host);
    await act(async () => { root.render(<SavedGames cacheKey={key} onPlay={() => {}} />); });
    await settle();
  };

  it("a first page with a continuation keeps the older pages already loaded and their cursor", async () => {
    const key = "test:continuation";
    remember(key, ready([row("new", 300), row("mid", 200), row("old", 100)], "c-old"));
    routes["GET /api/me/games?limit=20"] = { status: 200, body: { games: [row("new", 300)], next_before: "c-new" } };
    await renderList(key);
    expect(qa(".games-day-row")).toHaveLength(3);
    routes["GET /api/me/games?limit=20&before=c-old"] = { status: 200, body: { games: [row("oldest", 50)], next_before: null } };
    await click(button("Load more"));
    expect(calls.map((c) => c.url)).toContain("/api/me/games?limit=20&before=c-old");
    expect(qa(".games-day-row")).toHaveLength(4);
    expect(button("Load more")).toBeUndefined();
  });

  it("a final first page replaces the cached rows, dropping ones the server no longer has", async () => {
    const key = "test:final";
    remember(key, ready([row("keep", 300), row("gone", 200)], "c1"));
    routes["GET /api/me/games?limit=20"] = { status: 200, body: { games: [row("keep", 300)], next_before: null } };
    await renderList(key);
    expect(qa(".games-day-row")).toHaveLength(1);
    expect(button("Load more")).toBeUndefined();
  });
});
