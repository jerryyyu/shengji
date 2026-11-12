import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import Leaderboard from "./Leaderboard";
import { auth } from "../auth";
import { forgetHomeSession } from "../home/session";
import type { Leaderboard as Board, LeaderRow } from "../ratings/api";

vi.mock("../ws", () => ({ conn: { send: () => {}, reconnect: () => {} } }));

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
const guestWeek: Board = { ...week, me: null };

let signedIn = true;
const calls: string[] = [];
let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
beforeEach(() => {
  forgetHomeSession();
  calls.length = 0;
  signedIn = true;
  auth.reset();
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    calls.push(url);
    if (url === "/api/auth/config") return { status: 200, json: async () => ({ google_client_id: "cid" }) } as Response;
    if (url === "/api/me") return { status: 401, json: async () => ({}) } as Response;
    // like the server, `me` is the account the session cookie belongs to
    const who = auth.state.status === "in" && auth.state.user ? auth.state.user.name_shown : "Jerry";
    const body = url.endsWith("period=week") ? (signedIn ? { ...week, me: { ...week.me!, name: who } } : guestWeek)
      : { ...week, period: "all", players: [row({ rank: 1, name: "Jerry", you: true })], me: row({ rank: 1, name: "Jerry", you: true }) };
    return { status: 200, json: async () => body } as Response;
  }) as typeof fetch;
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  auth.reset();
});

async function render() {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => { root.render(<Leaderboard />); });
  await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
}

const lbCalls = () => calls.filter((c) => c.startsWith("/api/leaderboard"));

it("defaults to This week", async () => {
  await render();
  expect(lbCalls()).toEqual(["/api/leaderboard?period=week"]);
  const seg = [...host.querySelectorAll<HTMLButtonElement>(".segmented-btn")];
  expect(seg.map((b) => b.textContent)).toEqual(["This week", "All time"]);
  expect(seg[0].getAttribute("aria-pressed")).toBe("true");
  expect(host.querySelector(".large-title")?.textContent).toBe("Leaderboard");
});

it("lists the players with the bot anchor as a divider and pins the viewer's own row", async () => {
  await render();
  const listed = [...host.querySelectorAll(".lb-list")[0].querySelectorAll(".lb-row")];
  expect(listed.map((r) => r.querySelector(".lb-name-text")?.textContent ?? r.textContent))
    .toEqual(["Shrewd", "sk", "Bold", "Sheng Ji bot · 1500", "Quiet"]);
  expect(listed[3].className).toContain("anchor");
  expect(listed[3].querySelector(".lb-rank")).toBeNull();
  expect(listed[0].querySelector(".lb-rank.top")?.textContent).toBe("1");
  expect(listed[0].querySelector(".lb-delta")?.textContent).toBe("▲ 24");
  const pinned = host.querySelector(".lb-pin .lb-row.me")!;
  expect(pinned.querySelector(".lb-rank")!.textContent).toBe("26");
  expect(pinned.querySelector(".lb-name-text")!.textContent).toBe("Jerry (you)");
  expect(pinned.querySelector(".lb-delta")!.textContent).toBe("▼ 12");
});

it("marks provisional players with a new chip", async () => {
  await render();
  const chips = [...host.querySelectorAll(".lb-new")];
  expect(chips).toHaveLength(1);
  expect(chips[0].closest(".lb-row")!.textContent).toContain("Bold");
});

it("switches to all time and does not pin a row already in the list", async () => {
  await render();
  const all = [...host.querySelectorAll<HTMLButtonElement>(".segmented-btn")].find((b) => b.textContent === "All time")!;
  expect(all.getAttribute("aria-pressed")).toBe("false");
  await act(async () => { all.click(); await new Promise((r) => setTimeout(r, 0)); });
  expect(lbCalls()).toEqual(["/api/leaderboard?period=week", "/api/leaderboard?period=all"]);
  expect(all.getAttribute("aria-pressed")).toBe("true");
  expect(host.querySelectorAll(".lb-row.me")).toHaveLength(1);
  expect(host.querySelector(".lb-pin")).toBeNull();
});

it("a guest reads the board, with a sign-in card where their own row would be", async () => {
  signedIn = false;
  await act(async () => { await auth.init(); });
  expect(auth.state.status).toBe("out");
  await render();
  expect(host.querySelectorAll(".lb-list .lb-row:not(.anchor)")).toHaveLength(4);
  expect(host.querySelector(".lb-row.me")).toBeNull();
  const card = host.querySelector(".lb-pin .signin-card")!;
  expect(card.querySelector("h3")?.textContent).toBe("Sign in to be ranked");
  expect(card.querySelector(".google-signin")).not.toBeNull();
  expect(card.textContent).not.toMatch(/coming soon/i);
});

it("over a game it offers the way back", async () => {
  const back = vi.fn();
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => { root.render(<Leaderboard onBack={back} />); });
  const btn = [...host.querySelectorAll<HTMLButtonElement>("button")].find((b) => b.textContent === "‹ Back to game")!;
  act(() => btn.click());
  expect(back).toHaveBeenCalledTimes(1);
});

it("review: account change must not reuse another viewer's personalized board", async () => {
  auth.signedIn({name:"Jerry",email:"j@x",picture:null,display_name:null,name_shown:"Jerry"});
  await render();
  expect(host.textContent).toContain("Jerry (you)");
  await act(async () => { auth.signedIn({name:"Alice",email:"a@x",picture:null,display_name:null,name_shown:"Alice"}); });
  expect(host.textContent).not.toContain("Jerry (you)");
});

describe("viewer changes", () => {
  const user = (name: string) => ({ name, email: `${name.toLowerCase()}@x`, picture: null, display_name: null,
                                    name_shown: name });
  // the board as the server personalises it: the cookie's account owns `me`
  let viewer: string | null = null;
  const boardFor = (who: string | null): Board =>
    who === null ? guestWeek : { ...week, me: row({ rank: 26, name: who, rating: 1210, you: true }) };
  type Pending = { resolve: (r: Response) => void };
  let pending: Pending[] = [];
  let mode: "serve" | "hold" | "fail" = "serve";
  const ok = (body: unknown) => ({ status: 200, json: async () => body }) as Response;
  beforeEach(() => {
    viewer = null;
    pending = [];
    mode = "serve";
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      calls.push(url);
      if (url === "/api/auth/config") return ok({ google_client_id: "cid" });
      if (url === "/api/me") return { status: 401, json: async () => ({}) } as Response;
      if (url === "/api/auth/logout") return ok({});
      const body = boardFor(viewer);
      if (mode === "fail") return { status: 503, json: async () => ({}) } as Response;
      if (mode === "hold") return new Promise<Response>((resolve) => pending.push({ resolve }));
      return ok(body);
    }) as typeof fetch;
  });
  const settle = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });
  const pinnedName = () => host.querySelector(".lb-pin .lb-name-text")?.textContent ?? null;
  const signIn = async (name: string) => {
    viewer = name;
    await act(async () => { auth.signedIn(user(name)); });
    await settle();
  };
  const signOut = async () => {
    viewer = null;
    await act(async () => { await auth.signOut(); });
    await settle();
  };

  it("guest to account: the board reloads with the new account's own row", async () => {
    await act(async () => { await auth.init(); });
    await render();
    expect(host.querySelector(".lb-pin .signin-card")).not.toBeNull();
    expect(lbCalls()).toHaveLength(1);
    await signIn("Jerry");
    expect(lbCalls()).toHaveLength(2);
    expect(pinnedName()).toBe("Jerry (you)");
    expect(host.querySelector(".signin-card")).toBeNull();
  });

  it("account A, guest, account B: each sees only their own row", async () => {
    await act(async () => { await auth.init(); });
    await signIn("Jerry");
    await render();
    expect(pinnedName()).toBe("Jerry (you)");
    await signOut();
    expect(host.textContent).not.toContain("(you)");
    expect(host.querySelector(".lb-pin .signin-card")).not.toBeNull();
    await signIn("Alice");
    expect(pinnedName()).toBe("Alice (you)");
    expect(host.textContent).not.toContain("Jerry (you)");
  });

  it("a slow refresh after a viewer change shows loading, not the previous viewer's board", async () => {
    await signIn("Jerry");
    await render();
    expect(pinnedName()).toBe("Jerry (you)");
    mode = "hold";
    await signIn("Alice");
    expect(host.textContent).not.toContain("Jerry (you)");
    expect(host.querySelector(".lb-note[role=status]")?.textContent).toBe("Loading…");
    await act(async () => { pending.forEach((p) => p.resolve(ok(boardFor("Alice")))); });
    await settle();
    expect(pinnedName()).toBe("Alice (you)");
  });

  it("a failed refresh after a viewer change shows the failure, not the previous viewer's board", async () => {
    await signIn("Jerry");
    await render();
    expect(pinnedName()).toBe("Jerry (you)");
    mode = "fail";
    await signIn("Alice");
    expect(host.textContent).not.toContain("Jerry (you)");
    expect(host.querySelector(".lobby-error")?.textContent).toBe("Could not load the leaderboard (503).");
    // remounting while the server still fails does not bring Jerry's board back
    act(() => root.unmount());
    host.remove();
    await render();
    expect(host.textContent).not.toContain("Jerry (you)");
    expect(host.querySelector(".lobby-error")).not.toBeNull();
  });

  it("a late response for the previous viewer is ignored", async () => {
    await signIn("Jerry");
    mode = "hold";
    await render();
    expect(pending).toHaveLength(1);
    const jerrys = pending[0];
    await signIn("Alice");
    expect(pending).toHaveLength(2);
    await act(async () => { pending[1].resolve(ok(boardFor("Alice"))); });
    await settle();
    expect(pinnedName()).toBe("Alice (you)");
    await act(async () => { jerrys.resolve(ok(boardFor("Jerry"))); });
    await settle();
    expect(pinnedName()).toBe("Alice (you)");
    // nor was it cached for Alice: a remount draws Alice's board at once
    act(() => root.unmount());
    host.remove();
    await render();
    expect(pinnedName()).toBe("Alice (you)");
    expect(host.textContent).not.toContain("Jerry (you)");
  });

  it("signing out and back in as the same account does not draw the old session's board", async () => {
    await signIn("Jerry");
    await render();
    expect(pinnedName()).toBe("Jerry (you)");
    act(() => root.unmount());
    host.remove();
    await signOut();
    mode = "hold";
    viewer = "Jerry";
    await act(async () => { auth.signedIn(user("Jerry")); });
    await render();
    expect(host.textContent).not.toContain("(you)");
    expect(host.querySelector(".lb-note[role=status]")?.textContent).toBe("Loading…");
  });

  it("the same account gets its period and last board back at once on return", async () => {
    await signIn("Jerry");
    await render();
    const all = () => [...host.querySelectorAll<HTMLButtonElement>(".segmented-btn")].find((b) => b.textContent === "All time")!;
    await act(async () => { all().click(); });
    await settle();
    expect(host.querySelector(".lb-row.me .lb-name-text")?.textContent).toBe("Jerry (you)");
    act(() => root.unmount());
    host.remove();
    mode = "hold";
    await render();
    expect(all().getAttribute("aria-pressed")).toBe("true");
    expect(lbCalls().at(-1)).toBe("/api/leaderboard?period=all");
    expect(host.querySelector(".lb-row.me .lb-name-text")?.textContent).toBe("Jerry (you)");
    expect(host.querySelector(".lb-note[role=status]")).toBeNull();
  });

  it("signing out keeps the chosen period but forgets the board", async () => {
    await signIn("Jerry");
    await render();
    const all = () => [...host.querySelectorAll<HTMLButtonElement>(".segmented-btn")].find((b) => b.textContent === "All time")!;
    await act(async () => { all().click(); });
    await settle();
    act(() => root.unmount());
    host.remove();
    await signOut();
    mode = "hold";
    await render();
    expect(all().getAttribute("aria-pressed")).toBe("true");
    expect(host.textContent).not.toContain("(you)");
  });
});
