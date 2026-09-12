import { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it } from "vitest";
import type { GameState, StatePlayer } from "../protocol";
import Table from "./Table";

function makePlayer(overrides: Partial<StatePlayer> = {}): StatePlayer {
  return {
    seat: 1,
    name: "Opponent",
    is_bot: false,
    connected: true,
    team: 1,
    cards_left: 16,
    is_banker: false,
    takeover_in: null,
    controller: "human",
    reserved_for: null,
    reserved_secs: null,
    ...overrides,
  };
}

function makeState({
  phase,
  target,
  turn = 1,
}: {
  phase: GameState["phase"];
  target: Partial<StatePlayer>;
  turn?: number | null;
}): GameState {
  return {
    type: "state",
    room: "TEST",
    you: 0,
    phase,
    players: [
      makePlayer({ seat: 0, name: "You", team: 0, is_banker: phase !== "bury" }),
      makePlayer({ ...target, is_banker: phase === "bury" }),
    ],
    hand: [],
    levels: ["2", "2"],
    banker: phase === "bury" ? 1 : 0,
    trump: null,
    turn,
    declare_options: [],
    current_declaration: null,
    passed: [],
    trick: null,
    last_trick: null,
    attacker_points: 0,
    kitty_count: 8,
    round_result: null,
    message: null,
  };
}

function renderTable(state: GameState): { container: HTMLDivElement; unmount: () => void } {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => root.render(<Table state={state} />));
  return {
    container,
    unmount: () => {
      act(() => root.unmount());
      container.remove();
    },
  };
}

describe("opponent turn status", () => {
  it("describes bot bury and play turns with their action phase", () => {
    for (const [phase, text] of [
      ["bury", "Choosing 8 cards to bury…"],
      ["play", "Considering the next play…"],
    ] as const) {
      const view = renderTable(makeState({
        phase,
        target: { is_bot: true, controller: "bot" },
      }));
      expect(view.container.querySelector(".thinking")?.textContent).toBe(text);
      expect(view.container.querySelector(".thinking")?.getAttribute("role")).toBe("status");
      view.unmount();
    }
  });

  it("describes a bot covering a human seat", () => {
    for (const phase of ["bury", "play"] as const) {
      const view = renderTable(makeState({
        phase,
        target: { connected: false, controller: "bot_cover" },
      }));
      expect(view.container.querySelector(".thinking")?.textContent).toBe(
        phase === "bury" ? "Choosing 8 cards to bury…" : "Considering the next play…");
      expect(view.container.querySelector(".their-turn")).toBeNull();
      view.unmount();
    }
  });

  it("keeps human turns generic and hides status off-turn or outside action phases", () => {
    const human = renderTable(makeState({
      phase: "play",
      target: { controller: "human" },
    }));
    expect(human.container.querySelector(".their-turn")?.textContent).toBe("their turn");
    expect(human.container.querySelector(".thinking")).toBeNull();
    human.unmount();

    const offTurn = renderTable(makeState({
      phase: "play",
      turn: null,
      target: { is_bot: true, controller: "bot" },
    }));
    expect(offTurn.container.querySelector(".thinking")).toBeNull();
    offTurn.unmount();

    for (const phase of ["deal", "declare", "round_end", "game_over"] as const) {
      const nonAction = renderTable(makeState({
        phase,
        target: { is_bot: true, controller: "bot" },
      }));
      expect(nonAction.container.querySelector(".thinking")).toBeNull();
      expect(nonAction.container.querySelector(".their-turn")).toBeNull();
      nonAction.unmount();
    }
  });
});
