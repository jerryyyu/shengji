import { describe, expect, it, vi } from "vitest";

vi.mock("../ws", () => ({ conn: { send: () => true } }));

import { leaveCopy } from "./leaveCopy";
import type { LeaveContext } from "./leaveCopy";

const line = (ctx: LeaveContext, joined = false) => leaveCopy(ctx, joined).line;

describe("one consequence line per place a leave starts", () => {
  it("the Play table before a game has no line alone, and names who stays", () => {
    expect(line({ kind: "queue", others: [] })).toBeNull();
    expect(line({ kind: "queue", others: ["Alice"] })).toBe("Alice stays at the table.");
    expect(line({ kind: "queue", others: ["Alice", "Li"] })).toBe("Alice & Li stay at the table.");
    expect(leaveCopy({ kind: "queue", others: [] }).title).toBe("Leave the table?");
  });

  it("a Duo made at the Play table: Leave the Duo?, and the partner keeps the table (its code too, from the opener)", () => {
    expect(leaveCopy({ kind: "duo", partner: "Jerry", opener: false }))
      .toEqual({ title: "Leave the Duo?", line: "Jerry keeps the table." });
    expect(leaveCopy({ kind: "duo", partner: "Alice", opener: true }))
      .toEqual({ title: "Leave the Duo?", line: "Alice keeps the table and its code." });
    expect(line({ kind: "duo", partner: "Alexandrina Smith", opener: false })).toBe("Alexandrin… keeps the table.");
  });

  it("a ranked round keeps 'at best a draw'; a casual one is free and has no line", () => {
    expect(line({ kind: "game", ranked: true })).toBe("This round counts as at best a draw.");
    expect(line({ kind: "game", ranked: false })).toBeNull();
  });

  it("a guest sees no ranked words", () => {
    for (const joined of [false, true]) {
      for (const betweenRounds of [false, true]) {
        expect(line({ kind: "game", ranked: true, guest: true, betweenRounds }, joined) ?? "").not.toMatch(/rank|draw/i);
      }
    }
    expect(line({ kind: "game", ranked: true, guest: true })).toBeNull();
  });

  it("a round joined at a ranked table costs the 1-minute wait; at a casual one it is free", () => {
    const wait = "Stay until this round ends, or wait 1 minute to play again.";
    expect(line({ kind: "game", ranked: true }, true)).toBe(wait);
    expect(line({ kind: "game", ranked: true, guest: true }, true)).toBe(wait);
    expect(line({ kind: "game", ranked: false }, true)).toBeNull();
  });

  it("a free leave never says Free: a round end keeps its result, and practice says the game ends", () => {
    expect(line({ kind: "game", ranked: true, betweenRounds: true }, true)).toBe("This round's result is kept.");
    for (const ctx of [{ kind: "queue", others: ["Alice"] }, { kind: "duo", partner: "Alice", opener: true }] as LeaveContext[]) {
      expect(line(ctx)).not.toMatch(/Free/);
    }
    expect(line({ kind: "game", ranked: false, practice: true })).toBe("This offline game ends.");
    expect(leaveCopy({ kind: "game", ranked: true }).title).toBe("Leave the game?");
  });
});
