import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import {
  CASUAL_WINS, FRESH, PROMPT_DELAY_MS, RANKED_WINS, REVIEW_KEY, SESSION_GAP_MS, ReviewPrompt, appVersion,
  nativeKv, nativeRequest, parseState, recordWin, touch, type Kv, type ReviewDeps, type Trigger,
} from "./reviewPrompt";
import { useReviewPrompt } from "./useReviewPrompt";
import type { GameState } from "./protocol";

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function memoryKv(): Kv & { data: Map<string, string> } {
  const data = new Map<string, string>();
  return {
    data,
    get: async (k) => data.get(k) ?? null,
    set: async (k, v) => { data.set(k, v); },
  };
}

interface Harness {
  prompt: ReviewPrompt;
  kv: ReturnType<typeof memoryKv>;
  asked: number;
  reports: [Trigger, string][];
  clock: { now: number };
  online: { on: boolean };
}

function harness(opts: { kv?: ReturnType<typeof memoryKv>; version?: string | null; plugin?: boolean;
                         clock?: { now: number } } = {}): Harness {
  const kv = opts.kv ?? memoryKv();
  const clock = opts.clock ?? { now: 1_000_000 };
  const online = { on: true };
  const h: Harness = { prompt: null as unknown as ReviewPrompt, kv, asked: 0, reports: [], clock, online };
  const deps: ReviewDeps = {
    kv: () => kv,
    request: () => (opts.plugin === false ? null : async () => { h.asked += 1; }),
    version: () => (opts.version === undefined ? "1.0.3" : opts.version),
    report: (trigger, version) => {
      if (!online.on) return false;
      h.reports.push([trigger, version]);
      return true;
    },
    now: () => clock.now,
  };
  h.prompt = new ReviewPrompt(deps);
  return h;
}

/** First open, then a return after the gap: the second session. */
async function secondSession(h: Harness): Promise<void> {
  await h.prompt.touch();
  await h.prompt.away();
  h.clock.now += SESSION_GAP_MS;
  await h.prompt.touch();
}

async function state(h: Harness) {
  return parseState(h.kv.data.get(REVIEW_KEY) ?? null);
}

describe("review prompt rules", () => {
  it("a session starts at first open and again after 30 minutes away, not before", () => {
    let s = touch(FRESH, 100);
    expect(s).toMatchObject({ first: 100, last: 100, session: 1 });
    s = touch(s, 100 + SESSION_GAP_MS - 1);
    expect(s.session).toBe(1);
    s = touch(s, s.last + SESSION_GAP_MS);
    expect(s.session).toBe(2);
    expect(s.first).toBe(100);
  });

  it("asks at the 2nd ranked win or the 5th casual win, whichever comes first", () => {
    let s = touch(touch(FRESH, 1), 1 + SESSION_GAP_MS);
    let r = recordWin(s, "ranked", "1.0.3", 2 + SESSION_GAP_MS);
    expect(r.trigger).toBeNull();
    r = recordWin(r.state, "ranked", "1.0.3", 3 + SESSION_GAP_MS);
    expect(r.trigger).toBe("ranked2");
    expect(r.state.ranked).toBe(RANKED_WINS);

    s = touch(touch(FRESH, 1), 1 + SESSION_GAP_MS);
    for (let i = 1; i < CASUAL_WINS; i++) {
      r = recordWin(s, "casual", "1.0.3", 2 + SESSION_GAP_MS);
      expect(r.trigger).toBeNull();
      s = r.state;
    }
    r = recordWin(s, "casual", "1.0.3", 2 + SESSION_GAP_MS);
    expect(r.trigger).toBe("casual5");
  });

  it("never asks in the first session; the next win in a later session does", async () => {
    const h = harness();
    await h.prompt.touch();
    for (let i = 0; i < 6; i++) expect(await h.prompt.roundWon("casual")).toBeNull();
    expect(await h.prompt.roundWon("ranked")).toBeNull();
    expect(await h.prompt.roundWon("ranked")).toBeNull();
    // a return under 30 minutes is still the first session
    await h.prompt.away();
    h.clock.now += SESSION_GAP_MS - 1000;
    await h.prompt.touch();
    expect(await h.prompt.roundWon("casual")).toBeNull();
    await h.prompt.away();
    h.clock.now += SESSION_GAP_MS;
    await h.prompt.touch();
    expect((await state(h)).session).toBe(2);
    expect(await h.prompt.roundWon("casual")).toBe("ranked2");
  });

  it("asks once per app version, and again for a new one", async () => {
    let version = "1.0.3";
    const h = harness();
    const prompt = new ReviewPrompt({
      kv: () => h.kv, request: () => async () => { h.asked += 1; }, version: () => version,
      report: (t, v) => { h.reports.push([t, v]); return true; }, now: () => h.clock.now,
    });
    h.prompt = prompt;
    await secondSession(h);
    await prompt.roundWon("ranked");
    const trigger = await prompt.roundWon("ranked");
    expect(trigger).toBe("ranked2");
    expect(await prompt.ask(trigger!)).toBe(true);
    expect(h.asked).toBe(1);
    expect(await prompt.roundWon("ranked")).toBeNull();
    expect(await prompt.ask("ranked2")).toBe(false);
    expect(h.asked).toBe(1);
    expect((await state(h)).prompted).toBe("1.0.3");
    version = "1.0.4";
    expect(await prompt.roundWon("casual")).toBe("ranked2");
    expect(await prompt.ask("ranked2")).toBe(true);
    expect(h.asked).toBe(2);
    expect(h.reports).toEqual([["ranked2", "1.0.3"], ["ranked2", "1.0.4"]]);
  });

  it("an ask made offline is reported from the next online page, once", async () => {
    const h = harness();
    await secondSession(h);
    h.online.on = false;
    for (let i = 0; i < CASUAL_WINS; i++) await h.prompt.roundWon("casual");
    expect(await h.prompt.ask("casual5")).toBe(true);
    expect(h.reports).toEqual([]);
    expect((await state(h)).reported).toBe(false);
    h.online.on = true;
    await h.prompt.touch();
    await h.prompt.touch();
    expect(h.reports).toEqual([["casual5", "1.0.3"]]);
    expect((await state(h)).reported).toBe(true);
  });

  it("offline and online pages add to the same counts through the native store", async () => {
    const kv = memoryKv();
    const clock = { now: 5_000_000 };
    const hosted = harness({ kv, clock });
    const bundled = harness({ kv, clock });
    await secondSession(hosted);
    await bundled.prompt.touch();
    expect(await bundled.prompt.roundWon("casual")).toBeNull();
    expect(await hosted.prompt.roundWon("casual")).toBeNull();
    expect(await bundled.prompt.roundWon("casual")).toBeNull();
    expect(await hosted.prompt.roundWon("casual")).toBeNull();
    expect(await bundled.prompt.roundWon("casual")).toBe("casual5");
    expect((await state(hosted)).casual).toBe(5);
    expect((await state(hosted)).session).toBe(2);
  });

  it("does nothing without the plugin or a version", async () => {
    const noPlugin = harness({ plugin: false });
    await secondSession(noPlugin);
    for (let i = 0; i < 6; i++) expect(await noPlugin.prompt.roundWon("casual")).toBeNull();
    expect(await noPlugin.prompt.ask("casual5")).toBe(false);
    expect((await state(noPlugin)).casual).toBe(0);

    const noVersion = harness({ version: null });
    await secondSession(noVersion);
    for (let i = 0; i < 6; i++) expect(await noVersion.prompt.roundWon("casual")).toBeNull();
    expect(await noVersion.prompt.ask("casual5")).toBe(false);
    expect(noVersion.asked).toBe(0);
  });

  it("reads the version only from a bare ShengjiApp token", () => {
    expect(appVersion("Mozilla/5.0 (iPhone) AppleWebKit/605 ShengjiApp/1.0.3")).toBe("1.0.3");
    expect(appVersion("Mozilla/5.0 ShengjiApp/1.0.3 Other")).toBe("1.0.3");
    expect(appVersion("Mozilla/5.0 ShengjiApp/1.0.3beta")).toBeNull();
    expect(appVersion("Mozilla/5.0 (Macintosh) Safari/605")).toBeNull();
  });

  it("a damaged stored value reads as fresh", () => {
    expect(parseState("not json")).toEqual(FRESH);
    expect(parseState('{"casual": 1e9, "ranked": -3, "trigger": "x"}')).toMatchObject({ casual: 99, ranked: 0, trigger: null });
  });
});

describe("the web and the native bridge", () => {
  afterEach(() => {
    delete (window as unknown as { Capacitor?: unknown }).Capacitor;
  });

  it("is a no-op in a browser: no store, no plugin", () => {
    expect(nativeKv()).toBeNull();
    expect(nativeRequest()).toBeNull();
  });

  it("is a no-op in a shell without the review plugin (1.0.2 and earlier)", () => {
    (window as unknown as { Capacitor?: unknown }).Capacitor = {
      isNativePlatform: () => true,
      isPluginAvailable: (name: string) => name === "Preferences",
      registerPlugin: () => ({ get: async () => ({ value: null }), set: async () => undefined }),
    };
    expect(nativeKv()).not.toBeNull();
    expect(nativeRequest()).toBeNull();
  });

  it("reaches Preferences and ShengjiReview.request in the app", async () => {
    const calls: string[] = [];
    const store = new Map<string, string>();
    (window as unknown as { Capacitor?: unknown }).Capacitor = {
      isNativePlatform: () => true,
      isPluginAvailable: (name: string) => name === "Preferences" || name === "ShengjiReview",
      registerPlugin: (name: string) => ({
        get: async (o: { key: string }) => ({ value: store.get(o.key) ?? null }),
        set: async (o: { key: string; value: string }) => { store.set(o.key, o.value); },
        request: async () => { calls.push(name); return { requested: true }; },
      }),
    };
    const kv = nativeKv()!;
    await kv.set("k", "v");
    expect(await kv.get("k")).toBe("v");
    await nativeRequest()!();
    expect(calls).toEqual(["ShengjiReview"]);
  });
});

function gameState(over: Partial<GameState> & { winner?: 0 | 1 | null } = {}): GameState {
  const { winner = null, ...rest } = over;
  const players = [0, 1, 2, 3].map((seat) => ({
    seat, name: seat === 0 ? "You" : `Bot ${seat}`, is_bot: seat !== 0, connected: true,
    team: (seat % 2) as 0 | 1, cards_left: 0, is_banker: seat === 0, takeover_in: null,
    controller: seat === 0 ? "human" : "bot", reserved_for: null, reserved_secs: null,
  }));
  return {
    type: "state", room: "R", you: 0, phase: winner === null ? "play" : "round_end", players,
    round_result: winner === null ? null : { winner_team: winner } as GameState["round_result"],
    ...rest,
  } as unknown as GameState;
}

describe("useReviewPrompt at the table", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;
  let h: Harness;

  beforeEach(async () => {
    vi.useFakeTimers();
    container = document.createElement("div");
    root = createRoot(container);
    h = harness();
    await secondSession(h);
    for (let i = 0; i < CASUAL_WINS - 1; i++) await h.prompt.roundWon("casual");
  });

  afterEach(() => {
    act(() => root.unmount());
    vi.useRealTimers();
  });

  function Probe({ state, live }: { state: GameState; live: boolean }) {
    useReviewPrompt(state, live, h.prompt);
    return null;
  }

  function show(state: GameState, live = true) {
    act(() => root.render(createElement(Probe, { state, live })));
  }

  async function settle(ms: number) {
    await act(async () => { await vi.advanceTimersByTimeAsync(ms); });
  }

  it("asks 1.5 s after a won round's card appears", async () => {
    show(gameState());
    show(gameState({ winner: 0 }));
    await settle(PROMPT_DELAY_MS - 100);
    expect(h.asked).toBe(0);
    await settle(200);
    expect(h.asked).toBe(1);
    expect(h.reports).toEqual([["casual5", "1.0.3"]]);
  });

  it("never after a loss", async () => {
    show(gameState());
    show(gameState({ winner: 1 }));
    await settle(PROMPT_DELAY_MS * 2);
    expect(h.asked).toBe(0);
    expect((await state(h)).casual).toBe(CASUAL_WINS - 1);
  });

  it("never mid-round: Next dealt before the delay cancels it", async () => {
    show(gameState());
    show(gameState({ winner: 0 }));
    await settle(500);
    show(gameState({ phase: "deal" }));
    await settle(PROMPT_DELAY_MS * 2);
    expect(h.asked).toBe(0);
    // the win still counts, and the next won round asks
    show(gameState({ winner: 0 }));
    await settle(PROMPT_DELAY_MS);
    expect(h.asked).toBe(1);
  });

  it("not for a table opened onto a finished round, or a seat the bot plays", async () => {
    show(gameState());
    show(gameState({ winner: 0 }), false);
    await settle(PROMPT_DELAY_MS * 2);
    show(gameState());
    const away = gameState({ winner: 0 });
    away.players[0] = { ...away.players[0], away: true };
    show(away);
    await settle(PROMPT_DELAY_MS * 2);
    expect(h.asked).toBe(0);
    expect((await state(h)).casual).toBe(CASUAL_WINS - 1);
  });

  it("a matched table counts a ranked win; an unranked seat there counts casual", async () => {
    const fresh = harness();
    h = fresh;
    await secondSession(h);
    show(gameState({ matched: true }));
    show(gameState({ matched: true, winner: 0 }));
    await settle(PROMPT_DELAY_MS);
    show(gameState({ matched: true }));
    const guest = gameState({ matched: true, winner: 0 });
    guest.round_result = { ...guest.round_result!, unranked: "guest" };
    show(guest);
    await settle(PROMPT_DELAY_MS);
    expect(await state(h)).toMatchObject({ ranked: 1, casual: 1 });
    show(gameState({ matched: true }));
    show(gameState({ matched: true, winner: 0 }));
    await settle(PROMPT_DELAY_MS);
    expect(h.asked).toBe(1);
    expect(h.reports).toEqual([["ranked2", "1.0.3"]]);
  });
});
