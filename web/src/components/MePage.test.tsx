// The Me tab: identity, Stats and Games in one page, the account's settings
// rows, and the two-step Delete account.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
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
import GamesList from "./GamesList";
import { openNameEditor } from "../home/route";
import { forgetHomeSession, forgetPrivateSession } from "../home/session";
import { hapticsEnabled, setHapticsEnabled } from "../native";
import { isMuted, setMuted } from "../audio";

const JERRY = { name: "Jerry Yu", email: "j@x", picture: null, display_name: null, name_shown: "Jerry" };
const STATS = { name: "Jerry", rating: 1532, rank: 12, rounds: 412, provisional: false, levels_per_round: 0.41,
                won_pct: 58.2, defender_won_pct: 61, attacker_won_pct: 54, best_streak: 7, games_won: 34,
                week_delta: 8, history: [1491, 1532], visible: true,
                recent_games: [{ started_at: 1, ended_at: 2, rounds: 6, delta: 14, games_won: 1, partner: null,
                                 partner_bot: true, opponents_bots: 2 }] };
const GAME = { id: "g1", room_code: "KQ4X", started_at: Math.floor(Date.now() / 1000) - 60, ended_at: null, seat: 0,
               players: ["Jerry", "Sam", "Mei", "Wen"], rounds: [1, 2], final_levels: ["4", "3"],
               games_won: [0, 0], incomplete: false };

// the Sound row loads the audio module, whose first tap unlocks an AudioContext
beforeAll(() => {
  class SilentAudioContext { state = "running"; currentTime = 0; async resume() {} }
  (window as unknown as { AudioContext: unknown }).AudioContext = SilentAudioContext;
});

let calls: { url: string; method: string }[];
let deleteStatus = 204;
beforeEach(() => {
  forgetHomeSession();
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
      "Queue with a friend", "Sound", "Show me on the leaderboard", "Edit name", "How to play", "Privacy policy",
      "Support", "Sign out", "Delete account"]);
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
    expect(row.parentElement!.querySelector(".games-replay")?.textContent).toBe("Replay");
    expect(host.querySelector(".me-tile")).toBeNull();
  });

  it("the account's settings and help rows sit under Games too, below the games", async () => {
    await render("games");
    expect(rowLabels()).toEqual(["Queue with a friend", "Sound", "Show me on the leaderboard", "Edit name", "How to play",
      "Privacy policy", "Support", "Sign out", "Delete account"]);
    const list = host.querySelector(".games-day-row")!;
    const settings = host.querySelector(".me-visible")!;
    expect(list.compareDocumentPosition(settings) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("the leaderboard switch moves on the tap, says it is saving, and takes one save at a time", async () => {
    await render();
    let answer!: (r: Response) => void;
    const real = globalThis.fetch;
    globalThis.fetch = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input) !== "/api/me/leaderboard-visibility") return real(input, init);
      calls.push({ url: String(input), method: init?.method ?? "GET" });
      return new Promise<Response>((r) => { answer = r; });
    }) as typeof fetch;
    const sw = host.querySelector<HTMLButtonElement>(".me-visible")!;
    act(() => sw.click());
    expect(sw.getAttribute("aria-checked")).toBe("false");
    expect(sw.querySelector(".ios-switch")?.classList.contains("on")).toBe(false);
    expect(sw.getAttribute("aria-busy")).toBe("true");
    expect(sw.disabled).toBe(false);
    act(() => sw.click());
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(1);
    await act(async () => { answer({ status: 503, json: async () => ({}) } as Response); await new Promise((r) => setTimeout(r, 0)); });
    expect(sw.getAttribute("aria-checked")).toBe("true");
    expect(sw.getAttribute("aria-busy")).toBeNull();
    const err = host.querySelector(`#${sw.getAttribute("aria-describedby")}`)!;
    expect(err.getAttribute("role")).toBe("alert");
    expect(err.textContent).toBe("Could not save (503).");
  });

  it("a saved switch stays saved when Me is opened again", async () => {
    await render();
    await act(async () => { host.querySelector<HTMLButtonElement>(".me-visible")!.click(); await new Promise((r) => setTimeout(r, 0)); });
    act(() => root.unmount());
    host.remove();
    globalThis.fetch = vi.fn(() => new Promise<Response>(() => {})) as typeof fetch;
    await render();
    expect(host.querySelector(".me-visible")?.getAttribute("aria-checked")).toBe("false");
    expect(host.querySelector(".me-tile")).not.toBeNull();
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

  it("the delete confirmation is a dialog that takes focus, keeps Tab inside and gives it back", async () => {
    await render();
    const deleteRow = rowNamed("Delete account");
    deleteRow.focus();
    act(() => deleteRow.click());
    const dialog = host.querySelector<HTMLElement>(".me-delete-confirm")!;
    const yes = dialog.querySelector<HTMLButtonElement>(".me-delete-yes")!;
    const no = dialog.querySelector<HTMLButtonElement>(".me-delete-no")!;
    expect(document.activeElement).toBe(no);
    expect(document.getElementById(dialog.getAttribute("aria-describedby")!)?.textContent).toContain("can’t be undone");
    const key = (k: string, shift = false) =>
      act(() => { document.activeElement!.dispatchEvent(new KeyboardEvent("keydown", { key: k, shiftKey: shift, bubbles: true })); });
    key("Tab");
    expect(document.activeElement).toBe(yes);
    key("Tab");
    expect(document.activeElement).toBe(no);
    key("Tab", true);
    expect(document.activeElement).toBe(yes);
    key("Escape");
    expect(host.querySelector(".me-delete-confirm")).toBeNull();
    expect(document.activeElement).toBe(rowNamed("Delete account"));
    act(() => rowNamed("Delete account").click());
    act(() => host.querySelector<HTMLButtonElement>(".me-delete-no")!.click());
    expect(document.activeElement).toBe(rowNamed("Delete account"));
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
  it("sees the sign-in card with Google only, and the help rows", async () => {
    authState.current = { status: "out", clientId: "cid", user: null };
    await render();
    expect(host.querySelector(".me-name")?.textContent).toBe("Guest");
    expect(host.querySelector(".me-sub")?.textContent).toBe("Unranked");
    const card = host.querySelector(".signin-card")!;
    expect(card.querySelector(".google-signin")).not.toBeNull();
    expect(card.querySelector(".apple-signin")).toBeNull();
    expect(card.querySelectorAll("button:disabled")).toHaveLength(0);
    expect(card.textContent).not.toContain("Apple");
    expect(rowLabels()).toEqual(["Sound", "How to play", "Privacy policy", "Support"]);
    expect([...host.querySelectorAll("a.grp-row")].map((a) => a.getAttribute("href"))).toEqual(["/privacy", "/support"]);
    expect(calls.some((c) => c.url === "/api/me/stats")).toBe(false);
    expect(host.querySelector(".segmented")).toBeNull();
  });
});

it("review: a new account must not render previous account stats while loading", async () => {
  authState.current = {status:"in",clientId:"cid",user:JERRY};
  await render();
  expect(host.textContent).toContain("1532");
  globalThis.fetch = vi.fn(() => new Promise<Response>(() => {}));
  authState.current = {status:"out",clientId:"cid",user:null};
  await act(async () => {root.render(<MePage section="stats" />);});
  authState.current = {status:"in",clientId:"cid",user:{...JERRY,email:"a@x",name_shown:"Alice"}};
  await act(async () => {root.render(<MePage section="stats" />);});
  expect(host.textContent).not.toContain("1532");
});

describe("account changes", () => {
  const ALICE = { ...JERRY, name: "Alice Li", email: "a@x", name_shown: "Alice" };
  const ALICE_STATS = { ...STATS, name: "Alice", rating: 1404, rank: 30, rounds: 77, week_delta: -3, visible: false };
  const ok = (body: unknown) => ({ status: 200, json: async () => body }) as Response;
  let held: ((r: Response) => void)[] = [];
  let statsMode: "serve" | "hold" = "serve";
  let statsFor: typeof STATS = STATS;
  beforeEach(() => {
    held = [];
    statsMode = "serve";
    statsFor = STATS;
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      calls.push({ url, method: "GET" });
      if (url.startsWith("/api/me/games?")) return ok({ games: [GAME], next_before: null });
      if (url !== "/api/me/stats") return { status: 404, json: async () => ({}) } as Response;
      if (statsMode === "hold") return new Promise<Response>((resolve) => held.push(resolve));
      return ok(statsFor);
    }) as typeof fetch;
  });
  const as = async (state: AuthState, section: "stats" | "games" = "stats") => {
    authState.current = state;
    await act(async () => { root.render(<MePage section={section} />); });
    await settle();
  };
  const IN = (user: typeof JERRY): AuthState => ({ status: "in", clientId: "cid", user });
  const OUT: AuthState = { status: "out", clientId: "cid", user: null };
  const sub = () => host.querySelector(".me-sub")?.textContent;

  it("guest to account: the account's own stats load", async () => {
    authState.current = OUT;
    await render();
    expect(host.querySelector(".me-name")?.textContent).toBe("Guest");
    await as(IN(JERRY));
    expect(host.querySelector(".me-name")?.textContent).toBe("Jerry");
    expect(sub()).toContain("1532");
    expect(calls.filter((c) => c.url === "/api/me/stats")).toHaveLength(1);
  });

  it("account A, guest, account B: B sees only B's stats, settings and games", async () => {
    authState.current = IN(JERRY);
    await render();
    expect(sub()).toContain("1532");
    await as(OUT);
    expect(host.textContent).not.toContain("1532");
    statsMode = "hold";
    await as(IN(ALICE));
    expect(host.querySelector(".me-name")?.textContent).toBe("Alice");
    expect(host.textContent).not.toContain("1532");
    await act(async () => { held.forEach((r) => r(ok(ALICE_STATS))); });
    await settle();
    expect(sub()).toContain("1404");
    expect(host.textContent).not.toContain("1532");
    expect(host.textContent).not.toContain("412");
    expect(host.querySelector(".me-visible")?.getAttribute("aria-checked")).toBe("false");
  });

  it("a slow refresh for a new account shows loading, with no stats or settings of the previous one", async () => {
    authState.current = IN(JERRY);
    await render();
    expect(host.querySelector(".me-visible")?.getAttribute("aria-checked")).toBe("true");
    statsMode = "hold";
    await as(OUT);
    await as(IN(ALICE));
    expect(host.textContent).not.toContain("1532");
    expect(host.textContent).not.toContain("412");
    expect(host.querySelector(".lb-note[role=status]")?.textContent).toBe("Loading…");
    expect(host.querySelector(".me-visible")?.getAttribute("aria-checked")).toBe("false");
    expect(host.querySelector<HTMLButtonElement>(".me-visible")?.disabled).toBe(true);
    await act(async () => { held.forEach((r) => r(ok(ALICE_STATS))); });
    await settle();
    expect(sub()).toContain("1404");
  });

  it("a failed refresh for a new account says so instead of showing the previous one's stats", async () => {
    authState.current = IN(JERRY);
    await render();
    statsMode = "hold";
    await as(IN(ALICE));
    expect(host.textContent).not.toContain("1532");
    await act(async () => { held.forEach((r) => r({ status: 503, json: async () => ({}) } as Response)); });
    await settle();
    expect(host.textContent).not.toContain("1532");
    expect(host.querySelector(".lobby-error")?.textContent).toBe("Could not load your stats (503).");
  });

  it("a late response for the previous account is ignored and not cached", async () => {
    authState.current = IN(JERRY);
    await render();
    act(() => root.unmount());
    host.remove();
    // Jerry's cached stats are drawn while his refresh is still out
    statsMode = "hold";
    await render();
    expect(sub()).toContain("1532");
    expect(held).toHaveLength(1);
    const jerrys = held[0];
    await as(IN(ALICE));
    expect(held).toHaveLength(2);
    expect(host.textContent).not.toContain("1532");
    await act(async () => { held[1](ok(ALICE_STATS)); });
    await settle();
    expect(sub()).toContain("1404");
    await act(async () => { jerrys(ok(STATS)); });
    await settle();
    expect(sub()).toContain("1404");
    expect(host.textContent).not.toContain("1532");
    act(() => root.unmount());
    host.remove();
    await render();
    expect(sub()).toContain("1404");
  });

  it("a response from a session that ended is dropped even for the same account", async () => {
    statsMode = "hold";
    authState.current = IN(JERRY);
    await render();
    expect(held).toHaveLength(1);
    // what a confirmed sign-out does, before the page has drawn it
    forgetPrivateSession();
    await act(async () => { held[0](ok(STATS)); });
    await settle();
    expect(host.textContent).not.toContain("1532");
    expect(host.querySelector(".lb-note[role=status]")?.textContent).toBe("Loading…");
  });

  it("the same account gets its section and last stats back at once on return", async () => {
    authState.current = IN(JERRY);
    await render();
    act(() => root.unmount());
    host.remove();
    statsMode = "hold";
    await render();
    expect(sub()).toContain("1532");
    expect(host.querySelector(".me-tile")).not.toBeNull();
    expect(host.querySelector(".lb-note[role=status]")).toBeNull();
  });

  it("the games list belongs to the account that loaded it", async () => {
    authState.current = IN(JERRY);
    await render("games");
    expect(host.querySelector(".games-row-title")).not.toBeNull();
    globalThis.fetch = vi.fn(() => new Promise<Response>(() => {})) as typeof fetch;
    await as(IN(ALICE), "games");
    expect(host.querySelector(".games-row-title")).toBeNull();
  });
});

describe("removing a saved game from Me → Games", () => {
  beforeEach(() => { authState.current = { status: "in", clientId: "cid", user: JERRY }; });
  const game = (id: string, ago: number) => ({ ...GAME, id, started_at: GAME.started_at - ago });
  const ids = () => [...host.querySelectorAll(".games-day-row")].length;
  const buttonNamed = (label: string) =>
    [...host.querySelectorAll<HTMLButtonElement>("button")].find((b) => b.textContent?.trim() === label);
  const tap = async (b: HTMLElement) => { act(() => b.click()); await settle(); };

  it("a game removed from a previously loaded older page stays gone; the first page's continuation stays", async () => {
    let first = { games: [game("g1", 0)], next_before: "c1" as string | null };
    let removed = false;
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      calls.push({ url, method });
      const ok = (body: unknown) => ({ status: 200, json: async () => body }) as Response;
      if (url === "/api/me/stats") return ok(STATS);
      if (url === "/api/me/games?limit=20") return ok(first);
      if (url === "/api/me/games?limit=20&before=c1") {
        return ok({ games: removed ? [game("g3", 120)] : [game("g2", 60), game("g3", 120)], next_before: null });
      }
      if (url === "/api/me/games/g2" && method === "GET") return ok({ ...game("g2", 60), round_results: [] });
      if (url === "/api/me/games/g2" && method === "DELETE") {
        removed = true;
        return { status: 204, json: async () => { throw new Error("no body"); } } as unknown as Response;
      }
      return { status: 404, json: async () => ({}) } as Response;
    }) as typeof fetch;
    await render("games");
    await tap(buttonNamed("Load more")!);
    expect(ids()).toBe(3);

    await act(async () => { root.render(<GamesList route={{ page: "game", id: "g2" }} />); });
    await settle();
    await tap(buttonNamed("Remove from my history")!);
    await tap(buttonNamed("Tap again to remove")!);
    expect(calls.some((c) => c.method === "DELETE" && c.url === "/api/me/games/g2")).toBe(true);

    // the refreshed first page still has a continuation, so the cached older page stays
    first = { games: [game("g1", 0)], next_before: "c1" };
    await act(async () => { root.render(<MePage section="games" />); });
    expect(ids()).toBe(2);
    await settle();
    expect(ids()).toBe(2);
    expect(buttonNamed("Load more")).toBeUndefined();
  });
});

describe("pull to refresh", () => {
  beforeEach(() => { authState.current = { status: "in", clientId: "cid", user: JERRY }; });

  function pullDown() {
    const el = host.querySelector(".me-page")!;
    const fire = (type: string, y: number | null) => {
      const e = new Event(type, { bubbles: true, cancelable: true });
      Object.defineProperty(e, "touches", { value: y === null ? [] : [{ clientX: 150, clientY: y }] });
      act(() => { el.dispatchEvent(e); });
    };
    fire("touchstart", 100);
    for (let y = 110; y <= 260; y += 10) fire("touchmove", y);
    fire("touchend", null);
  }
  const count = (prefix: string) => calls.filter((c) => c.url.startsWith(prefix)).length;

  it("Stats reloads the stats through the page's cached load", async () => {
    await render();
    expect(count("/api/me/stats")).toBe(1);
    pullDown();
    await act(async () => { await new Promise((r) => setTimeout(r, 450)); });
    expect(count("/api/me/stats")).toBe(2);
    expect(count("/api/me/games")).toBe(0);
    expect(host.querySelector(".me-name")?.textContent).toBe("Jerry");
  });

  it("Games reloads the saved games' first page and the stats, once each", async () => {
    await render("games");
    expect(count("/api/me/games?")).toBe(1);
    pullDown();
    await act(async () => { await new Promise((r) => setTimeout(r, 450)); });
    expect(count("/api/me/games?")).toBe(2);
    expect(count("/api/me/stats")).toBe(2);
    expect(host.querySelector(".games-day-row .games-row-title")?.textContent).toBe("Room KQ4X · with Sam, Mei, Wen");
  });
});

describe("the Settings group", () => {
  const native = (on: boolean) => {
    if (on) (window as unknown as { Capacitor: unknown }).Capacitor = { isNativePlatform: () => true };
    else delete (window as unknown as { Capacitor?: unknown }).Capacitor;
  };
  afterEach(() => {
    native(false);
    setHapticsEnabled(true);
    setMuted(false);
  });
  const head = () => host.querySelector(".grp-head#me-settings-head");
  const group = () => host.querySelector("ul.me-settings")!;
  const groupLabels = () => [...group().querySelectorAll(".grp-label")].map((e) => e.textContent);

  it("in the app: Sound, Haptics, the leaderboard switch and Edit name, under a Settings heading", async () => {
    native(true);
    authState.current = { status: "in", clientId: "cid", user: JERRY };
    await render();
    expect(head()?.textContent).toBe("Settings");
    expect(group().getAttribute("aria-labelledby")).toBe("me-settings-head");
    expect(groupLabels()).toEqual(["Sound", "Haptics", "Show me on the leaderboard", "Edit name"]);
  });

  it("Haptics is a switch that turns haptic() off and is remembered", async () => {
    native(true);
    authState.current = { status: "in", clientId: "cid", user: JERRY };
    await render();
    const sw = () => host.querySelector<HTMLButtonElement>(".me-haptics")!;
    expect(sw().getAttribute("role")).toBe("switch");
    expect(sw().getAttribute("aria-checked")).toBe("true");
    act(() => sw().click());
    expect(sw().getAttribute("aria-checked")).toBe("false");
    expect(hapticsEnabled()).toBe(false);
    expect(localStorage.getItem("shengji.haptics")).toBe("0");
    act(() => sw().click());
    expect(hapticsEnabled()).toBe(true);
    expect(localStorage.getItem("shengji.haptics")).toBe("1");
  });

  it("Sound is a switch on the shared mute store", async () => {
    authState.current = { status: "in", clientId: "cid", user: JERRY };
    await render();
    const sw = () => host.querySelector<HTMLButtonElement>(".me-sound")!;
    expect(sw().getAttribute("aria-checked")).toBe("true");
    act(() => sw().click());
    expect(isMuted()).toBe(true);
    expect(sw().getAttribute("aria-checked")).toBe("false");
    act(() => setMuted(false));
    expect(sw().getAttribute("aria-checked")).toBe("true");
  });

  it("a browser has no Haptics row; a guest gets the device rows only", async () => {
    authState.current = { status: "out", clientId: "cid", user: null };
    await render();
    expect(groupLabels()).toEqual(["Sound"]);
    native(true);
    act(() => root.unmount());
    host.remove();
    await render();
    expect(groupLabels()).toEqual(["Sound", "Haptics"]);
  });

  it("a guest's sign-in card links to the leaderboard's explanation of ranked games instead of repeating it", async () => {
    authState.current = { status: "out", clientId: "cid", user: null };
    await render();
    const card = host.querySelector(".signin-card")!;
    expect(card.textContent).not.toContain("1000");
    const link = card.querySelector<HTMLButtonElement>(".me-rated-link")!;
    expect(link.textContent?.trim()).toBe("How ranked games work");
    act(() => link.click());
    expect(window.location.hash).toBe("#/leaderboard");
  });
});
