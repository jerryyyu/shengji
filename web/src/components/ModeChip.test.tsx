// The game's mode: a plain label at the top of the ⋯ menu, Ranked (gold) for
// a matched game or a created room switched to Ranked, Casual for every other
// online game, and none offline. The header carries no mode chip.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeAll, beforeEach, expect, it } from "vitest";
import Hud from "./Hud";
import type { GameState } from "../protocol";

// a tap unlocks the audio module's AudioContext, which jsdom lacks
beforeAll(() => {
  class SilentAudioContext { state = "running"; currentTime = 0; async resume() {} }
  (window as unknown as { AudioContext: unknown }).AudioContext = SilentAudioContext;
});

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
beforeEach(() => {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

const player = (seat: number) => ({
  seat, name: `P${seat}`, is_bot: seat !== 0, connected: true, team: seat % 2, cards_left: 3, is_banker: seat === 1,
  takeover_in: null, controller: seat ? "bot" : "human", reserved_for: null, reserved_secs: null,
});
const state = (matched: boolean) => ({
  type: "state", room: "ABCD", you: 0, phase: "play", ...(matched ? { matched: true } : {}),
  players: [0, 1, 2, 3].map(player), hand: [{ id: 1, code: "S5" }], levels: ["2", "2"], games_won: [0, 0],
  banker: 1, trump: { suit: "S", rank: "2", declarer: 1 }, turn: 1, declare_options: [],
  current_declaration: null, passed: [], trick: { leader: 1, plays: [] }, last_trick: null,
  attacker_points: 15, kitty_count: 8, message: null, notice: null, round_result: null,
}) as unknown as GameState;
const openMenu = () => act(() => host.querySelector<HTMLButtonElement>(".hud-more-btn")!.click());
const label = () => host.querySelector<HTMLElement>(".hud-menu .hud-menu-mode");

it("a matched game says Ranked, in gold, at the top of the menu", () => {
  act(() => root.render(<Hud state={state(true)} practice={false} />));
  openMenu();
  expect(label()!.textContent).toBe("Ranked");
  expect(label()!.classList.contains("ranked")).toBe(true);
  expect(host.querySelector(".hud-menu")!.firstElementChild).toBe(label());
});

it("offline play has no mode label: it is plain from the screen", () => {
  act(() => root.render(<Hud state={state(false)} practice />));
  openMenu();
  expect(host.querySelector(".hud-menu")).not.toBeNull();
  expect(label()).toBeNull();
  expect(host.textContent).not.toMatch(/Ranked|Casual|Offline/);
});

it("a casual game says Casual, and never Ranked", () => {
  act(() => root.render(<Hud state={state(false)} practice={false} />));
  openMenu();
  expect(label()!.textContent).toBe("Casual");
  expect(label()!.classList.contains("casual")).toBe(true);
  expect(host.textContent).not.toContain("Ranked");
});

it("the label is not a row to tap, and the header carries no mode chip", () => {
  act(() => root.render(<Hud state={state(true)} practice={false} />));
  expect(host.querySelector(".mode-chip")).toBeNull();
  expect(host.querySelector(".hud-bar")!.textContent).not.toMatch(/Ranked|Casual/);
  openMenu();
  expect(label()!.getAttribute("role")).toBe("none");
  expect(label()!.matches("button, [role='menuitem']")).toBe(false);
});
