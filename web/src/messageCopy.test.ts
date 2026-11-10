import { describe, expect, it } from "vitest";
import { formatTableMessage, isDeclareMessage } from "./messageCopy";
import type { StatePlayer } from "./protocol";

const players = [0, 1, 2, 3].map((seat) => ({ seat, name: seat ? `Bot ${seat}` : "Jerry" })) as StatePlayer[];

describe("formatTableMessage", () => {
  it("names the seat and writes the declared card as rank and suit symbol", () => {
    expect(formatTableMessage("Seat 1 declared H2", players, 0)).toBe("Bot 1 declares 2♥");
    expect(formatTableMessage("Seat 3 declared S10 (pair)", players, 0)).toBe("Bot 3 declares 10♠ pair");
    expect(formatTableMessage("Seat 2 declared NT (pair)", players, 0)).toBe("Bot 2 declares no trump pair");
  });

  it("says You for your own declaration", () => {
    expect(formatTableMessage("Seat 0 declared DA", players, 0)).toBe("You declared A♦");
  });

  it("writes a flipped trump suit as its symbol", () => {
    expect(formatTableMessage("No declaration — trump flipped from the kitty: C", players, 0))
      .toBe("No declaration — trump flipped from the kitty: ♣");
  });

  it("passes every other message through", () => {
    expect(formatTableMessage("Throw failed.", players, 0)).toBe("Throw failed.");
    expect(formatTableMessage("Seat 9 declared H2", players, 0)).toBe("Seat 9 declares 2♥");
  });
});

describe("isDeclareMessage", () => {
  it("knows a declaration from any other message", () => {
    expect(isDeclareMessage("Seat 1 declared H2")).toBe(true);
    expect(isDeclareMessage("Seat 2 declared NT (pair)")).toBe(true);
    expect(isDeclareMessage("No declaration — trump flipped from the kitty: C")).toBe(false);
    expect(isDeclareMessage("Throw failed.")).toBe(false);
  });
});
