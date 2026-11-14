// The home screen's tabs: the same three, Play, Leaderboard and Me, in a
// bottom tab bar on a phone and a top bar at 700px and up (an iPad, a desktop
// window), neither over a game; the old Stats and Games deep links open Me on
// that switch.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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

/** A window `width` px wide (true: a desktop window, false: a phone):
 *  min-width queries answer by it, every other query is false. */
function viewport(width: number | boolean) {
  const px = width === true ? 1440 : width === false ? 390 : width;
  window.matchMedia = ((q: string) => {
    const min = /^\(min-width: (\d+)px\)$/.exec(q);
    return { matches: min ? px >= Number(min[1]) : false, media: q, addEventListener() {}, removeEventListener() {} };
  }) as unknown as typeof window.matchMedia;
}
const BREAKPOINTS: [string, number][] = [["phone", 390], ["iPad portrait", 768], ["iPad", 1024], ["desktop", 1440]];

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
    expect(items.slice(0, 2).every((b) => b.querySelector("svg"))).toBe(true);
    // signed in, Me shows the account's initial in place of the person icon
    expect(items[2].querySelector("svg")).toBeNull();
    expect(items[2].querySelector(".avatar")?.getAttribute("data-initial")).toBe("J");
    expect(host.querySelector(".topbar")).toBeNull();
    expect(host.querySelector(".lobby-panel")).not.toBeNull();
  });

  it("a guest's Me tab shows the initial of the name they play under", async () => {
    signedIn = false;
    await renderApp();
    const { guestName } = await import("./guestName");
    const me = () => [...host.querySelectorAll<HTMLButtonElement>(".tabbar .tabbar-item")][2];
    expect(me().textContent).toBe("Me");
    act(() => guestName.setName("Gentle Tractor"));
    expect(me().querySelector("svg")).toBeNull();
    expect(me().querySelector(".avatar")?.getAttribute("data-initial")).toBe("G");
  });

  for (const [label, width] of BREAKPOINTS) {
    it(`the same three tabs, Play, Leaderboard and Me, on a ${label} (${width}px)`, async () => {
      viewport(width);
      await renderApp();
      const sel = width >= 700 ? ".topbar-tabs .topbar-tab" : ".tabbar .tabbar-item";
      const tabs = () => [...host.querySelectorAll<HTMLButtonElement>(sel)];
      expect(tabs().map((b) => b.textContent)).toEqual(["Play", "Leaderboard", "Me"]);
      expect(host.querySelector(width >= 700 ? ".tabbar" : ".topbar")).toBeNull();
      await act(async () => { tabs()[2].click(); await new Promise((r) => setTimeout(r, 0)); });
      expect(window.location.hash).toBe("#/me");
      expect(host.querySelector(".large-title")?.textContent).toBe("Me");
      expect(tabs()[2].getAttribute("aria-current")).toBe("page");
      // Stats and Games are a switch inside Me at every width
      const seg = (t: string) => [...host.querySelectorAll<HTMLButtonElement>(".me-page .segmented-btn")].find((b) => b.textContent === t)!;
      expect(seg("Stats").getAttribute("aria-pressed")).toBe("true");
      expect(host.querySelector(".me-tile")).not.toBeNull();
      await act(async () => { seg("Games").click(); await new Promise((r) => setTimeout(r, 0)); });
      expect(window.location.hash).toBe("#/me/games");
      expect(seg("Games").getAttribute("aria-pressed")).toBe("true");
      expect(host.querySelector(".large-title")?.textContent).toBe("Me");
      expect(tabs()[2].getAttribute("aria-current")).toBe("page");
      expect(host.querySelector(".games-status")?.textContent).toContain("No saved games yet");
      // who you are and the settings stay above or beside the games
      expect(host.querySelector(".me-who")).not.toBeNull();
      expect(host.querySelector(".me-visible")).not.toBeNull();
    });
  }

  it("the selected capsule follows the active tab", async () => {
    await renderApp();
    const bar = () => host.querySelector<HTMLElement>(".tabbar")!;
    expect(bar().querySelectorAll(".tabbar-capsule")).toHaveLength(1);
    expect(bar().style.getPropertyValue("--tab-index")).toBe("0");
    const { openTab } = await import("./home/route");
    await act(async () => { openTab("leaderboard"); await new Promise((r) => setTimeout(r, 0)); });
    expect(bar().style.getPropertyValue("--tab-index")).toBe("1");
    expect(host.querySelector(".tabbar-item.on")?.textContent).toBe("Leaderboard");
    await act(async () => { openTab("me"); await new Promise((r) => setTimeout(r, 0)); });
    expect(bar().style.getPropertyValue("--tab-index")).toBe("2");
  });

  it("at 700px and up the top bar has the three tabs centred and the account chip, which opens Me", async () => {
    viewport(true);
    await renderApp();
    expect(host.querySelector(".tabbar")).toBeNull();
    const tabs = () => [...host.querySelectorAll<HTMLButtonElement>(".topbar-tabs .topbar-tab")];
    expect(tabs().map((b) => b.textContent)).toEqual(["Play", "Leaderboard", "Me"]);
    // Play carries the title itself; the other tabs show the wordmark
    expect(host.querySelector(".topbar-mark")).toBeNull();
    const account = () => host.querySelector<HTMLButtonElement>(".topbar .account-pill")!;
    expect(account().textContent).toContain("Jerry");
    expect(account().getAttribute("aria-label")).toMatch(/^Jerry(, rating \d+)?, open profile$/);
    expect(host.querySelector("[role=menu]")).toBeNull();
    expect(host.querySelector(".topbar .guest-pill")).toBeNull();
    // the account chip opens Me, where the name is edited, from any tab
    await act(async () => { tabs()[1].click(); await new Promise((r) => setTimeout(r, 0)); });
    expect(host.querySelector(".topbar-mark")?.textContent).toContain("升级");
    await act(async () => { account().click(); await new Promise((r) => setTimeout(r, 0)); });
    expect(window.location.hash).toBe("#/me");
    expect(tabs()[2].getAttribute("aria-current")).toBe("page");
    expect(host.querySelector(".me-name")?.textContent).toBe("Jerry");
    expect(document.querySelector(".guest-name-sheet")).toBeNull();
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

describe("one name control", () => {
  const sheets = () => document.querySelectorAll(".guest-name-sheet");
  const done = () => act(() => document.querySelector<HTMLButtonElement>(".guest-name-sheet .btn.gold")!.click());
  const type = async (name: string) => {
    const input = document.querySelector<HTMLInputElement>(".guest-name-sheet input")!;
    const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
    act(() => { set.call(input, name); input.dispatchEvent(new Event("input", { bubbles: true })); });
  };
  for (const [label, width] of [["phone", 390], ["iPad", 1024]] as const) {
    it(`a guest's chip on Play and Edit name on Me open the same sheet (${label})`, async () => {
      signedIn = false;
      viewport(width);
      await renderApp();
      const chip = () => host.querySelector<HTMLButtonElement>(width >= 700 ? ".topbar .guest-pill" : ".lobby .guest-pill, .guest-pill")!;
      expect(sheets()).toHaveLength(0);
      act(() => chip().click());
      expect(sheets()).toHaveLength(1);
      await type("Gentle Tractor");
      done();
      expect(sheets()).toHaveLength(0);
      const { openTab } = await import("./home/route");
      await act(async () => { openTab("me"); await new Promise((r) => setTimeout(r, 0)); });
      expect(host.querySelector(".me-name")?.textContent).toBe("Gentle Tractor");
      expect(host.querySelector(".me-sub")?.textContent).toBe("Guest · not ranked");
      expect(host.querySelector(".me-who .avatar")?.textContent).toBe("G");
      const edit = [...host.querySelectorAll<HTMLButtonElement>(".grp-row")].find((r) => r.textContent?.startsWith("Edit name"))!;
      act(() => edit.click());
      expect(sheets()).toHaveLength(1);
      expect(document.querySelector<HTMLInputElement>(".guest-name-sheet input")!.value).toBe("Gentle Tractor");
      await type("Mei");
      done();
      expect(host.querySelector(".me-name")?.textContent).toBe("Mei");
      // the chip opens that same one sheet from Me too, wherever it is drawn
      if (width >= 700) {
        act(() => chip().click());
        expect(sheets()).toHaveLength(1);
        done();
      }
      await act(async () => { openTab("play"); await new Promise((r) => setTimeout(r, 0)); });
      expect(host.querySelector(".guest-pill .account-pill-name")?.textContent).toBe("Mei");
    });
  }

  it("the Play chip says Guest · not ranked with a pencil; the top bar's says Guest", async () => {
    signedIn = false;
    await renderApp();
    expect(host.querySelector(".guest-pill .account-pill-rating")?.textContent).toBe("Guest · not ranked");
    expect(host.querySelector(".guest-pill .guest-pill-edit")).not.toBeNull();
    act(() => root.unmount());
    host.remove();
    viewport(true);
    await renderApp();
    expect(host.querySelector(".topbar .guest-pill .account-pill-rating")?.textContent).toBe("Guest");
  });

  it("signed in, the account name is unchanged everywhere and the chip opens Me, not a sheet", async () => {
    await renderApp();
    expect(host.querySelector(".guest-pill")).toBeNull();
    const chip = host.querySelector<HTMLButtonElement>(".account-pill")!;
    expect(chip.textContent).toContain("Jerry");
    await act(async () => { chip.click(); await new Promise((r) => setTimeout(r, 0)); });
    expect(window.location.hash).toBe("#/me");
    expect(sheets()).toHaveLength(0);
    expect(host.querySelector(".me-name")?.textContent).toBe("Jerry");
    expect(host.querySelector(".me-sub")?.textContent).toContain("1532");
    const edit = [...host.querySelectorAll<HTMLButtonElement>(".grp-row")].find((r) => r.textContent?.startsWith("Edit name"))!;
    expect(edit.querySelector(".grp-value")?.textContent).toBe("Jerry");
  });
});

describe("tab context", () => {
  // jsdom keeps scrollTop but fires no scroll event; this sets both
  const scrollTo = (el: Element, top: number) =>
    act(() => { el.scrollTop = top; el.dispatchEvent(new Event("scroll")); });
  const tab = (label: string) =>
    [...host.querySelectorAll<HTMLButtonElement>(".tabbar-item")].find((b) => b.textContent === label)!;
  const go = (label: string) => act(async () => { tab(label).click(); await new Promise((r) => setTimeout(r, 0)); });
  const seg = (label: string) =>
    [...host.querySelectorAll<HTMLButtonElement>(".segmented-btn")].find((b) => b.textContent === label)!;

  it("returning to a tab resumes its section, period and scroll, with the last data drawn at once", async () => {
    await renderApp();
    await go("Me");
    expect(seg("Stats").getAttribute("aria-pressed")).toBe("true");
    await act(async () => { seg("Games").click(); await new Promise((r) => setTimeout(r, 0)); });
    await go("Leaderboard");
    expect(seg("This week").getAttribute("aria-pressed")).toBe("true");
    await act(async () => { seg("All time").click(); await new Promise((r) => setTimeout(r, 0)); });
    scrollTo(host.querySelector(".lb-page")!, 240);
    await go("Me");
    expect(window.location.hash).toBe("#/me/games");
    expect(seg("Games").getAttribute("aria-pressed")).toBe("true");
    // the next board request never answers: the cached board stays drawn
    const real = globalThis.fetch;
    globalThis.fetch = vi.fn((input: RequestInfo | URL, init?: RequestInit) =>
      String(input).startsWith("/api/leaderboard") ? new Promise<Response>(() => {}) : real(input, init)) as typeof fetch;
    await go("Leaderboard");
    expect(seg("All time").getAttribute("aria-pressed")).toBe("true");
    expect(host.querySelector(".lb-list")).not.toBeNull();
    expect(host.querySelector(".lb-page [role=status]")).toBeNull();
    expect(host.querySelector(".lb-page")!.scrollTop).toBe(240);
    // tapping the selected tab again goes back to the top
    await go("Leaderboard");
    expect(window.location.hash).toBe("#/leaderboard");
    expect(host.querySelector(".lb-page")!.scrollTop).toBe(0);
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
    it(`${hash} opens the ${title} tab${section ? ` on ${section}` : ""} on a phone`, async () => {
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

  // the top bar's old Stats and Games tabs live on as Me's switch
  const wideCases: [string, string, string | null][] = [
    ["#/leaderboard", "Leaderboard", null],
    ["#/stats", "Me", "Stats"],
    ["#/me", "Me", "Stats"],
    ["#/me/stats", "Me", "Stats"],
    ["#/me/games", "Me", "Games"],
    ["#/games", "Me", "Games"],
  ];
  for (const [hash, tab, section] of wideCases) {
    it(`${hash} opens the ${tab} tab${section ? ` on ${section}` : ""} at 700px and up`, async () => {
      viewport(true);
      window.history.replaceState(null, "", `/${hash}`);
      await renderApp();
      expect(host.querySelector(".large-title")?.textContent).toBe(tab);
      expect(host.querySelector(".topbar-tab[aria-current=page]")?.textContent).toBe(tab);
      if (section) {
        expect(host.querySelector(".me-page .segmented-btn[aria-pressed=true]")?.textContent).toBe(section);
      }
    });
  }

  it("a guest on #/leaderboard reads the board with the sign-in card", async () => {
    signedIn = false;
    window.history.replaceState(null, "", "/#/leaderboard");
    await renderApp();
    expect(host.querySelector(".lb-list")).not.toBeNull();
    expect(host.textContent).not.toContain("Sheng Ji bot");
    expect(host.querySelector(".lb-page .signin-card h3")?.textContent).toBe("Sign in to be ranked");
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
