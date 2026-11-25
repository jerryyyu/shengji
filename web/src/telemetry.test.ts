import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./ws", () => ({ conn: { send: () => true } }));

import { FLUSH_AT, FLUSH_MS, MAX_BYTES, Telemetry, TurnClock, leadKind, telemetry } from "./telemetry";
import { noteLink } from "./link";

type Msg = { type: string; v: number; form: string; first_visit: boolean; events: Record<string, unknown>[] };

let sent: Msg[];
const sender = (ok = true) => (m: unknown) => { if (ok) sent.push(m as Msg); return ok; };

beforeEach(() => { sent = []; vi.useFakeTimers(); });
afterEach(() => { vi.useRealTimers(); });

describe("connection notices", () => {
  it("each lost socket and recovery the socket manager reports becomes a notice", () => {
    telemetry.reset();
    noteLink({ kind: "down", cause: "no_pong" });
    noteLink({ kind: "up", ms: 4400.4 });
    expect(telemetry.pending()).toEqual([
      expect.objectContaining({ e: "notice", code: "disconnected", cause: "no_pong" }),
      expect.objectContaining({ e: "notice", code: "reconnected", ms: 4400 }),
    ]);
    telemetry.reset();
  });
});

describe("telemetry transport", () => {
  it("sends a batch at 20 events", () => {
    const t = new Telemetry(sender(), true);
    for (let i = 0; i < FLUSH_AT - 1; i++) t.tap("play");
    expect(sent).toHaveLength(0);
    t.tap("play");
    expect(sent).toHaveLength(1);
    expect(sent[0]).toMatchObject({ type: "client_event", v: 1 });
    expect(sent[0].events).toHaveLength(FLUSH_AT);
  });

  it("flushes after 10 s", () => {
    const t = new Telemetry(sender(), true);
    t.tap("next_round");
    vi.advanceTimersByTime(FLUSH_MS - 1);
    expect(sent).toHaveLength(0);
    vi.advanceTimersByTime(1);
    expect(sent[0].events).toEqual([expect.objectContaining({ e: "tap", id: "next_round" })]);
  });

  it("keeps every message under the server's 2 kB", () => {
    const t = new Telemetry(sender(), true);
    for (let i = 0; i < 19; i++) {
      t.turnDone({ phase: "play", lead: "tractor", need: 4, ms_to_first_tap: 123456, ms_total: 234567,
                   sel_changes: 12, disabled_play_taps: 3, refused: 1, coach: true, nth_turn: 40, by: "timer" });
    }
    t.flush();
    expect(sent.length).toBeGreaterThan(1);
    for (const m of sent) expect(JSON.stringify(m).length).toBeLessThanOrEqual(MAX_BYTES);
    expect(sent.flatMap((m) => m.events)).toHaveLength(19);
    expect(sent[0].events[0].nth_turn).toBe(30);
  });

  it("does nothing in practice (no server)", () => {
    const send = vi.fn(() => true);
    const t = new Telemetry(send, false);
    t.tap("play");
    t.screenView("table");
    t.flush();
    expect(send).not.toHaveBeenCalled();
    expect(t.pending()).toHaveLength(0);
  });

  it("keeps events while the socket is down and never throws", () => {
    const t = new Telemetry(sender(false), true);
    t.tap("play");
    t.flush();
    expect(t.pending()).toHaveLength(1);
    const boom = new Telemetry(() => { throw new Error("socket gone"); }, true);
    expect(() => { boom.tap("play"); boom.flush(); }).not.toThrow();
  });

  it("reports a screen change with the previous screen and its time", () => {
    const t = new Telemetry(sender(), true);
    t.screenView("play");
    t.screenView("play");
    vi.advanceTimersByTime(1500);
    t.screenView("table");
    t.flush();
    const [first, second] = sent[0].events;
    expect(first).toMatchObject({ e: "screen", name: "play" });
    expect(first).not.toHaveProperty("prev");
    expect(second).toMatchObject({ e: "screen", name: "table", prev: "play" });
    expect(sent[0].events).toHaveLength(2);
  });
});

describe("turn telemetry", () => {
  it("names the lead's shape from its codes", () => {
    expect(leadKind(["S5"])).toBe("single");
    expect(leadKind(["S5", "S5"])).toBe("pair");
    expect(leadKind(["S5", "S5", "S6", "S6"])).toBe("tractor");
    expect(leadKind(["SA", "SK"])).toBe("throw");
  });

  it("folds a turn into counts with no cards in it", () => {
    const c = new TurnClock("play", 3, "throw", false, 2);
    c.select(); c.select(); c.disabledTaps += 1;
    const done = c.finish("you");
    expect(done).toMatchObject({ phase: "play", need: 3, lead: "throw", sel_changes: 2,
                                 disabled_play_taps: 1, refused: 0, coach: false, nth_turn: 2, by: "you" });
    expect(Object.values(done).every((v) => typeof v !== "string" || /^[a-z]+$/.test(v))).toBe(true);
  });
});

describe("funnel events and batch stamps", () => {
  it("every batch carries the day, session and language buckets and nothing finer", () => {
    localStorage.clear();
    const t = new Telemetry(sender(), true);
    t.appOpen(true, 812.6);
    t.flush();
    const m = sent[0] as unknown as Record<string, unknown>;
    expect(m).toMatchObject({ days_since_first: "0", session_n: "1", lang: "en" });
    expect(m.events).toEqual([{ e: "app_open", t: expect.any(Number), cold: true, ms_to_socket: 813 }]);
    expect(JSON.stringify(m)).not.toMatch(/\d{4}-\d{2}-\d{2}/);    // never the first-seen date itself
  });

  it("caps app_open's time to the socket and each round count", () => {
    const t = new Telemetry(sender(), true);
    t.appOpen(true, 10 * 60_000);
    t.appOpen(false);
    t.roundStart("casual", 7, 900);
    t.roundFinish("casual", "end", 40, true);
    t.roundFinish("casual", "left", -2, true);
    t.roundFinish("friend", "closed");
    t.howtoStep(99, false);
    expect(t.pending().map(({ t: _t, ...e }) => e)).toEqual([
      { e: "app_open", cold: true, ms_to_socket: 120_000 },
      { e: "app_open", cold: false },
      { e: "round_start", mode: "casual", bots: 3, nth_round_this_load: 50 },
      { e: "round_finish", mode: "casual", by: "end", tricks_played: 25, won: true },
      { e: "round_finish", mode: "casual", by: "left", tricks_played: 0 },
      { e: "round_finish", mode: "friend", by: "closed" },          // an unknown count is no count
      { e: "howto_step", step: 20, done: false },
    ]);
  });

  it("the offline digest goes in a batch of its own, only while collecting, and says whether it went", () => {
    const t = new Telemetry(sender(), true);
    expect(t.sendOfflineDigest({ rounds_started: 500, rounds_finished: 1, nearby_rounds: -1 })).toBe(true);
    expect(t.pending()).toEqual([]);                                  // never buffered
    expect(sent[0].events).toEqual([expect.objectContaining(
      { e: "offline_digest", rounds_started: 99, rounds_finished: 1, nearby_rounds: 0 })]);
    expect(new Telemetry(sender(false), true).sendOfflineDigest({ rounds_started: 1, rounds_finished: 0, nearby_rounds: 0 }))
      .toBe(false);                                                   // the socket refused it
    expect(new Telemetry(sender(), false).sendOfflineDigest({ rounds_started: 1, rounds_finished: 0, nearby_rounds: 0 }))
      .toBe(false);                                                   // offline: not collecting
    expect(sent).toHaveLength(1);
  });

  it("device_account says whether a round came first", () => {
    localStorage.clear();
    const t = new Telemetry(sender(), true);
    t.deviceAccount("created");
    localStorage.setItem("shengji.telemetry.played", "1");
    t.deviceAccount("restored");
    expect(t.pending().map((e) => (e as { first_round_before?: boolean }).first_round_before)).toEqual([false, true]);
    localStorage.clear();
  });

  it("the language stamp follows the page", async () => {
    const { setLanguageChoice } = await import("./i18n/locale");
    const t = new Telemetry(sender(), true);
    setLanguageChoice("zh-Hans");
    try {
      t.tap("play");
      t.flush();
      expect((sent[0] as unknown as { lang: string }).lang).toBe("zh");
    } finally {
      setLanguageChoice("system");
    }
  });
});
