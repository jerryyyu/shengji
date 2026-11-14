import { describe, expect, it } from "vitest";
import { hostName, joinSeat, tableFull, takeoverSeats } from "./joinSeats";

type Row = { seat: number; name: string; is_bot?: boolean; connected?: boolean; claimable?: boolean };
const peek = (rows: Row[], over: { in_game?: boolean; ranked?: boolean; full?: boolean } = {}) => ({
  in_game: false, ...over,
  seats: rows.map((r) => ({ is_bot: false, connected: true, claimable: false, team: r.seat % 2,
                            controller: "human" as const, reserved_secs: null, ...r })),
});

describe("the Join panel's seats", () => {
  it("before the game a join sits across from the person the panel names, else at the lowest empty seat", () => {
    expect(joinSeat(peek([{ seat: 0, name: "Jerry" }]))).toBe(2);
    expect(joinSeat(peek([{ seat: 0, name: "Jerry" }, { seat: 2, name: "Mei" }]))).toBe(1);
    expect(hostName(peek([{ seat: 1, name: "Bot 1", is_bot: true }, { seat: 2, name: "Mei" }]))).toBe("Mei");
  });

  it("in a game a join takes a bot seat; a dropped player's seat is only a takeover", () => {
    const rows: Row[] = [{ seat: 0, name: "Mei" }, { seat: 1, name: "Alice", connected: false, claimable: true },
                         { seat: 2, name: "Sam" }, { seat: 3, name: "Bot 3", is_bot: true, claimable: true }];
    expect(joinSeat(peek(rows, { in_game: true }))).toBe(3);
    expect(takeoverSeats(peek(rows, { in_game: true }))).toEqual([]);
    rows[3] = { seat: 3, name: "Li" };
    expect(joinSeat(peek(rows, { in_game: true }))).toBeNull();
    expect(takeoverSeats(peek(rows, { in_game: true }))).toEqual([{ seat: 1, name: "Alice" }]);
    expect(tableFull(peek(rows, { in_game: true }))).toBe(false);
    rows[1] = { seat: 1, name: "Alice" };
    expect(tableFull(peek(rows, { in_game: true }))).toBe(true);
  });

  it("a ranked table the server calls full is full", () => {
    const rows: Row[] = [0, 1, 2, 3].map((seat) => ({ seat, name: `P${seat}` }));
    expect(tableFull(peek(rows, { in_game: true, ranked: true, full: true }))).toBe(true);
  });
});
