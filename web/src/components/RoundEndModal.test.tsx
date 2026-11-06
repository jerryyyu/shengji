import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { GameState, RoundResult, StatePlayer } from "../protocol";
import RoundEndModal from "./RoundEndModal";

const sent: unknown[] = [];
vi.mock("../ws", () => ({ conn: { send: (m: unknown) => { sent.push(m); }, leaveToLobby: () => {} } }));

function makePlayer(seat: number, name: string, team: 0 | 1): StatePlayer {
  return {
    seat, name, is_bot: false, connected: true, team, cards_left: 0,
    is_banker: seat === 0, takeover_in: null, controller: "human",
    reserved_for: null, reserved_secs: null,
  };
}

const state: GameState = {
  type: "state", room: "TEST", you: 0, phase: "round_end",
  players: [makePlayer(0, "You", 0), makePlayer(1, "Robin", 1),
            makePlayer(2, "Sam", 0), makePlayer(3, "Ada", 1)],
  hand: [], levels: ["2", "2"], games_won: [0, 0], banker: 0, trump: null,
  turn: null, declare_options: [], current_declaration: null, passed: [],
  trick: null, last_trick: null, attacker_points: 0, kitty_count: 8,
  round_result: null, message: null, notice: null,
};

function makeResult(overrides: Partial<RoundResult> = {}): RoundResult {
  return {
    attacker_points: 0, kitty_points: 0, kitty_cards: [], winner_team: 0,
    level_change: 3, next_banker: 2, new_levels: ["2", "2"],
    game_over: false, games_won: [0, 0], point_scored: false,
    ...overrides,
  };
}

let root: ReturnType<typeof createRoot>;
let host: HTMLDivElement;
const originalShow = Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, "showModal");
const originalClose = Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, "close");
beforeEach(() => {
  // jsdom has no modal top-layer implementation; real-browser checks cover isolation.
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", { configurable: true, value: function (this: HTMLDialogElement) {
    this.setAttribute("open", "");
  } });
  Object.defineProperty(HTMLDialogElement.prototype, "close", { configurable: true, value: function (this: HTMLDialogElement) {
    this.removeAttribute("open");
  } });
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  for (const [name, descriptor] of [["showModal", originalShow], ["close", originalClose]] as const) {
    if (descriptor) Object.defineProperty(HTMLDialogElement.prototype, name, descriptor);
    else Reflect.deleteProperty(HTMLDialogElement.prototype, name);
  }
});
function renderModal(result: RoundResult, shown: GameState = state): string {
  sent.length = 0;
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  act(() => { root.render(<RoundEndModal state={shown} result={result} />); });
  return host.textContent ?? "";
}

describe("round end modal", () => {
  it("opens a named dialog, focuses its heading and prevents silent dismissal", () => {
    renderModal(makeResult());
    const dialog = host.querySelector("dialog")!;
    expect(dialog.open).toBe(true);
    expect(dialog.getAttribute("aria-labelledby")).toBe(host.querySelector("h2")!.id);
    expect(document.activeElement).toBe(host.querySelector("h2"));
    const cancel = new Event("cancel", { cancelable: true });
    dialog.dispatchEvent(cancel);
    expect(cancel.defaultPrevented).toBe(true);
  });
  it("shows a level change on an ordinary round", () => {
    const text = renderModal(makeResult({ new_levels: ["5", "2"] }));
    expect(text).toContain("Level change");
    expect(text).toContain("+3");
    expect(text).not.toContain("wins the game");
  });

  it("says a GAME was won, not '+levels', when a team holds Ace", () => {
    // The bug this guards: the levels reset to 2 while the modal still
    // announced "+3 levels", which reads as the game losing your progress.
    const text = renderModal(makeResult({ point_scored: true, games_won: [1, 0] }));
    expect(text).toContain("wins the game");
    expect(text).toContain("levels restart at 2");
    expect(text).not.toContain("Level change");
  });

  it("shows the running games-won tally once a game has been won", () => {
    const text = renderModal(makeResult({ point_scored: true, games_won: [2, 1] }));
    expect(text).toContain("Games won");
  });

  it("titles the round with the winners and a plural verb, colour prefix separable", () => {
    renderModal(makeResult({ winner_team: 1 }));
    const h2 = host.querySelector("h2")!;
    expect(h2.textContent).toBe("Orange team · Robin & Ada win the round");
    // phones hide the prefix; what remains still reads as a sentence
    expect(h2.querySelector(".title-team")!.textContent).toBe("Orange team · ");
  });

  it("does not show a tally on an ordinary round", () => {
    expect(renderModal(makeResult())).not.toContain("Games won");
  });
});

describe("buried kitty reveal", () => {
  it("names the banker and the points in the bury, above the score", () => {
    const text = renderModal(makeResult({ kitty_cards: ["S5", "HK", "D10", "C3", "C4", "C6", "C7", "C8"] }));
    expect(text).toContain("Buried by you · 25 pts");
    expect(text.indexOf("Buried by")).toBeLessThan(text.indexOf("Trick points"));
  });

  it("uses the banker's name for another seat and counts a pointless bury as 0", () => {
    const other = { ...state, banker: 1 };
    host = document.createElement("div");
    document.body.appendChild(host);
    root = createRoot(host);
    act(() => { root.render(<RoundEndModal state={other} result={makeResult({ kitty_cards: ["S2", "S3", "S4", "S6", "S7", "S8", "S9", "SJ"] })} />); });
    expect(host.textContent).toContain("Buried by Robin · 0 pts");
  });

  it("shows nothing when there are no buried cards", () => {
    expect(renderModal(makeResult())).not.toContain("Buried");
  });
});

describe("leaving from the round-end screen", () => {
  // The dialog is modal, so everything behind it (the HUD's Leave control
  // included) is inert; the way out has to live inside the dialog.
  const waiting: GameState = { ...state, ready: [0] };
  const leaveButton = () =>
    [...host.querySelectorAll("dialog button")].find((b) => /leave/i.test(b.textContent ?? "")) as
      HTMLButtonElement | undefined;

  it("offers an enabled Leave control inside the dialog while you wait for others", () => {
    const text = renderModal(makeResult(), waiting);
    expect(text).toContain("Waiting for others");
    const leave = leaveButton();
    expect(leave).toBeDefined();
    expect(leave!.disabled).toBe(false);
  });

  it("sends leave_room only on the confirming second tap", () => {
    renderModal(makeResult(), waiting);
    act(() => { leaveButton()!.click(); });
    expect(sent).toEqual([]);
    expect(leaveButton()!.textContent).toBe("Tap again to leave");
    act(() => { leaveButton()!.click(); });
    expect(sent).toEqual([{ type: "leave_room" }]);
  });

  it("is also available before you confirm the next round", () => {
    renderModal(makeResult());
    expect(leaveButton()).toBeDefined();
  });
});
