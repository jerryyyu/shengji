// The seat's round memory: a round boundary clears it, and each finished
// trick joins the history once, by its ordinal.
import { describe, expect, it } from "vitest";
import { freshMemory, remember, viewFromFrame, type Frame } from "./frameView";

const card = (code: string, id: number) => ({ id, code });
const trick = (cards: string[]) => ({ leader: 1, plays: [1, 2, 3, 0].map((seat, i) => ({ seat, cards: [cards[i]] })), winner: 1 });
const frame = (over: Record<string, unknown>): Frame => ({
  type: "state", you: 0, phase: "play", banker: 0, hand: [card("S3", 1)], trump: { suit: "H", rank: "2" },
  current_declaration: null, trick: null, last_trick: null, ...over,
});
const T24 = trick(["SA", "S5", "S6", "S7"]);
const T25 = trick(["CA", "C5", "C6", "C7"]);

describe("frameView memory", () => {
  it("a round's end then a deal with empty hands and tricks_done back to 0 starts clean", () => {
    const mem = freshMemory();
    remember(mem, frame({ tricks_done: 24, last_trick: T24 }));
    mem.buried = ["S9", "S9", "D3", "D4", "D5", "C3", "C4", "C8"];
    remember(mem, frame({ phase: "round_end", hand: [], tricks_done: 25, last_trick: T25 }));
    expect(mem.history).toHaveLength(2);
    // the next round's deal still carries the old last trick
    remember(mem, frame({ phase: "deal", hand: [], tricks_done: 0, last_trick: T25 }));
    expect(mem.history).toEqual([]);
    expect(mem.buried).toEqual([]);
    remember(mem, frame({ phase: "deal", hand: [card("D3", 1)], tricks_done: 0, last_trick: T25 }));
    remember(mem, frame({ phase: "play", hand: [card("D3", 1)], tricks_done: 0, last_trick: T25 }));
    expect(mem.history).toEqual([]);
    expect(viewFromFrame(frame({ phase: "play", banker: 0, tricks_done: 0 }), mem)!.ownBuried).toEqual([]);
  });

  it("tricks_done going down clears it even with no deal frame seen", () => {
    const mem = freshMemory();
    remember(mem, frame({ phase: "round_end", hand: [], tricks_done: 25, last_trick: T25 }));
    expect(mem.history).toHaveLength(1);
    remember(mem, frame({ phase: "play", tricks_done: 0, last_trick: null }));
    expect(mem.history).toEqual([]);
    remember(mem, frame({ phase: "play", tricks_done: 1, last_trick: T24 }));
    expect(mem.history).toEqual([{ leader: T24.leader, plays: T24.plays }]);
  });

  it("two successive tricks with the same plays are two tricks", () => {
    const mem = freshMemory();
    remember(mem, frame({ tricks_done: 3, last_trick: T24 }));
    remember(mem, frame({ tricks_done: 3, last_trick: T24 }));
    remember(mem, frame({ tricks_done: 4, last_trick: T24 }));
    expect(mem.history).toHaveLength(2);
  });

  it("a server that sends no count still records each new trick once", () => {
    const mem = freshMemory();
    remember(mem, frame({ last_trick: T24 }));
    remember(mem, frame({ last_trick: T24 }));
    remember(mem, frame({ last_trick: T25 }));
    expect(mem.history).toHaveLength(2);
    remember(mem, frame({ phase: "round_end", hand: [], last_trick: T25 }));
    remember(mem, frame({ phase: "deal", hand: [], last_trick: T25 }));
    expect(mem.history).toEqual([]);
  });
});
