import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { GameState, RoundResult, StatePlayer } from "../protocol";
import RoundEndModal from "./RoundEndModal";
import { auth } from "../auth";

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

  const alert = () => host.querySelector<HTMLElement>("[role='alertdialog']");
  const choice = (label: string) =>
    [...(alert()?.querySelectorAll("button") ?? [])].find((b) => b.textContent === label) as
      HTMLButtonElement | undefined;

  it("opens the leave alert, and sends leave_room only on Leave", () => {
    renderModal(makeResult(), waiting);
    act(() => { leaveButton()!.click(); });
    expect(sent).toEqual([]);
    expect(alert()!.textContent).toContain("Leave this game?");
    act(() => { choice("Leave")!.click(); });
    expect(sent).toEqual([{ type: "leave_room" }]);
  });

  it("a ranked game's alert says what leaving does to the result", () => {
    renderModal(makeResult(), { ...waiting, matched: true });
    act(() => { leaveButton()!.click(); });
    expect(alert()!.querySelector("h2")!.textContent).toBe("Leave this ranked game?");
  });

  it("has no timer: the alert waits, and Keep playing closes it", () => {
    vi.useFakeTimers();
    try {
      renderModal(makeResult(), waiting);
      act(() => { leaveButton()!.click(); });
      act(() => { vi.advanceTimersByTime(30_000); });
      expect(alert()).not.toBeNull();
      act(() => { choice("Keep playing")!.click(); });
      expect(alert()).toBeNull();
      expect(leaveButton()!.textContent).toBe("Leave game");
      expect(sent).toEqual([]);
    } finally {
      vi.useRealTimers();
    }
  });

  it("is also available before you confirm the next round", () => {
    renderModal(makeResult());
    expect(leaveButton()).toBeDefined();
  });
});

describe("round end rating line", () => {
  afterEach(() => auth.reset());

  async function signedOutWithSignIn() {
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/auth/config") return { status: 200, json: async () => ({ google_client_id: "cid" }) } as Response;
      return { status: 401, json: async () => ({}) } as Response;
    }) as typeof fetch;
    await auth.init();
  }

  it("a seat taken mid-round from an open table reads Unranked · joined mid-round", () => {
    renderModal(makeResult({ unranked: "joined" }));
    expect(host.querySelector(".rating-unranked")!.textContent).toBe("Unranked · joined mid-round");
    expect(host.querySelector(".rating-delta")).toBeNull();
  });

  it("shows a signed-in player's rating and this round's change", () => {
    renderModal(makeResult({ rating: { rating: 1712, delta: 9 } }));
    const line = host.querySelector(".rating-line")!;
    expect(line.textContent).toContain("Your rating 1712");
    expect(line.querySelector(".rating-delta")!.textContent).toBe("▲ +9");
    expect(line.querySelector(".rating-delta")!.className).toContain("delta-up");
    expect(line.querySelector(".rating-game")).toBeNull();
    expect(host.querySelector(".rating-guest")).toBeNull();
  });

  it("shows a loss and, on the round that wins a game, the game's total", () => {
    renderModal(makeResult({ point_scored: true, games_won: [1, 0],
                             rating: { rating: 1688, delta: -4, game_delta: 31 } }));
    const line = host.querySelector(".rating-line")!;
    expect(line.querySelector(".rating-delta")!.textContent).toBe("▼ −4");
    expect(line.querySelector(".rating-game")!.textContent).toBe("+31 this game");
  });

  it("shows the game total on the game-over screen", () => {
    renderModal(makeResult({ game_over: true, rating: { rating: 1740, delta: 12, game_delta: 55 } }));
    expect(host.querySelector(".victory .rating-line")!.textContent).toContain("+55 this game");
  });

  it("offers a guest Sign in to be ranked in place of the rating line; a tap opens sign-in", async () => {
    await signedOutWithSignIn();
    renderModal(makeResult());
    const guest = host.querySelector(".rating-guest")!;
    expect(host.querySelector(".rating-line")).toBeNull();
    expect(host.querySelector(".google-signin-slot")).toBeNull();
    const link = guest.querySelector<HTMLButtonElement>(".rating-signin")!;
    expect(link.textContent).toBe("Sign in to be ranked");
    expect(guest.textContent).toBe("Sign in to be ranked");
    act(() => { link.click(); });
    expect(host.querySelector(".rating-signin")).toBeNull();
    expect(host.querySelector(".google-signin-slot")).not.toBeNull();
  });

  it("says nothing about ratings where sign-in is off", () => {
    renderModal(makeResult());
    expect(host.querySelector(".rating-line")).toBeNull();
    expect(host.querySelector(".rating-guest")).toBeNull();
  });
});

describe("headline first, details behind a disclosure", () => {
  it("leads with the level change and new levels; the score grid and kitty wait under Details", () => {
    renderModal(makeResult({ new_levels: ["5", "2"], attacker_points: 30,
      kitty_cards: ["S5", "HK", "D10", "C3", "C4", "C6", "C7", "C8"] }));
    const modal = host.querySelector(".modal")!;
    const headline = modal.querySelector(".result-headline")!;
    expect(headline.querySelector(".result-change")!.textContent).toBe("+3 levels");
    expect(headline.textContent).toContain("Now");
    expect(headline.textContent).toContain("5");
    expect(headline.textContent).toContain("Attackers 30 of 80");
    const details = modal.querySelector<HTMLDetailsElement>("details.result-details")!;
    expect(details.open).toBe(false);
    expect(details.querySelector("summary")!.textContent).toBe("Details");
    expect(details.querySelector(".result-grid")).not.toBeNull();
    expect(details.querySelector(".kitty-reveal")).not.toBeNull();
    expect(details.querySelector(".result-verdict")).not.toBeNull();
    // the headline comes before the details, and Next round and Leave stay outside them
    expect(headline.compareDocumentPosition(details) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    const next = [...modal.querySelectorAll("button")].find((b) => b.textContent === "Next round")!;
    expect(details.contains(next)).toBe(false);
    act(() => next.click());
    expect(sent).toEqual([{ type: "next_round" }]);
    const leave = [...modal.querySelectorAll("button")].find((b) => /leave/i.test(b.textContent ?? ""));
    expect(leave && details.contains(leave)).toBe(false);
  });

  it("says one level, and a won game, in the headline", () => {
    renderModal(makeResult({ level_change: 1 }));
    expect(host.querySelector(".result-change")!.textContent).toBe("+1 level");
    act(() => root.unmount());
    host.remove();
    renderModal(makeResult({ point_scored: true, games_won: [1, 0] }));
    expect(host.querySelector(".result-change")!.textContent).toBe("Game won");
    expect(host.querySelector(".result-headline")!.textContent).toContain("Levels restart at");
  });
});
