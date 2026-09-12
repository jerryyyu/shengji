import { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";
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

function renderTable(state: GameState) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => root.render(<Table state={state} />));
  return {
    container,
    rerender: (next: GameState) => act(() => root.render(<Table state={next} />)),
    unmount: () => {
      act(() => root.unmount());
      container.remove();
    },
  };
}

describe("opponent turn status", () => {
  it("cycles cosmetic banter, resets for the next decision, and clears its timer", () => {
    vi.useFakeTimers();
    const state = makeState({ phase: "play", target: { is_bot: true, controller: "bot" } });
    const view = renderTable(state);
    try {
      const first = view.container.querySelector(".bot-banter")?.textContent;
      const bar = view.container.querySelector('[role="progressbar"]');
      expect(bar?.getAttribute("aria-label")).toBe("Bot considering its play");
      expect(bar?.hasAttribute("aria-valuenow")).toBe(false);
      expect(first).toContain("Bot banter:");
      act(() => vi.advanceTimersByTime(3200));
      expect(view.container.querySelector(".bot-banter")?.textContent).not.toBe(first);
      expect(view.container.querySelector('[role="status"]')?.textContent).toBe("Considering the next play…");
      expect(view.container.querySelector('[role="status"] .bot-banter')).toBeNull();
      // Unrelated server broadcasts must not restart a long-running turn.
      const second = view.container.querySelector(".bot-banter")?.textContent;
      view.rerender({ ...state, message: "Someone connected" });
      expect(view.container.querySelector(".bot-banter")?.textContent).toBe(second);
      act(() => vi.advanceTimersByTime(3200 * 3));
      expect(view.container.querySelector(".bot-banter")?.textContent).toBe(first);
      act(() => vi.advanceTimersByTime(3200));
      // A same-seat next decision resets even without an intervening off-turn render.
      view.rerender({ ...state, players: state.players.map((p) => p.seat === 1 ? { ...p, cards_left: 15 } : p) });
      expect(view.container.querySelector(".bot-banter")?.textContent).toBe(first);
      view.rerender({ ...state, turn: null });
      expect(view.container.querySelector(".bot-banter")).toBeNull();
      expect(view.container.querySelector('[role="progressbar"]')).toBeNull();
      expect(vi.getTimerCount()).toBe(0);
      view.rerender(state);
      expect(view.container.querySelector(".bot-banter")?.textContent).toBe(first);
    } finally {
      view.unmount();
      expect(vi.getTimerCount()).toBe(0);
      vi.useRealTimers();
    }
  });
  it("rotates bury flavor and resets on phase and room changes", () => {
    vi.useFakeTimers();
    const state = makeState({ phase: "bury", target: { controller: "bot_cover" } });
    const view = renderTable(state);
    try {
      const first = view.container.querySelector(".bot-banter")?.textContent;
      act(() => vi.advanceTimersByTime(3200));
      expect(view.container.querySelector(".bot-banter")?.textContent).not.toBe(first);
      view.rerender({ ...state, room: "NEXT" });
      expect(view.container.querySelector(".bot-banter")?.textContent).toBe(first);
      view.rerender({ ...state, phase: "play" });
      expect(view.container.querySelector(".bot-banter")?.textContent).toContain("Hmm…");
      expect(view.container.querySelector('[role="progressbar"]')?.hasAttribute("aria-valuenow")).toBe(false);
    } finally {
      view.unmount();
      expect(vi.getTimerCount()).toBe(0);
      vi.useRealTimers();
    }
  });
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
      expect(view.container.querySelector('[role="progressbar"]')?.getAttribute("aria-label")).toBe(
        phase === "bury" ? "Bot choosing cards to bury" : "Bot considering its play");
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
