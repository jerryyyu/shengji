import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { DUR } from "../motion";
import type { GameState, Notice, StatePlayer } from "../protocol";
import Hud from "./Hud";
import { clearToast, currentToast } from "../toast";

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

describe("failed-throw notice and table messages: told once, as the one toast", () => {
  // each test sits at its own table, so what one told is news to the next
  let n = 0;
  const at = (over: Partial<GameState> = {}) => makeState({ room: `T${n}`, ...over });
  beforeEach(() => { n += 1; clearToast(); });
  const toast = () => currentToast();

  it("names what was thrown and what was forced, politely", () => {
    const view = render(at({ notice: failedThrow() }));
    expect(toast()?.text).toBe("Throw failed. You threw ♣7 ♣7 ♦7 ♦7 and had to play ♦7 ♦7.");
    expect(toast()?.info).toBe(true);
    // no banner of its own in the header
    expect(view.host.querySelector(".hud-notice, .hud-message")).toBeNull();
    view.unmount();
  });

  it("names the other player when the throw was not yours", () => {
    const view = render(at({ notice: failedThrow(1, 1) }));
    expect(toast()?.text).toContain("Robin threw");
    view.unmount();
  });

  it("tells a notice once while the same notice stands, even across a remount", () => {
    const state = at({ notice: failedThrow() });
    const view = render(state);
    act(() => clearToast());
    // the server keeps sending the same notice for several plays
    view.rerender({ ...state });
    expect(toast()).toBeNull();
    view.unmount();
    const again = render(state);
    expect(toast()).toBeNull();
    again.rerender(at({ notice: failedThrow(2) }));
    expect(toast()?.text).toContain("Throw failed.");
    again.unmount();
  });

  it("tells a reused notice id in the next round", () => {
    const roundOne = at({ notice: failedThrow(1) });
    const view = render(roundOne);
    expect(toast()?.text).toContain("Throw failed.");
    act(() => clearToast());
    // Round creates its notice sequence afresh, so the first failed throw of
    // the next round may again be id 1 at the same table.
    view.rerender(at({ notice: null, phase: "round_end" }));
    view.rerender(at({ notice: failedThrow(1), phase: "play", levels: ["3", "2"] }));
    expect(toast()?.text).toContain("Throw failed.");
    view.unmount();
  });

  it("tells no notice outside play", () => {
    const view = render(at({ notice: failedThrow(4), phase: "round_end" }));
    expect(toast()).toBeNull();
    view.unmount();
  });

  it("tells the notice, not the one-play message that restates it", () => {
    const view = render(at({ notice: failedThrow(), message: "Throw failed — forced to play D7+D7" }));
    expect(toast()?.text).toContain("You threw");
    view.unmount();
  });

  it("tells an ordinary message, once until the next play clears it", () => {
    const view = render(at({ message: "No declaration — trump flipped from the kitty: S" }));
    expect(toast()?.text).toBe("No declaration — trump flipped from the kitty: ♠");
    act(() => clearToast());
    view.rerender(at({ message: "No declaration — trump flipped from the kitty: S" }));
    expect(toast()).toBeNull();
    view.rerender(at({ message: null }));
    view.rerender(at({ message: "No declaration — trump flipped from the kitty: S" }));
    expect(toast()).not.toBeNull();
    view.unmount();
  });

  it("tells no declaration: its tag under the declared cards does", () => {
    const view = render(at({ message: "Seat 1 declared H2" }));
    expect(toast()).toBeNull();
    view.unmount();
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
      expect(chip().textContent).toContain("Us 2");
      expect(chip().classList.contains("level-up")).toBe(false);
      view.rerender(makeState({ levels: ["5", "2"] }));
      expect(chip().classList.contains("level-up")).toBe(true);
      expect(view.host.querySelector(".level-chip.team1")!.classList.contains("level-up")).toBe(false);
      act(() => { vi.advanceTimersByTime(DUR.count + 50); });
      expect(chip().textContent).toContain("Us 5");
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
      expect(chip.textContent).toContain("Us K");
      expect(chip.classList.contains("level-up")).toBe(false);
      expect(view.host.querySelector(".points-big")!.textContent).toBe("35");
      view.unmount();
    } finally {
      window.matchMedia = mm;
    }
  });
});

describe("games score", () => {
  it("is absent until a game is won, then reads Games Us–Them with your team first", () => {
    const view = render(makeState());
    expect(view.host.querySelector(".games-chip")).toBeNull();
    expect(view.host.textContent).not.toContain("Games");
    view.rerender(makeState({ games_won: [1, 0] }));
    const chip = () => view.host.querySelector(".games-chip")!;
    expect(chip().textContent).toBe("Games 1–0");
    expect(chip().getAttribute("aria-label")).toBe("Games: Us 1, Them 0");
    // the level chips carry no star of their own
    expect(view.host.querySelector(".level-chip.team0")!.textContent).not.toMatch(/★/);
    // seen from the other team, Us is that team
    view.rerender(makeState({ you: 1, games_won: [1, 0],
                              players: [makePlayer({ seat: 0, name: "Robin", team: 0 }),
                                        makePlayer({ seat: 1, name: "You", team: 1 })] }));
    expect(chip().textContent).toBe("Games 0–1");
    expect(chip().getAttribute("aria-label")).toBe("Games: Us 0, Them 1");
    view.unmount();
  });

  it("sits with the levels, after the other team's chip", () => {
    const view = render(makeState({ games_won: [2, 3] }));
    const group = view.host.querySelector(".level-chip.team1")!.parentElement!;
    expect(group.lastElementChild?.className).toContain("games-chip");
    view.unmount();
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

describe("leaving a ranked table", () => {
  const leave = (host: HTMLElement) => {
    act(() => host.querySelector<HTMLButtonElement>(".hud-more-btn")!.click());
    act(() => host.querySelector<HTMLButtonElement>(".hud-menu-row.leave")!.click());
  };
  it("warns a signed-in player about the result but gives a guest the casual warning", () => {
    const signedIn = render(makeState({ matched: true }));
    leave(signedIn.host);
    expect(signedIn.host.querySelector("[role='alertdialog'] p")!.textContent).toBe("This round counts as at best a draw.");
    signedIn.unmount();
    const guest = render(makeState({ matched: true, guest: true }));
    leave(guest.host);
    // a guest sees no ranked words
    expect(guest.host.querySelector("[role='alertdialog'] p")).toBeNull();
    expect(guest.host.querySelector("[role='alertdialog']")!.textContent).not.toMatch(/rank|draw/i);
    guest.unmount();
  });
});

describe("the header holds the game's state only", () => {
  it("has no mute, Coach, Leave, code, phase or kitty chip: those live in ⋯", () => {
    const view = render(makeState({ matched: true, phase: "bury", allow_joiners: true }));
    const bar = view.host.querySelector(".hud-bar")!;
    for (const gone of [".mute-btn", ".coach-chip", ".leave-btn", ".room-chip", ".phase-chip", ".kitty-chip"]) {
      expect(bar.querySelector(gone)).toBeNull();
    }
    const buttons = [...bar.querySelectorAll("button")];
    expect(buttons.map((b) => b.getAttribute("aria-label") ?? b.textContent)).toEqual(["More"]);
    expect(bar.textContent).not.toContain("TEST");
    expect(bar.textContent).not.toMatch(/Leave|Coach|Burying/);
    // the state that stays: levels, trump, points; the mode lives in ⋯
    expect(bar.querySelectorAll(".level-chip")).toHaveLength(2);
    expect(bar.querySelector(".trump-chip")).not.toBeNull();
    expect(bar.querySelector(".points-chip")).not.toBeNull();
    expect(bar.textContent).not.toMatch(/Ranked|Casual/);
    view.unmount();
  });

  it("is one quiet strip: no divider, no mode chip, and points read N/80 with no team word", () => {
    const view = render(makeState({ matched: true, attacker_points: 35, banker: 1 }));
    const bar = view.host.querySelector(".hud-bar")!;
    expect(bar.querySelector(".hud-divider, .points-divider, [role='separator']")).toBeNull();
    expect(bar.querySelector(".mode-chip")).toBeNull();
    expect(bar.querySelector(".points-label, .points-bar")).toBeNull();
    const points = bar.querySelector(".points-chip")!;
    expect(points.textContent).toBe("35/80");
    expect(points.textContent).not.toMatch(/them|attackers|us/i);
    view.unmount();
  });

  it("dots the points in the attacking team's colour once a banker exists, and not before", () => {
    // you sit at seat 0, team 0: seat 1 banks, so your team attacks
    const view = render(makeState({ attacker_points: 20, banker: 1 }));
    const dot = () => view.host.querySelector(".points-chip .points-dot")!;
    expect(dot().className).toBe("points-dot t0");
    expect(dot().getAttribute("aria-hidden")).toBe("true");
    expect(view.host.querySelector(".points-chip")!.classList.contains("team0")).toBe(true);
    view.rerender(makeState({ attacker_points: 20, banker: 0 }));
    expect(dot().className).toBe("points-dot t1");
    view.rerender(makeState({ attacker_points: 0, banker: null, phase: "declare" }));
    expect(dot().className).toBe("points-dot");
    expect(view.host.querySelector(".points-chip")!.textContent).toBe("0/80");
    view.unmount();
  });

  it("the ⋯ menu opens with the mode as a plain label: Ranked or Casual", () => {
    const view = render(makeState({ matched: true }));
    act(() => view.host.querySelector<HTMLButtonElement>(".hud-more-btn")!.click());
    const mode = view.host.querySelector(".hud-menu")!.firstElementChild!;
    expect(mode.className).toBe("hud-menu-mode ranked");
    expect(mode.textContent).toBe("Ranked");
    expect(mode.getAttribute("role")).toBe("none");
    expect(mode.tagName).toBe("DIV");
    view.rerender(makeState({ matched: false }));
    expect(view.host.querySelector(".hud-menu-mode")!.textContent).toBe("Casual");
    view.unmount();
  });

  it("the ⋯ menu carries the code, the settings and Leave game", () => {
    const view = render(makeState({ matched: true, allow_joiners: true, opener: 0 }));
    act(() => view.host.querySelector<HTMLButtonElement>(".hud-more-btn")!.click());
    const menu = view.host.querySelector(".hud-menu")!;
    expect(menu.querySelector(".hud-menu-code-text")!.textContent).toBe("TEST");
    expect([...menu.querySelectorAll(".hud-menu-row")].map((r) => r.textContent))
      .toEqual(["Invite link", "Allow joiners", "Coach", "Sound", "How to play›", "Leave game"]);
    view.unmount();
  });

  it("Allow joiners is in the menu only for the table's opener", () => {
    const rows = (opener: number) => {
      const view = render(makeState({ matched: true, allow_joiners: true, opener }));
      act(() => view.host.querySelector<HTMLButtonElement>(".hud-more-btn")!.click());
      const text = [...view.host.querySelectorAll(".hud-menu-row")].map((r) => r.textContent);
      view.unmount();
      return text;
    };
    expect(rows(0)).toContain("Allow joiners");
    expect(rows(1)).not.toContain("Allow joiners");
  });

  it("Allow joiners is at every table that takes joiners: casual and unmatched too, never a test room", () => {
    const rows = (over: Record<string, unknown>) => {
      const view = render(makeState({ opener: 0, ...over }));
      act(() => view.host.querySelector<HTMLButtonElement>(".hud-more-btn")!.click());
      const text = [...view.host.querySelectorAll(".hud-menu-row")].map((r) => r.textContent);
      view.unmount();
      return text;
    };
    expect(rows({ matched: false, allow_joiners: false })).toContain("Allow joiners");
    expect(rows({ matched: false, ranked: true, allow_joiners: true })).toContain("Allow joiners");
    // the server leaves the flag off a room that never seats a stranger
    expect(rows({ matched: true })).not.toContain("Allow joiners");
  });

  it("the stylesheet keeps no rules for the chips that left the bar", async () => {
    const { readFileSync } = await import("node:fs");
    const css = readFileSync(`${import.meta.dirname}/../index.css`, "utf8");
    for (const gone of [".mute-btn", ".coach-chip", "button.room-chip", ".phase-chip", ".kitty-chip", ".hud-bar .leave-btn"]) {
      expect(css).not.toContain(gone);
    }
  });
});
