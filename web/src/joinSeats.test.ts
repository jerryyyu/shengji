import { describe, expect, it } from "vitest";
import { hostName, joinSeat, roomChoices, roomDefaultSeat, tableFull, tableHostName, tableJoinSeat, takeoverSeats } from "./joinSeats";

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

  it("a game's choices are its bot seats, the plain one first, else its dropped players' seats", () => {
    const rows: Row[] = [{ seat: 0, name: "Mei" }, { seat: 1, name: "Bot 1", is_bot: true, claimable: true },
                         { seat: 2, name: "Alice", connected: false, claimable: true },
                         { seat: 3, name: "Bot 3", is_bot: true, claimable: true }];
    expect(roomChoices(peek(rows, { in_game: true }))).toEqual([1, 3]);
    expect(roomDefaultSeat(peek(rows, { in_game: true }))).toBe(1);
    rows[1] = { seat: 1, name: "Li" };
    rows[3] = { seat: 3, name: "Sam" };
    expect(roomChoices(peek(rows, { in_game: true }))).toEqual([2]);
    rows[2] = { seat: 2, name: "Alice" };
    expect(roomDefaultSeat(peek(rows, { in_game: true }))).toBeNull();
  });

  it("a ranked table the server calls full is full", () => {
    const rows: Row[] = [0, 1, 2, 3].map((seat) => ({ seat, name: `P${seat}` }));
    expect(tableFull(peek(rows, { in_game: true, ranked: true, full: true }))).toBe(true);
  });
});

describe("a queued table's seats", () => {
  type State = "taken" | "open" | "held";
  const table = (states: State[], names: (string | null)[] = []) => ({
    seats: states.map((state, seat) => ({ seat, team: seat % 2, state, name: names[seat] ?? null, ready: false })),
  });
  it("seat a code join in the held seat, else the first open seat partner first, else nowhere", () => {
    expect(tableJoinSeat(table(["taken", "open", "held", "open"]))).toBe(2);
    expect(tableJoinSeat(table(["taken", "open", "open", "open"]))).toBe(2);
    expect(tableJoinSeat(table(["taken", "open", "taken", "open"]))).toBe(1);
    expect(tableJoinSeat(table(["taken", "taken", "taken", "taken"]))).toBeNull();
  });
  it("are titled with the first person seated", () => {
    expect(tableHostName(table(["open", "taken", "taken", "open"], [null, "Li", "Mei"]))).toBe("Li");
    expect(tableHostName(table(["open", "open", "open", "open"]))).toBeNull();
  });
});
