import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeAll, describe, expect, it } from "vitest";
import type { GameState, Notice, StatePlayer } from "../protocol";
import Hud from "./Hud";

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

function makeState(overrides: Partial<GameState> = {}): GameState {
  return {
    type: "state",
    room: "TEST",
    you: 0,
    phase: "play",
    players: [
      makePlayer({ seat: 0, name: "You", team: 0 }),
      makePlayer({ seat: 1, name: "Robin" }),
    ],
    hand: [],
    levels: ["2", "2"],
    banker: 0,
    trump: null,
    turn: 0,
    declare_options: [],
    current_declaration: null,
    passed: [],
    trick: null,
    last_trick: null,
    attacker_points: 0,
    kitty_count: 8,
    round_result: null,
    message: null,
    notice: null,
    ...overrides,
  };
}

beforeAll(() => {
  // audio.ts installs a global pointer handler that unlocks an AudioContext on
  // the first gesture. jsdom has no AudioContext, so a real click in this file
  // would surface an unhandled error from a module these tests do not exercise.
  class SilentAudioContext {
    state: "suspended" | "running" = "running";
    currentTime = 0;
    async resume(): Promise<void> {}
  }
  (window as unknown as { AudioContext: unknown }).AudioContext = SilentAudioContext;
});

const failedThrow = (id = 1, seat = 0): Notice => ({
  id,
  kind: "failed_throw",
  seat,
  attempted: ["C7", "C7", "D7", "D7"],
  forced: ["D7", "D7"],
});

function render(state: GameState) {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  act(() => root.render(<Hud state={state} />));
  return {
    host,
    rerender: (next: GameState) => act(() => root.render(<Hud state={next} />)),
    unmount: () => act(() => root.unmount()),
  };
}

describe("failed-throw notice", () => {
  it("names what was thrown and what was forced", () => {
    const view = render(makeState({ notice: failedThrow() }));
    const el = view.host.querySelector(".hud-notice");
    expect(el).not.toBeNull();
    const text = el!.textContent ?? "";
    expect(text).toContain("Throw failed");
    expect(text).toContain("♣7 ♣7 ♦7 ♦7"); // the attempt, which `message` never carried
    expect(text).toContain("♦7 ♦7");
    expect(el!.getAttribute("role")).toBe("status");
    view.unmount();
  });

  it("names the other player when the throw was not yours", () => {
    const view = render(makeState({ notice: failedThrow(1, 1) }));
    expect(view.host.querySelector(".hud-notice")!.textContent).toContain("Robin threw");
    view.unmount();
  });

  it("dismisses on click and stays dismissed while the same notice stands", () => {
    const state = makeState({ notice: failedThrow() });
    const view = render(state);
    const close = view.host.querySelector<HTMLButtonElement>(".hud-notice-close")!;
    act(() => close.click());
    expect(view.host.querySelector(".hud-notice")).toBeNull();
    // the server keeps sending the same notice for several plays: it must not
    // pop back up after the player has dismissed it
    view.rerender({ ...state });
    expect(view.host.querySelector(".hud-notice")).toBeNull();
    view.unmount();
  });

  it("shows the NEXT failed throw even after the last one was dismissed", () => {
    const state = makeState({ notice: failedThrow(1) });
    const view = render(state);
    act(() => view.host.querySelector<HTMLButtonElement>(".hud-notice-close")!.click());
    expect(view.host.querySelector(".hud-notice")).toBeNull();
    view.rerender(makeState({ notice: failedThrow(2) }));
    expect(view.host.querySelector(".hud-notice")).not.toBeNull();
    view.unmount();
  });

  it("does not double up the one-play message with the notice", () => {
    const view = render(makeState({
      notice: failedThrow(),
      message: "Throw failed — forced to play D7+D7",
    }));
    expect(view.host.querySelector(".hud-notice")).not.toBeNull();
    expect(view.host.querySelector(".hud-message")).toBeNull();
    view.unmount();
  });

  it("still shows an ordinary message when there is no notice", () => {
    const view = render(makeState({ message: "Robin declared Hearts" }));
    expect(view.host.querySelector(".hud-message")!.textContent).toBe("Robin declared Hearts");
    view.unmount();
  });
});
