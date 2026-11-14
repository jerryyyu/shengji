import { describe, expect, it, vi } from "vitest";

vi.mock("../ws", () => ({ conn: { send: () => true } }));

import { leaveCopy } from "./leaveCopy";
import type { LeaveContext } from "./leaveCopy";

const line = (ctx: LeaveContext, joined = false) => leaveCopy(ctx, joined).line;

describe("one consequence line per place a leave starts", () => {
  it("the Play table before a game is free, and names who stays", () => {
    expect(line({ kind: "queue", others: [] })).toBe("Free.");
    expect(line({ kind: "queue", others: ["Alice"] })).toBe("Free. Alice stays at the table.");
    expect(line({ kind: "queue", others: ["Alice", "Li"] })).toBe("Free. Alice & Li stay at the table.");
    expect(leaveCopy({ kind: "queue", others: [] }).title).toBe("Leave the table?");
  });

  it("a room is free; the host's controls pass on, and an empty room closes", () => {
    expect(line({ kind: "room", others: ["Alice", "Li"], host: true }))
      .toBe("Free. The table stays open; Alice can start it.");
    expect(line({ kind: "room", others: ["Alice"], host: false })).toBe("Free. The table stays open.");
    expect(line({ kind: "room", others: [], host: true })).toBe("Free. The room closes.");
    expect(leaveCopy({ kind: "room", others: [], host: true }).title).toBe("Leave the room?");
  });

  it("a ranked round keeps 'at best a draw'; a casual one hands the seat to a bot", () => {
    expect(line({ kind: "game", ranked: true }))
      .toBe("A bot takes your seat. This round counts as at best a draw for you.");
    expect(line({ kind: "game", ranked: false })).toBe("A bot takes your seat and the others keep playing.");
  });

  it("a guest sees no ranked words", () => {
    for (const joined of [false, true]) {
      for (const betweenRounds of [false, true]) {
        expect(line({ kind: "game", ranked: true, guest: true, betweenRounds }, joined)).not.toMatch(/rank|draw/i);
      }
    }
    expect(line({ kind: "game", ranked: true, guest: true }))
      .toBe("A bot takes your seat and the others keep playing.");
  });

  it("a round joined at a ranked table costs the 1-minute wait; at a casual one it is free", () => {
    expect(line({ kind: "game", ranked: true }, true)).toBe("You'll wait 1 minute to play again.");
    expect(line({ kind: "game", ranked: true, guest: true }, true)).toBe("You'll wait 1 minute to play again.");
    expect(line({ kind: "game", ranked: false }, true)).toBe("A bot takes your seat and the others keep playing.");
  });

  it("a round end is free, and practice says the game ends", () => {
    expect(line({ kind: "game", ranked: true, betweenRounds: true }, true)).toBe("Free. This round's result is kept.");
    expect(line({ kind: "game", ranked: false, practice: true })).toBe("This offline game ends.");
    expect(leaveCopy({ kind: "game", ranked: true }).title).toBe("Leave the game?");
  });
});
