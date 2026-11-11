// The home screen's tabs: a bottom tab bar on a phone, a top bar at 700px and
// up, neither over a game; the old ratings deep links land on the new tabs.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { WIDE } from "./home/HomeShell";

class FakeWS {
  static all: FakeWS[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  readyState = 1;
  constructor() { FakeWS.all.push(this); }
  send() {}
  close() { this.readyState = 3; this.onclose?.(); }
  deliver(msg: unknown) { this.onmessage?.({ data: JSON.stringify(msg) }); }
}

const player = (seat: number) => ({
  seat, name: seat ? `Bot ${seat}` : "Me", is_bot: seat !== 0, connected: true, team: seat % 2,
  cards_left: 3, is_banker: seat === 1, takeover_in: null, controller: seat ? "bot" : "human",
  reserved_for: null, reserved_secs: null,
});
const playing = {
  type: "state", room: "ABCD", you: 0, phase: "play",
  players: [0, 1, 2, 3].map(player),
  hand: [{ id: 1, code: "S5" }, { id: 2, code: "H7" }, { id: 3, code: "BJ" }],
  levels: ["2", "2"], games_won: [0, 0], banker: 1, trump: { suit: "S", rank: "2", declarer: 1 },
  turn: 0, declare_options: [], current_declaration: null, passed: [], trick: { leader: 0, plays: [] },
  last_trick: null, attacker_points: 0, kitty_count: 8, message: null, notice: null, round_result: null,
};
const STATS = { name: "Jerry", rating: 1532, rank: 12, rounds: 80, provisional: false, levels_per_round: 0.4,
                won_pct: 58, defender_won_pct: 61, attacker_won_pct: 54, best_streak: 7, games_won: 3,
                week_delta: 8, history: [1500, 1532], recent_games: [], visible: true };

function viewport(wide: boolean) {
  window.matchMedia = ((q: string) => ({
    matches: q === WIDE ? wide : false, media: q, addEventListener() {}, removeEventListener() {},
  })) as unknown as typeof window.matchMedia;
}

let signedIn = true;
let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
const realMatchMedia = window.matchMedia;
beforeEach(() => {
  FakeWS.all = [];
  signedIn = true;
  localStorage.clear();
  viewport(false);
  (globalThis as unknown as { WebSocket: unknown }).WebSocket = FakeWS;
  (window as unknown as { AudioContext: unknown }).AudioContext = class {
    state = "running";
    resume() { return Promise.resolve(); }
  };
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if ((url === "/api/me" || url.startsWith("/api/me/")) && !signedIn) {
      return { status: 401, json: async () => ({}) } as Response;
    }
    const body = url === "/api/auth/config" ? { google_client_id: "cid" }
      : url === "/api/me" ? { name: "Jerry Yu", email: "j@x", picture: null, display_name: null, name_shown: "Jerry" }
      : url === "/api/me/stats" ? STATS
      : url.startsWith("/api/me/games?") ? { games: [], next_before: null }
      : url.startsWith("/api/leaderboard") ? { period: "week", players: [], me: null, anchor: { name: "Sheng Ji bot", rating: 1500 } }
      : null;
    return { status: body ? 200 : 404, json: async () => body ?? {} } as Response;
  }) as typeof fetch;
  vi.resetModules();
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  window.matchMedia = realMatchMedia;
  window.history.replaceState(null, "", "/");
});

const settle = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });

async function renderApp(opts: { resume?: boolean } = {}) {
  const { default: App } = await import("./App");
  if (opts.resume) {
    const { saveRoom, saveName } = await import("./ws");
    saveName("Me");
    saveRoom("ABCD");
  }
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => { root.render(<App />); });
  await settle();
}

describe("the bars", () => {
  it("a phone gets the bottom tab bar, Play selected, and no top bar", async () => {
    await renderApp();
    const items = [...host.querySelectorAll<HTMLButtonElement>(".tabbar .tabbar-item")];
    expect(items.map((b) => b.textContent)).toEqual(["Play", "Leaderboard", "Me"]);
    expect(items[0].getAttribute("aria-current")).toBe("page");
    expect(items.every((b) => b.querySelector("svg"))).toBe(true);
    expect(host.querySelector(".topbar")).toBeNull();
    expect(host.querySelector(".lobby-panel")).not.toBeNull();
  });

  it("at 700px and up the tabs move into a top bar with the account chip", async () => {
    viewport(true);
    await renderApp();
    expect(host.querySelector(".tabbar")).toBeNull();
    const tabs = [...host.querySelectorAll<HTMLButtonElement>(".topbar-tabs .topbar-tab")];
    expect(tabs.map((b) => b.textContent)).toEqual(["Play", "Leaderboard"]);
    expect(host.querySelector(".topbar-mark")?.textContent).toContain("升级");
    const account = host.querySelector<HTMLButtonElement>(".topbar-account")!;
    expect(account.textContent).toContain("Jerry");
    act(() => account.click());
    const items = [...host.querySelectorAll<HTMLButtonElement>(".topbar-menu [role=menuitem]")];
    expect(items.map((b) => b.textContent)).toEqual(["Me", "My games", "How to play", "Privacy", "Support"]);
    await act(async () => { items[0].click(); await new Promise((r) => setTimeout(r, 0)); });
    expect(window.location.hash).toBe("#/me");
    expect(host.querySelector(".me-page")).not.toBeNull();
  });

  it("a guest at 700px gets a Sign in button that opens Me", async () => {
    signedIn = false;
    viewport(true);
    await renderApp();
    const signIn = host.querySelector<HTMLButtonElement>(".topbar-signin")!;
    expect(signIn.textContent).toBe("Sign in");
    await act(async () => { signIn.click(); await new Promise((r) => setTimeout(r, 0)); });
    expect(host.querySelector(".me-page .signin-card")).not.toBeNull();
  });

  for (const wide of [false, true]) {
    it(`neither bar shows in a game (${wide ? "wide" : "phone"})`, async () => {
      viewport(wide);
      await renderApp({ resume: true });
      const ws = FakeWS.all[0];
      act(() => ws.onopen?.());
      act(() => ws.deliver(playing));
      expect(host.querySelector(".table, .hand")).not.toBeNull();
      expect(host.querySelector(".tabbar")).toBeNull();
      expect(host.querySelector(".topbar")).toBeNull();
    });
  }

  it("neither bar shows in How to play", async () => {
    window.history.replaceState(null, "", "/#/howto");
    await renderApp();
    expect(host.querySelector(".tabbar")).toBeNull();
    expect(host.querySelector(".topbar")).toBeNull();
  });

  it("the tab bar switches tabs through the hash", async () => {
    await renderApp();
    const tab = (label: string) =>
      [...host.querySelectorAll<HTMLButtonElement>(".tabbar-item")].find((b) => b.textContent === label)!;
    await act(async () => { tab("Leaderboard").click(); await new Promise((r) => setTimeout(r, 0)); });
    expect(window.location.hash).toBe("#/leaderboard");
    expect(host.querySelector(".large-title")?.textContent).toBe("Leaderboard");
    expect(tab("Leaderboard").getAttribute("aria-current")).toBe("page");
    await act(async () => { tab("Play").click(); await new Promise((r) => setTimeout(r, 0)); });
    expect(window.location.hash).toBe("");
    expect(host.querySelector(".lobby-panel")).not.toBeNull();
  });
});

describe("deep links", () => {
  const cases: [string, string, string | null][] = [
    ["#/leaderboard", "Leaderboard", null],
    ["#/stats", "Me", "Stats"],
    ["#/me", "Me", "Stats"],
    ["#/me/games", "Me", "Games"],
    ["#/games", "Me", "Games"],
  ];
  for (const [hash, title, section] of cases) {
    it(`${hash} opens the ${title} tab${section ? ` on ${section}` : ""}`, async () => {
      window.history.replaceState(null, "", `/${hash}`);
      await renderApp();
      expect(host.querySelector(".large-title")?.textContent).toBe(title);
      const current = host.querySelector(".tabbar-item[aria-current=page]")?.textContent;
      expect(current).toBe(title);
      if (section) {
        expect(host.querySelector(".segmented-btn[aria-pressed=true]")?.textContent).toBe(section);
      }
    });
  }

  it("a guest on #/leaderboard reads the board with the sign-in card", async () => {
    signedIn = false;
    window.history.replaceState(null, "", "/#/leaderboard");
    await renderApp();
    expect(host.querySelector(".lb-row.anchor")?.textContent).toContain("Sheng Ji bot");
    expect(host.querySelector(".lb-pin .signin-card h3")?.textContent).toBe("Sign in to be ranked");
  });

  it("a saved game's page and its replay keep their routes, without the bars", async () => {
    window.history.replaceState(null, "", "/#/games/g1");
    await renderApp();
    expect(host.querySelector(".games-title")?.textContent).toBe("Game");
    expect(host.querySelector(".tabbar")).toBeNull();
  });

  it("over a game the tabs' pages offer the way back instead of the bars", async () => {
    await renderApp({ resume: true });
    const ws = FakeWS.all[0];
    act(() => ws.onopen?.());
    act(() => ws.deliver(playing));
    await act(async () => { window.location.hash = "#/leaderboard"; await new Promise((r) => setTimeout(r, 0)); });
    expect(host.querySelector(".large-title")?.textContent).toBe("Leaderboard");
    expect(host.querySelector(".tabbar")).toBeNull();
    const back = [...host.querySelectorAll<HTMLButtonElement>("button")].find((b) => b.textContent === "‹ Back to game")!;
    await act(async () => { back.click(); await new Promise((r) => setTimeout(r, 0)); });
    expect(host.querySelector(".table, .hand")).not.toBeNull();
  });
});
