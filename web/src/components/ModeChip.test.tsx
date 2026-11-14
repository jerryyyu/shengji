// The header's mode chip: Ranked (gold, trophy) for a matched game or a
// created room switched to Ranked, Offline
// for offline play on this device, Casual for every other game. It sits
// right of the points, before the menu.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it } from "vitest";
import Hud from "./Hud";
import type { GameState } from "../protocol";

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
const chip = () => host.querySelector<HTMLElement>(".hud-bar .mode-chip");

it("a matched game shows a gold Ranked chip with a trophy", () => {
  act(() => root.render(<Hud state={state(true)} practice={false} />));
  expect(chip()!.textContent).toBe("Ranked");
  expect(chip()!.classList.contains("ranked")).toBe(true);
  expect(chip()!.querySelector("svg.mode-chip-icon")).not.toBeNull();
});

it("a created room its host switched to Ranked shows the same Ranked chip", () => {
  act(() => root.render(<Hud state={{ ...state(false), ranked: true }} practice={false} />));
  expect(chip()!.textContent).toBe("Ranked");
  expect(chip()!.classList.contains("ranked")).toBe(true);
});

it("offline play shows a grey Offline chip", () => {
  act(() => root.render(<Hud state={state(false)} practice />));
  expect(chip()!.textContent).toBe("Offline");
  expect(chip()!.classList.contains("practice")).toBe(true);
});

it("a casual game shows a grey Casual chip, as Ranked shows for a ranked one", () => {
  act(() => root.render(<Hud state={state(false)} practice={false} />));
  expect(chip()!.textContent).toBe("Casual");
  expect(chip()!.classList.contains("casual")).toBe(true);
  expect(host.textContent).not.toContain("Ranked");
  expect(host.textContent).not.toContain("Offline");
});

it("the chip sits after the points and before the menu", () => {
  act(() => root.render(<Hud state={state(true)} practice={false} />));
  const order = Array.from(host.querySelectorAll(".points-chip, .mode-chip, .hud-more")).map((e) => e.className.split(" ")[1] ?? e.className);
  expect(order).toEqual(["points-chip", "mode-chip", "hud-more"]);
});
