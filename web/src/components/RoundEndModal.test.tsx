import { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it } from "vitest";
import type { GameState, RoundResult, StatePlayer } from "../protocol";
import RoundEndModal from "./RoundEndModal";

function makePlayer(seat: number, name: string, team: 0 | 1): StatePlayer {
  return {
    seat, name, is_bot: false, connected: true, team, cards_left: 0,
    is_banker: seat === 0, takeover_in: null, controller: "human",
    reserved_for: null, reserved_secs: null,
  };
}

const state: GameState = {
  type: "state", room: "TEST", you: 0, phase: "round_end",
  players: [makePlayer(0, "You", 0), makePlayer(1, "Robin", 1),
            makePlayer(2, "Sam", 0), makePlayer(3, "Ada", 1)],
  hand: [], levels: ["2", "2"], games_won: [0, 0], banker: 0, trump: null,
  turn: null, declare_options: [], current_declaration: null, passed: [],
  trick: null, last_trick: null, attacker_points: 0, kitty_count: 8,
  round_result: null, message: null, notice: null,
};

function makeResult(overrides: Partial<RoundResult> = {}): RoundResult {
  return {
    attacker_points: 0, kitty_points: 0, kitty_cards: [], winner_team: 0,
    level_change: 3, next_banker: 2, new_levels: ["2", "2"],
    game_over: false, games_won: [0, 0], point_scored: false,
    ...overrides,
  };
}

function renderModal(result: RoundResult): string {
  const host = document.createElement("div");
  document.body.appendChild(host);
  act(() => { createRoot(host).render(<RoundEndModal state={state} result={result} />); });
  return host.textContent ?? "";
}

describe("round end modal", () => {
  it("shows a level change on an ordinary round", () => {
    const text = renderModal(makeResult({ new_levels: ["5", "2"] }));
    expect(text).toContain("Level change");
    expect(text).toContain("+3");
    expect(text).not.toContain("wins the game");
  });

  it("says a GAME was won, not '+levels', when a team holds Ace", () => {
    // The bug this guards: the levels reset to 2 while the modal still
    // announced "+3 levels", which reads as the game losing your progress.
    const text = renderModal(makeResult({ point_scored: true, games_won: [1, 0] }));
    expect(text).toContain("wins the game");
    expect(text).toContain("levels restart at 2");
    expect(text).not.toContain("Level change");
  });

  it("shows the running games-won tally once a game has been won", () => {
    const text = renderModal(makeResult({ point_scored: true, games_won: [2, 1] }));
    expect(text).toContain("Games won");
  });

  it("does not show a tally on an ordinary round", () => {
    expect(renderModal(makeResult())).not.toContain("Games won");
  });
});
