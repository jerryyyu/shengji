// Table motion: plays fly in from their seat or your hand, a finished trick
// sweeps to its winner inside the linger window, the hand glides closed, and
// reduced motion turns every one of these off. jsdom has no layout or Web
// Animations, so boxes come from a stub keyed on class and `animate` is a spy.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { GameState, LastTrick, StatePlayer, Trick } from "../protocol";
import { DUR } from "../motion";
import Table from "./Table";

interface Call { el: HTMLElement; frames: Keyframe[]; opts: KeyframeAnimationOptions; anim: { cancel: ReturnType<typeof vi.fn> } }
let calls: Call[] = [];

function box(left: number, top: number, width = 50, height = 70): DOMRect {
  return { left, top, width, height, right: left + width, bottom: top + height, x: left, y: top, toJSON() {} } as DOMRect;
}

/** Layout stub: hand slots sit 30px apart by DOM order, seats and trick slots
 *  at fixed spots. */
function fakeRect(this: Element): DOMRect {
  const el = this as HTMLElement;
  const slot = el.closest(".hand-slot");
  if (slot) return box([...slot.parentElement!.children].indexOf(slot) * 30, 500);
  if (el.classList.contains("hand")) return box(0, 480, 600, 100);
  const opp = el.closest(".opponent");
  if (opp) {
    const pos = /pos-(\w+)/.exec(opp.className)![1];
    return ({ left: box(0, 200), top: box(300, 0), right: box(600, 200) } as Record<string, DOMRect>)[pos];
  }
  const play = el.closest(".trick-play");
  if (play) {
    const pos = /pos-(\w+)/.exec(play.className)![1];
    return ({ bottom: box(200, 300), left: box(100, 200), top: box(200, 100), right: box(300, 200) } as Record<string, DOMRect>)[pos];
  }
  return box(0, 0, 0, 0);
}

function player(seat: number): StatePlayer {
  return {
    seat, name: seat === 0 ? "You" : `Bot ${seat}`, is_bot: seat !== 0, connected: true,
    team: (seat % 2) as 0 | 1, cards_left: 5, is_banker: seat === 0, takeover_in: null,
    controller: seat === 0 ? "human" : "bot", reserved_for: null, reserved_secs: null,
  } as StatePlayer;
}

const HAND = ["S5", "H7", "D9", "CK", "BJ"].map((code, id) => ({ id, code }));

function makeState(over: Partial<GameState> = {}): GameState {
  return {
    type: "state", room: "TEST", you: 0, phase: "play",
    players: [0, 1, 2, 3].map(player), hand: HAND,
    levels: ["2", "2"], games_won: [0, 0], banker: 0, trump: null, turn: 2,
    declare_options: [], current_declaration: null, passed: [],
    trick: null, last_trick: null, attacker_points: 0, kitty_count: 8,
    round_result: null, message: null, notice: null,
    ...over,
  };
}

const trick = (leader: number, plays: [number, string][]): Trick =>
  ({ leader, plays: plays.map(([seat, card]) => ({ seat, cards: [card] })) });

function renderTable(state: GameState) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => root.render(<Table state={state} />));
  return {
    container,
    rerender: (next: GameState) => act(() => root.render(<Table state={next} />)),
    unmount: () => { act(() => root.unmount()); container.remove(); },
  };
}

const plays = (c: HTMLElement) => [...c.querySelectorAll<HTMLElement>(".trick-play[data-play]")];
const flights = () => calls.filter((c) => c.el.classList.contains("trick-play") && c.opts.fill !== "forwards");
const sweeps = () => calls.filter((c) => c.opts.fill === "forwards");
const reflows = () => calls.filter((c) => c.el.classList.contains("hand-slot"));

let restoreMatchMedia: (() => void) | null = null;
function reduceMotion() {
  const mm = window.matchMedia;
  window.matchMedia = ((q: string) => ({ matches: q.includes("reduce"), media: q })) as unknown as typeof window.matchMedia;
  restoreMatchMedia = () => { window.matchMedia = mm; };
}

beforeEach(() => {
  calls = [];
  vi.useFakeTimers();
  vi.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(fakeRect);
  (HTMLElement.prototype as unknown as { animate: unknown }).animate = function (this: HTMLElement, frames: Keyframe[], opts: KeyframeAnimationOptions) {
    const anim = { cancel: vi.fn(), onfinish: null };
    calls.push({ el: this, frames, opts, anim });
    return anim;
  };
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  delete (HTMLElement.prototype as unknown as { animate?: unknown }).animate;
  restoreMatchMedia?.();
  restoreMatchMedia = null;
});

describe("play flight", () => {
  it("leaves a restored table in place and flies a new play in from its seat", () => {
    const view = renderTable(makeState({ trick: trick(1, [[1, "S2"]]) }));
    expect(flights()).toHaveLength(0);

    view.rerender(makeState({ trick: trick(1, [[1, "S2"], [2, "H3"]]) }));
    expect(flights()).toHaveLength(1);
    const f = flights()[0];
    expect(f.el.dataset.seat).toBe("2");
    expect(f.opts.duration).toBe(DUR.flight);
    // the top seat's stack is at (300, 0); the top trick slot at (200, 100)
    expect(f.frames[0].transform).toMatch(/^translate\(100px, -100px\) rotate\(3deg\)/);
    expect(f.frames[f.frames.length - 1].transform).toBe("none");
    view.unmount();
  });

  it("flies your play out of the hand and glides the rest of the hand closed", () => {
    const view = renderTable(makeState({ turn: 0, trick: trick(1, [[1, "S2"]]) }));
    view.rerender(makeState({ turn: 1, hand: HAND.slice(1), trick: trick(1, [[1, "S2"], [0, "S5"]]) }));
    const f = flights();
    expect(f).toHaveLength(1);
    // S5 was the first hand card, drawn at (0, 500); your trick slot is (200, 300)
    expect(f[0].frames[0].transform).toBe("translate(-200px, 200px) rotate(-6deg) scale(1)");
    const r = reflows();
    expect(r).toHaveLength(4);
    expect(r.every((c) => c.frames[0].transform === "translateX(30px)" && c.frames[1].transform === "none")).toBe(true);
    expect(r[0].opts.duration).toBe(DUR.reflow);
    view.unmount();
  });
});

describe("trick sweep", () => {
  const four: [number, string][] = [[1, "S2"], [2, "S9"], [3, "SA"], [0, "S5"]];
  const last: LastTrick = { ...trick(1, four), winner: 3, points: 0 };

  it("lifts the winner, sweeps inside the linger window, then clears the table", () => {
    const view = renderTable(makeState({ trick: trick(1, four.slice(0, 3)) }));
    view.rerender(makeState({ trick: { leader: 3, plays: [] }, last_trick: last, hand: HAND.slice(1) }));
    // the reset frame already shows the finished trick
    expect(plays(view.container)).toHaveLength(4);
    expect(view.container.querySelector<HTMLElement>(".trick-play.winner")!.dataset.seat).toBe("3");
    expect(flights()).toHaveLength(1);   // only the fourth play is new
    expect(sweeps()).toHaveLength(0);

    act(() => { vi.advanceTimersByTime(1500 - DUR.sweep - 40); });
    expect(sweeps()).toHaveLength(4);
    expect(sweeps().every((s) => s.opts.duration === DUR.sweep && s.frames[2].opacity === 0)).toBe(true);
    // the winner's own play does not move in the gather step
    const winSweep = sweeps().find((s) => s.el.dataset.seat === "3")!;
    expect(winSweep.frames[1].transform).toContain("translate(0px, 0px)");

    act(() => { vi.advanceTimersByTime(40 + DUR.sweep); });
    expect(plays(view.container)).toHaveLength(0);
    expect(view.container.querySelector(".table-emblem")).not.toBeNull();
    expect(sweeps().every((s) => s.anim.cancel.mock.calls.length === 1)).toBe(true);
    view.unmount();
  });

  it("cancels a pending sweep on unmount and leaves no timers behind", () => {
    const view = renderTable(makeState({ trick: trick(1, four.slice(0, 3)) }));
    view.rerender(makeState({ trick: { leader: 3, plays: [] }, last_trick: last }));
    view.unmount();
    act(() => { vi.advanceTimersByTime(5000); });
    expect(sweeps()).toHaveLength(0);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("drops a play that a newer state no longer holds, mid-flight", () => {
    const view = renderTable(makeState({ trick: trick(1, [[1, "S2"]]) }));
    view.rerender(makeState({ trick: trick(1, [[1, "S2"], [2, "H3"]]) }));
    view.rerender(makeState({ trick: trick(2, [[2, "D4"]]) }));
    expect(plays(view.container).map((p) => p.dataset.play)).toEqual(["2-D4"]);
    view.unmount();
  });
});

describe("reduced motion", () => {
  it("shows every change at once, with the same linger and no animations", () => {
    reduceMotion();
    const four: [number, string][] = [[1, "S2"], [2, "S9"], [3, "SA"], [0, "S5"]];
    const view = renderTable(makeState({ turn: 0, trick: trick(1, four.slice(0, 3)) }));
    view.rerender(makeState({
      trick: { leader: 3, plays: [] }, hand: HAND.slice(1),
      last_trick: { ...trick(1, four), winner: 3, points: 0 },
    }));
    expect(plays(view.container)).toHaveLength(4);
    act(() => { vi.advanceTimersByTime(1499); });
    expect(plays(view.container)).toHaveLength(4);
    act(() => { vi.advanceTimersByTime(1); });
    expect(plays(view.container)).toHaveLength(0);
    expect(calls).toHaveLength(0);
    view.unmount();
  });
});
