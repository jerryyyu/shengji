import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeAll, describe, expect, it, vi } from "vitest";
import type { GameState, HandCard, StatePlayer } from "../protocol";
import Table from "./Table";
import Hud from "./Hud";

// a tap unlocks the audio module's AudioContext, which jsdom lacks
beforeAll(() => {
  class SilentAudioContext { state = "running"; currentTime = 0; async resume() {} }
  (window as unknown as { AudioContext: unknown }).AudioContext = SilentAudioContext;
});

function player(seat: number, name: string, extra: Partial<StatePlayer> = {}): StatePlayer {
  return {
    seat, name, is_bot: seat !== 0, connected: true, team: (seat % 2) as 0 | 1,
    cards_left: 25, is_banker: false, takeover_in: null,
    controller: seat === 0 ? "human" : "bot", reserved_for: null, reserved_secs: null,
    ...extra,
  };
}

function hand(codes: string[], firstId = 0): HandCard[] {
  return codes.map((code, i) => ({ id: firstId + i, code }));
}

function makeState(overrides: Partial<GameState> = {}): GameState {
  return {
    type: "state", room: "TEST", you: 0, phase: "play",
    players: [player(0, "Jo"), player(1, "Bot 1"), player(2, "Sam"), player(3, "Bot 3")],
    hand: [], levels: ["2", "4"], games_won: [0, 0], banker: null, trump: null,
    turn: null, declare_options: [], current_declaration: null, passed: [],
    trick: null, last_trick: null, attacker_points: 0, kitty_count: 8,
    round_result: null, message: null, notice: null,
    ...overrides,
  };
}

function render(node: React.ReactElement) {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  act(() => root.render(node));
  return {
    host,
    rerender: (next: React.ReactElement) => act(() => root.render(next)),
    unmount: () => { act(() => root.unmount()); host.remove(); },
  };
}

function withBanker(state: GameState, banker: number): GameState {
  return { ...state, banker, players: state.players.map((p) => ({ ...p, is_banker: p.seat === banker })) };
}

describe("the HUD says who attacks and marks your team", () => {
  it("labels the level chips Us and Them, yours first, never by colour alone", () => {
    const view = render(<Hud state={makeState({ you: 1, levels: ["2", "4"] })} practice={false} />);
    const chips = [...view.host.querySelectorAll(".level-chip")];
    expect(chips.map((c) => c.textContent)).toEqual(["Us 4", "Them 2"]);
    expect(chips[0].classList.contains("team1")).toBe(true);
    view.unmount();
  });

  it("labels the points counter Attackers before a banker, then Us or Them", () => {
    const view = render(<Hud state={makeState({ attacker_points: 40 })} practice={false} />);
    const label = () => view.host.querySelector(".points-label")!.textContent;
    expect(label()).toBe("Attackers");
    // Bot 1 banks: their team defends, so Us attacks
    view.rerender(<Hud state={withBanker(makeState({ attacker_points: 40 }), 1)} practice={false} />);
    expect(label()).toBe("Attackers · Us");
    expect(view.host.querySelector(".points-chip")!.classList.contains("attack-us")).toBe(true);
    // Sam (your partner) banks: Them attacks
    view.rerender(<Hud state={withBanker(makeState({ attacker_points: 40 }), 2)} practice={false} />);
    expect(label()).toBe("Attackers · Them");
    expect(view.host.querySelector(".points-chip")!.textContent).toContain("40");
    view.unmount();
  });

  it("says in words who banks: You bank, Sam banks", () => {
    const mine = render(<Table state={withBanker(makeState({ turn: 0, hand: hand(["S3"]) }), 0)} />);
    expect(mine.host.querySelector(".you-tagline .you-bank")!.textContent).toBe("You bank");
    mine.unmount();
    const partner = render(<Table state={withBanker(makeState(), 2)} />);
    const pill = [...partner.host.querySelectorAll(".opponent")].find((o) => o.textContent?.includes("Sam"))!;
    expect(pill.querySelector(".bank-tag")!.textContent).toBe("banks");
    expect(pill.querySelector(".opp-name")!.textContent).toContain("Sam");
    partner.unmount();
  });
});

describe("declaring", () => {
  it("shows a countdown on the declare window, a one-line explanation and your own declaration as yours", () => {
    const state = makeState({
      phase: "declare", hand: hand(["H2", "S5"]), declare_options: [[0]], declare_deadline: 4,
      current_declaration: { seat: 0, cards: ["H2"] },
    });
    const view = render(<Table state={state} />);
    const ring = view.host.querySelector(".action-bar .timer-ring");
    expect(ring).not.toBeNull();
    expect(ring!.getAttribute("aria-label")).toBe("4 seconds left");
    expect(view.host.querySelector(".follow-hint.phase-help")!.textContent)
      .toBe("Declaring picks trump and makes you banker. A pair outbids a single.");
    expect(view.host.querySelector(".declare-tag")!.textContent).toBe("You declared ♥2");
    view.unmount();
  });

  it("runs the declare ring down from full, with its seconds, red throughout its five", () => {
    vi.useFakeTimers();
    try {
      const view = render(<Table state={makeState({ phase: "declare", hand: hand(["S5"]), declare_deadline: 5 })} />);
      const ring = () => view.host.querySelector(".action-bar .timer-ring");
      expect(ring()!.textContent).toBe("5");
      expect(ring()!.getAttribute("style")).toContain("--ring-deg: 360deg");
      expect(ring()!.className).toContain("low");
      act(() => { vi.advanceTimersByTime(2000); });
      expect(ring()!.textContent).toBe("3");
      expect(ring()!.getAttribute("style")).toContain("--ring-deg: 216deg");
      view.unmount();
    } finally { vi.useRealTimers(); }
  });

  it("names another player's declaration in the past tense, and drops the ring once you are done", () => {
    const state = withBanker(makeState({
      phase: "declare", hand: hand(["S5"]), declare_deadline: 3, passed: [0],
      current_declaration: { seat: 2, cards: ["D2", "D2"] },
    }), 1);
    const view = render(<Table state={state} />);
    expect(view.host.querySelector(".declare-tag")!.textContent).toBe("Sam declared ♦2 pair");
    expect(view.host.querySelector(".action-bar .timer-ring")).toBeNull();
    view.unmount();
  });
});

describe("burying", () => {
  it("marks the 8 kitty cards, totals the points chosen and explains the kitty multiplier", () => {
    const before = hand(["S3", "S4", "HK"]);
    const deal = withBanker(makeState({ phase: "declare", hand: before }), 0);
    const view = render(<Table state={deal} />);
    const kitty = hand(["D5", "D10", "C3", "C4", "C6", "C7", "C8", "C9"], 100);
    const bury = withBanker(makeState({ phase: "bury", turn: 0, hand: [...before, ...kitty] }), 0);
    view.rerender(<Table state={bury} />);
    const marked = [...view.host.querySelectorAll(".hand-slot.from-kitty")].map((s) => Number((s as HTMLElement).dataset.id));
    expect(marked.sort((a, b) => a - b)).toEqual(kitty.map((c) => c.id));
    expect(view.host.querySelector(".bury-points")!.textContent).toBe("Burying 0 points");
    const click = (id: number) => act(() => {
      (view.host.querySelector(`.hand-slot[data-id="${id}"] .card`) as HTMLElement).click();
    });
    click(100); click(101); click(2);
    expect(view.host.querySelector(".bury-points")!.textContent).toBe("Burying 25 points");
    expect(view.host.querySelector(".follow-hint.phase-help")!.textContent).toContain("count double for them (×4 on a pair lead)");
    // once the bury is in, the marks go
    const play = withBanker(makeState({ phase: "play", turn: 0, hand: before }), 0);
    view.rerender(<Table state={play} />);
    expect(view.host.querySelector(".from-kitty")).toBeNull();
    view.unmount();
  });
});

describe("the last trick", () => {
  it("reopens the previous trick with its plays and winner until dismissed", () => {
    vi.useFakeTimers();
    try {
      const last = {
        leader: 1, winner: 3, points: 15,
        plays: [
          { seat: 1, cards: ["S5"] }, { seat: 2, cards: ["S9"] },
          { seat: 3, cards: ["SK"] }, { seat: 0, cards: ["S3"] },
        ],
      };
      const view = render(<Table state={withBanker(makeState({ turn: 1, last_trick: last }), 1)} />);
      const btn = [...view.host.querySelectorAll("button")].find((b) => b.textContent === "Last trick")!;
      act(() => btn.click());
      const panel = view.host.querySelector(".last-trick-panel")!;
      expect(panel.querySelector(".last-trick-sum")!.textContent).toBe("Bot 3 wins · 15 pts");
      const rows = [...panel.querySelectorAll(".last-trick-row")].map((r) => r.textContent);
      expect(rows).toEqual(["Bot 1lead♠5", "Sam♠9", "Bot 3♠Kwins", "You♠3"]);
      // it stays well past the 1.5 s linger of a finished trick
      act(() => { vi.advanceTimersByTime(10_000); });
      expect(view.host.querySelector(".last-trick-panel")).not.toBeNull();
      act(() => (panel.querySelector(".last-trick-close") as HTMLElement).click());
      expect(view.host.querySelector(".last-trick-panel")).toBeNull();
      view.unmount();
    } finally {
      vi.useRealTimers();
    }
  });

  it("offers no control before any trick is finished", () => {
    const view = render(<Table state={makeState({ turn: 1 })} />);
    expect([...view.host.querySelectorAll("button")].some((b) => b.textContent === "Last trick")).toBe(false);
    view.unmount();
  });
});

describe("a seat whose owner left", () => {
  it("reads Bot (Alice left), with no takeover countdown", () => {
    const alice = player(2, "Alice", {
      is_bot: false, connected: false, controller: "bot_cover", reserved_for: "Alice",
      reserved_secs: 28, left: true,
    });
    const state = makeState({ players: [player(0, "Jo"), player(1, "Bot 1"), alice, player(3, "Bot 3")] });
    const view = render(<Table state={state} />);
    const pill = view.host.querySelector(".opponent.pos-top")!;
    expect(pill.querySelector(".opp-name-text")!.textContent).toBe("Bot (Alice left)");
    expect(pill.textContent).not.toMatch(/bot in \d+s/);
    view.unmount();
  });

  it("keeps the countdown for a real disconnect", () => {
    const alice = player(2, "Alice", {
      is_bot: false, connected: false, controller: "bot_cover", takeover_in: 28,
    });
    const state = makeState({ players: [player(0, "Jo"), player(1, "Bot 1"), alice, player(3, "Bot 3")] });
    const view = render(<Table state={state} />);
    expect(view.host.querySelector(".opponent.pos-top .off-tag")!.textContent).toBe("offline — bot in 28s");
    view.unmount();
  });
});
