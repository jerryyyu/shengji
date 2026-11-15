import { describe, expect, it } from "vitest";
import type { GameState, StatePlayer } from "./protocol";
import {
  attackingTeam, bankerText, buryPointsText, declareHelp, kittyIds, pointsLabel, seatStatus, teamWord,
} from "./tableCopy";

function p(seat: number, name: string, extra: Partial<StatePlayer> = {}): StatePlayer {
  return {
    seat, name, is_bot: false, connected: true, team: (seat % 2) as 0 | 1, cards_left: 0,
    is_banker: false, takeover_in: null, controller: "human", reserved_for: null, reserved_secs: null,
    ...extra,
  };
}

const base = {
  you: 1, banker: null, players: [p(0, "A"), p(1, "Me"), p(2, "C"), p(3, "Sam")],
} as unknown as GameState;

describe("table copy", () => {
  it("names teams from the viewer's side", () => {
    expect(teamWord(1, base)).toBe("Us");
    expect(teamWord(0, base)).toBe("Them");
  });

  it("finds the attackers from the banker and labels the counter", () => {
    expect(attackingTeam(base)).toBeNull();
    expect(pointsLabel(base)).toBe("Attackers");
    expect(pointsLabel({ ...base, banker: 0 })).toBe("Us");
    expect(pointsLabel({ ...base, banker: 3 })).toBe("Them");
  });

  it("names the banker in words for the crown's label", () => {
    expect(bankerText(p(1, "Me"), 1)).toBe("You, banker");
    expect(bankerText(p(3, "Sam"), 1)).toBe("Sam, banker");
  });

  it("explains declaring by whether the banker is already fixed", () => {
    expect(declareHelp(base)).toContain("makes you banker");
    expect(declareHelp({ ...base, banker: 2 })).not.toContain("banker");
  });

  it("totals the points chosen to bury", () => {
    const hand = [{ id: 1, code: "S5" }, { id: 2, code: "HK" }, { id: 3, code: "D10" }, { id: 4, code: "C3" }];
    expect(buryPointsText(hand, new Set([1, 2, 4]))).toBe("Burying 15 points");
    expect(buryPointsText(hand, new Set())).toBe("Burying 0 points");
  });

  it("finds the kitty cards by their ids, whatever part of the deal this client saw", () => {
    // 25 dealt cards (deck positions 0..99) and the kitty's 8 (100..107),
    // plus a card the server minted after a desync (200+)
    const hand = [...[3, 7, 11, 15, 19, 23, 27, 31, 35, 39, 43, 47, 51, 55, 59, 63, 67, 71, 75, 79, 83, 87, 91, 95, 99],
      ...[100, 101, 102, 103, 104, 105, 106, 107], 200].map((id) => ({ id, code: "S5" }));
    expect([...kittyIds(hand)]).toEqual([100, 101, 102, 103, 104, 105, 106, 107]);
    expect(kittyIds(hand.slice(0, 25)).size).toBe(0);
  });

  it("words a left seat apart from a disconnect", () => {
    const gone = p(2, "Alice", { connected: false, controller: "bot_cover" });
    expect(seatStatus({ ...gone, left: true }, null)).toBe("Bot (Alice left)");
    expect(seatStatus(gone, 27.2)).toBe("offline — bot in 28s");
    expect(seatStatus(gone, null)).toBe("bot playing");
    expect(seatStatus(p(2, "Alice"), null)).toBeNull();
  });
});
