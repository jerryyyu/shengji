// The phone header publishes the width of its level-and-points strip as
// --hud-strip-w and the mode chip's as --hud-mode-w, so the top seat's label
// is placed clear of both. The mode chip stands at the right, so it never
// widens the strip.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it } from "vitest";
import Hud from "./Hud";
import type { GameState } from "../protocol";

// jsdom has no layout: give the measured parts fixed boxes by class.
const BOX: Record<string, [number, number]> = {
  "hud-group": [10, 150],      // left, width of the level/trump group
  "points-chip": [170, 70],
  "mode-chip": [600, 80],
};
const proto = HTMLElement.prototype;
const saved = {
  w: Object.getOwnPropertyDescriptor(proto, "offsetWidth")!,
  l: Object.getOwnPropertyDescriptor(proto, "offsetLeft")!,
  p: Object.getOwnPropertyDescriptor(proto, "offsetParent")!,
};
function box(el: HTMLElement): [number, number] | null {
  for (const [cls, b] of Object.entries(BOX)) if (el.classList.contains(cls)) return b;
  return null;
}

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
beforeEach(() => {
  Object.defineProperty(proto, "offsetWidth", { configurable: true, get(this: HTMLElement) { return box(this)?.[1] ?? 0; } });
  Object.defineProperty(proto, "offsetLeft", { configurable: true, get(this: HTMLElement) { return box(this)?.[0] ?? 0; } });
  Object.defineProperty(proto, "offsetParent", { configurable: true, get(this: HTMLElement) {
    return this.classList.contains("table-screen") ? null : this.closest(".table-screen");
  } });
  host = document.createElement("div");
  host.className = "table-screen";
  document.body.appendChild(host);
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  Object.defineProperty(proto, "offsetWidth", saved.w);
  Object.defineProperty(proto, "offsetLeft", saved.l);
  Object.defineProperty(proto, "offsetParent", saved.p);
});

const player = (seat: number) => ({
  seat, name: `P${seat}`, is_bot: false, connected: true, team: seat % 2, cards_left: 3, is_banker: seat === 1,
  takeover_in: null, controller: "human", reserved_for: null, reserved_secs: null,
});
const state = (matched: boolean) => ({
  type: "state", room: "ABCD", you: 0, phase: "play", ...(matched ? { matched: true } : {}),
  players: [0, 1, 2, 3].map(player), hand: [{ id: 1, code: "S5" }], levels: ["2", "2"], games_won: [0, 0],
  banker: 1, trump: { suit: "S", rank: "2", declarer: 1 }, turn: 1, declare_options: [],
  current_declaration: null, passed: [], trick: { leader: 1, plays: [] }, last_trick: null,
  attacker_points: 0, kitty_count: 8, message: null, notice: null, round_result: null,
}) as unknown as GameState;

it("the strip ends after the points, and every game, casual or ranked, publishes the mode chip's width", () => {
  for (const matched of [false, true]) {
    act(() => root.render(<Hud state={state(matched)} practice={false} />));
    expect(host.querySelector(".mode-chip")).not.toBeNull();
    // group 10..160, points 170..240 -> 230 + 1 rounding px
    expect(host.style.getPropertyValue("--hud-strip-w")).toBe("231px");
    expect(host.style.getPropertyValue("--hud-mode-w")).toBe("81px");
  }
});
