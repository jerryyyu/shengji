import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { DUR } from "../motion";
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
    games_won: [0, 0],
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

  it("closes when the round ends, even if no later trick cleared it", () => {
    const notice = failedThrow(4);
    const view = render(makeState({ notice }));
    expect(view.host.querySelector(".hud-notice")).not.toBeNull();
    view.rerender(makeState({ notice, phase: "round_end" }));
    expect(view.host.querySelector(".hud-notice")).toBeNull();
    view.unmount();
  });

  it("goes away by itself once the trick after the failed throw is over", () => {
    const trickA = { leader: 0, plays: [], winner: 0 } as unknown as GameState["last_trick"];
    const trickB = { leader: 1, plays: [], winner: 1 } as unknown as GameState["last_trick"];
    const trickC = { leader: 2, plays: [], winner: 2 } as unknown as GameState["last_trick"];
    const notice = failedThrow(3);
    const view = render(makeState({ notice, last_trick: trickA }));
    expect(view.host.querySelector(".hud-notice")).not.toBeNull();
    view.rerender(makeState({ notice, last_trick: trickA }));     // more plays in the same trick
    expect(view.host.querySelector(".hud-notice")).not.toBeNull();
    view.rerender(makeState({ notice, last_trick: trickB }));     // the throw's trick ends
    expect(view.host.querySelector(".hud-notice")).not.toBeNull();
    view.rerender(makeState({ notice, last_trick: trickC }));     // one more trick ends
    expect(view.host.querySelector(".hud-notice")).toBeNull();
    view.rerender(makeState({ notice: failedThrow(4), last_trick: trickC }));   // a new failed throw shows
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

  it("marks a declaration message, which the phone tells only by the tag under the cards", () => {
    const view = render(makeState({ message: "Seat 1 declared H2" }));
    expect(view.host.querySelector(".hud-message")!.classList.contains("declare-message")).toBe(true);
    view.unmount();
    const other = render(makeState({ message: "Robin declared Hearts" }));
    expect(other.host.querySelector(".hud-message")!.classList.contains("declare-message")).toBe(false);
    other.unmount();
  });
});

describe("points chip", () => {
  it("renders a new score box when the score changes", () => {
    // iOS WebKit kept the old box's width when "0" became "10", so the digits ran
    // into the "/ 80" (Jerry, 2026-10-05). A fresh element forces a fresh layout.
    vi.useFakeTimers();
    try {
      const view = render(makeState({ attacker_points: 0 }));
      const before = view.host.querySelector(".points-big");
      expect(before!.textContent).toBe("0");
      view.rerender(makeState({ attacker_points: 10 }));
      act(() => { vi.advanceTimersByTime(DUR.count + 100); });
      const after = view.host.querySelector(".points-big");
      expect(after!.textContent).toBe("10");
      expect(after).not.toBe(before);
      view.unmount();
    } finally {
      vi.useRealTimers();
    }
  });

  it("rolls up to a new score and snaps down to a new round's zero", () => {
    vi.useFakeTimers();
    try {
      const view = render(makeState({ attacker_points: 0 }));
      view.rerender(makeState({ attacker_points: 40 }));
      act(() => { vi.advanceTimersByTime(DUR.count / 4); });
      const mid = Number(view.host.querySelector(".points-big")!.textContent);
      expect(mid).toBeGreaterThan(0);
      expect(mid).toBeLessThan(40);
      // the meter reports the real score while the number rolls
      expect(view.host.querySelector(".points-bar")!.getAttribute("aria-valuenow")).toBe("40");
      act(() => { vi.advanceTimersByTime(DUR.count); });
      expect(view.host.querySelector(".points-big")!.textContent).toBe("40");
      view.rerender(makeState({ attacker_points: 0 }));
      expect(view.host.querySelector(".points-big")!.textContent).toBe("0");
      view.unmount();
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("level chip", () => {
  it("rolls through the ranks and pulses gold on a climb", () => {
    vi.useFakeTimers();
    try {
      const view = render(makeState({ levels: ["2", "2"] }));
      const chip = () => view.host.querySelector(".level-chip.team0")!;
      expect(chip().textContent).toContain("Lv 2");
      expect(chip().classList.contains("level-up")).toBe(false);
      view.rerender(makeState({ levels: ["5", "2"] }));
      expect(chip().classList.contains("level-up")).toBe(true);
      expect(view.host.querySelector(".level-chip.team1")!.classList.contains("level-up")).toBe(false);
      act(() => { vi.advanceTimersByTime(DUR.count + 50); });
      expect(chip().textContent).toContain("Lv 5");
      act(() => { vi.advanceTimersByTime(DUR.pulse); });
      expect(chip().classList.contains("level-up")).toBe(false);
      view.unmount();
    } finally {
      vi.useRealTimers();
    }
  });

  it("shows the new level at once under reduced motion", () => {
    const mm = window.matchMedia;
    window.matchMedia = ((q: string) => ({ matches: q.includes("reduce"), media: q })) as unknown as typeof window.matchMedia;
    try {
      const view = render(makeState({ levels: ["2", "2"], attacker_points: 0 }));
      view.rerender(makeState({ levels: ["K", "2"], attacker_points: 35 }));
      const chip = view.host.querySelector(".level-chip.team0")!;
      expect(chip.textContent).toContain("Lv K");
      expect(chip.classList.contains("level-up")).toBe(false);
      expect(view.host.querySelector(".points-big")!.textContent).toBe("35");
      view.unmount();
    } finally {
      window.matchMedia = mm;
    }
  });
});

describe("points pop", () => {
  it("floats the gain by the counter when the attackers score, then goes", () => {
    vi.useFakeTimers();
    try {
      const view = render(makeState({ attacker_points: 0 }));
      expect(view.host.querySelector(".points-pop")).toBeNull();
      view.rerender(makeState({ attacker_points: 10 }));
      const pop = view.host.querySelector(".points-chip .points-pop");
      expect(pop?.textContent).toBe("+10");
      expect(pop?.getAttribute("aria-hidden")).toBe("true");
      view.rerender(makeState({ attacker_points: 25 }));
      expect(view.host.querySelector(".points-pop")?.textContent).toBe("+15");
      act(() => { vi.advanceTimersByTime(1200); });
      expect(view.host.querySelector(".points-pop")).toBeNull();
      // a new round's reset is not a gain
      view.rerender(makeState({ attacker_points: 0 }));
      expect(view.host.querySelector(".points-pop")).toBeNull();
      view.unmount();
    } finally {
      vi.useRealTimers();
    }
  });

  it("shows no float under reduced motion", () => {
    const mm = window.matchMedia;
    window.matchMedia = ((q: string) => ({ matches: q.includes("reduce"), media: q })) as unknown as typeof window.matchMedia;
    try {
      const view = render(makeState({ attacker_points: 0 }));
      view.rerender(makeState({ attacker_points: 20 }));
      expect(view.host.querySelector(".points-pop")).toBeNull();
      view.unmount();
    } finally {
      window.matchMedia = mm;
    }
  });
});

it("says plainly that no trump is declared yet, with no placeholder mark", () => {
  const view = render(makeState({ trump: null, phase: "deal" }));
  const chip = view.host.querySelector(".trump-chip.none")!;
  expect(chip.querySelector(".trump-none-long")!.textContent).toBe("No trump yet");
  expect(chip.querySelector(".trump-none-short")!.textContent).toBe("No trump");
  expect(chip.textContent).not.toContain("?");
  view.unmount();
});
