import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./ws", () => ({ conn: { send: () => true } }));

import { FLUSH_AT, FLUSH_MS, MAX_BYTES, Telemetry, TurnClock, leadKind } from "./telemetry";

type Msg = { type: string; v: number; form: string; first_visit: boolean; events: Record<string, unknown>[] };

let sent: Msg[];
const sender = (ok = true) => (m: unknown) => { if (ok) sent.push(m as Msg); return ok; };

beforeEach(() => { sent = []; vi.useFakeTimers(); });
afterEach(() => { vi.useRealTimers(); });

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
