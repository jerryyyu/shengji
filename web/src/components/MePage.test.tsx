// The Me tab: identity, Stats and Games in one page, the account's settings
// rows, and the two-step Delete account.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AuthState } from "../auth";

const { authState, signOut, deleted, updated } = vi.hoisted(() => ({
  authState: { current: { status: "loading", clientId: null, user: null } as AuthState },
  signOut: vi.fn(() => Promise.resolve()),
  deleted: vi.fn(),
  updated: vi.fn(),
}));
vi.mock("../ws", () => ({ conn: { send: () => {}, reconnect: () => {} } }));
vi.mock("../auth", async (importOriginal) => {
  const real = await importOriginal<typeof import("../auth")>();
  return { ...real, useAuth: () => authState.current, auth: { signOut, deleted, updated, signedIn: vi.fn() } };
});

import MePage from "./MePage";
import { openNameEditor } from "../home/route";

const JERRY = { name: "Jerry Yu", email: "j@x", picture: null, display_name: null, name_shown: "Jerry" };
const STATS = { name: "Jerry", rating: 1532, rank: 12, rounds: 412, provisional: false, levels_per_round: 0.41,
                won_pct: 58.2, defender_won_pct: 61, attacker_won_pct: 54, best_streak: 7, games_won: 34,
                week_delta: 8, history: [1491, 1532], visible: true,
                recent_games: [{ started_at: 1, ended_at: 2, rounds: 6, delta: 14, games_won: 1, partner: null,
                                 partner_bot: true, opponents_bots: 2 }] };
const GAME = { id: "g1", room_code: "KQ4X", started_at: Math.floor(Date.now() / 1000) - 60, ended_at: null, seat: 0,
               players: ["Jerry", "Sam", "Mei", "Wen"], rounds: [1, 2], final_levels: ["4", "3"],
               games_won: [0, 0], incomplete: false };

let calls: { url: string; method: string }[];
let deleteStatus = 204;
beforeEach(() => {
  calls = [];
  deleteStatus = 204;
  signOut.mockClear();
  deleted.mockClear();
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    calls.push({ url, method });
    if (method === "DELETE" && url === "/api/me") return { status: deleteStatus, json: async () => { throw new Error("no body"); } } as unknown as Response;
    if (method === "POST" && url === "/api/me/leaderboard-visibility") {
      return { status: 200, json: async () => JSON.parse(String(init?.body)) } as Response;
    }
    const body = url === "/api/me/stats" ? STATS
      : url.startsWith("/api/me/games?") ? { games: [GAME], next_before: null } : null;
    return { status: body ? 200 : 404, json: async () => body ?? {} } as Response;
  }) as typeof fetch;
});

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  window.history.replaceState(null, "", "/");
});

const settle = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });
async function render(section: "stats" | "games" = "stats") {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => { root.render(<MePage section={section} />); });
  await settle();
}
const rowLabels = () => [...host.querySelectorAll(".grp-row .grp-label")].map((e) => e.textContent);
const rowNamed = (label: string) =>
  [...host.querySelectorAll<HTMLElement>(".grp-row")].find((r) => r.querySelector(".grp-label")?.textContent === label)!;

describe("signed in", () => {
  beforeEach(() => { authState.current = { status: "in", clientId: "cid", user: JERRY }; });

  it("Stats: the identity header, three tiles, the counts and the settings; no recent-games rows", async () => {
    await render();
    expect(host.querySelector(".large-title")?.textContent).toBe("Me");
    expect(host.querySelector(".me-name")?.textContent).toBe("Jerry");
    expect(host.querySelector(".me-sub")?.textContent).toBe("1532 · #12 all time · ▲ 8 this week");
    const tiles = [...host.querySelectorAll(".me-tile")].map((t) => t.textContent);
    expect(tiles).toEqual(["58%rounds won", "+0.41levels / round", "7best streak"]);
    expect(rowLabels()).toEqual(["Games won", "Rounds played", "Won as defenders", "Won as attackers",
      "Show me on the leaderboard", "Edit name", "How to play", "Privacy policy", "Support",
      "Sign out", "Delete account"]);
    expect(host.textContent).not.toContain("With a bot partner");
    expect(host.querySelector(".me-delete")?.className).toContain("destructive");
    expect(host.querySelector(".segmented-btn[aria-pressed=true]")?.textContent).toBe("Stats");
  });

  it("merges stats and games: the Games segment lists the saved games by day with Replay", async () => {
    await render();
    const games = [...host.querySelectorAll<HTMLButtonElement>(".segmented-btn")].find((b) => b.textContent === "Games")!;
    act(() => games.click());
    expect(window.location.hash).toBe("#/me/games");
    act(() => root.unmount());
    host.remove();
    await render("games");
    expect(host.querySelector(".me-name")?.textContent).toBe("Jerry");
    expect(host.querySelector(".grp-head")?.textContent).toBe("Today");
    const row = host.querySelector(".games-day-row")!;
    expect(row.querySelector(".games-row-title")?.textContent).toBe("Room KQ4X · with Sam, Mei, Wen");
    expect(row.querySelector(".games-replay")?.textContent).toBe("Replay");
    expect(host.querySelector(".me-tile")).toBeNull();
    expect(host.querySelector(".me-delete")).toBeNull();
  });

  it("the leaderboard switch saves and follows the stored choice", async () => {
    await render();
    const sw = host.querySelector<HTMLButtonElement>(".me-visible")!;
    expect(sw.getAttribute("aria-checked")).toBe("true");
    await act(async () => { sw.click(); await new Promise((r) => setTimeout(r, 0)); });
    expect(calls.filter((c) => c.method === "POST").map((c) => c.url)).toEqual(["/api/me/leaderboard-visibility"]);
    expect(sw.getAttribute("aria-checked")).toBe("false");
  });

  it("the account menu's Edit name opens Me with the form already open", async () => {
    openNameEditor();
    await render();
    expect(host.querySelector<HTMLInputElement>(".name-edit-input")?.value).toBe("Jerry");
  });

  it("Edit name opens the inline form; Sign out signs out", async () => {
    await render();
    act(() => rowNamed("Edit name").click());
    expect(host.querySelector<HTMLInputElement>(".name-edit-input")?.value).toBe("Jerry");
    await act(async () => { rowNamed("Sign out").click(); });
    expect(signOut).toHaveBeenCalledTimes(1);
  });

  it("Delete account calls DELETE /api/me only after the in-page confirmation, then returns to Play", async () => {
    window.history.replaceState(null, "", "/#/me");
    await render();
    act(() => rowNamed("Delete account").click());
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);
    const dialog = host.querySelector(".me-delete-confirm")!;
    expect(dialog.getAttribute("role")).toBe("alertdialog");
    expect(dialog.textContent).toContain("can’t be undone");
    // Cancel backs out without a request
    act(() => dialog.querySelector<HTMLButtonElement>(".me-delete-no")!.click());
    expect(host.querySelector(".me-delete-confirm")).toBeNull();
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);
    act(() => rowNamed("Delete account").click());
    await act(async () => {
      host.querySelector<HTMLButtonElement>(".me-delete-yes")!.click();
      await new Promise((r) => setTimeout(r, 0));
    });
    expect(calls.filter((c) => c.method === "DELETE")).toEqual([{ url: "/api/me", method: "DELETE" }]);
    expect(deleted).toHaveBeenCalledTimes(1);
    expect(window.location.hash).toBe("");
  });

  it("a refused delete keeps the account and says why", async () => {
    deleteStatus = 500;
    await render();
    act(() => rowNamed("Delete account").click());
    await act(async () => {
      host.querySelector<HTMLButtonElement>(".me-delete-yes")!.click();
      await new Promise((r) => setTimeout(r, 0));
    });
    expect(deleted).not.toHaveBeenCalled();
    expect(host.querySelector(".me-delete-confirm [role=alert]")?.textContent).toContain("(500)");
  });
});

describe("a guest", () => {
  it("sees the sign-in card with Google, Apple dimmed as coming soon, and the help rows", async () => {
    authState.current = { status: "out", clientId: "cid", user: null };
    await render();
    expect(host.querySelector(".me-name")?.textContent).toBe("Guest");
    expect(host.querySelector(".me-sub")?.textContent).toBe("Not rated");
    const card = host.querySelector(".signin-card")!;
    expect(card.querySelector(".google-signin")).not.toBeNull();
    const apple = card.querySelector<HTMLButtonElement>(".apple-signin")!;
    expect(apple.disabled).toBe(true);
    expect(card.textContent).toContain("Coming soon");
    expect(rowLabels()).toEqual(["How to play", "Privacy policy", "Support"]);
    expect([...host.querySelectorAll("a.grp-row")].map((a) => a.getAttribute("href"))).toEqual(["/privacy", "/support"]);
    expect(calls.some((c) => c.url === "/api/me/stats")).toBe(false);
    expect(host.querySelector(".segmented")).toBeNull();
  });
});
