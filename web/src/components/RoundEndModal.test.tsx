import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { GameState, RoundResult, StatePlayer } from "../protocol";
import RoundEndModal from "./RoundEndModal";
import { auth } from "../auth";

const sent: unknown[] = [];
vi.mock("../ws", () => ({ conn: { send: (m: unknown) => { sent.push(m); } } }));

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

/** A queue room: its rounds are rated. */
const ranked: GameState = { ...state, matched: true };

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
function renderModal(result: RoundResult, shown: GameState = state, clock: number | null = null): string {
  sent.length = 0;
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  act(() => { root.render(<RoundEndModal state={shown} result={result} clock={clock} />); });
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
    expect(text).toContain("Us go up 3, to 5.");
    expect(text).not.toContain("win the game");
  });

  it("says a GAME was won, not '+levels', when a team holds Ace", () => {
    // The bug this guards: the levels reset to 2 while the modal still
    // announced "+3 levels", which reads as the game losing your progress.
    const text = renderModal(makeResult({ point_scored: true, games_won: [1, 0] }));
    expect(text).toContain("win the game");
    expect(text).toContain("Levels restart at 2.");
    expect(text).not.toContain("go up");
  });

  it("shows the running games-won tally once a game has been won", () => {
    const text = renderModal(makeResult({ point_scored: true, games_won: [2, 1] }));
    expect(text).toContain("Games: Us 2 · Them 1");
  });

  it("a game won says so up front: the game in the title, the games score, Next game and Leave", () => {
    renderModal(makeResult({ point_scored: true, games_won: [1, 0], winner_team: 0 }));
    const h2 = host.querySelector("h2")!;
    expect(h2.textContent).toBe("You & Sam win the game");
    expect(host.querySelector(".modal.game-won")).not.toBeNull();
    expect(host.querySelector(".game-won-crown")!.getAttribute("aria-hidden")).toBe("true");
    // the score sits in the main view, outside Details
    const games = host.querySelector(".result-games")!;
    expect(games.closest("details")).toBeNull();
    expect(games.textContent).toBe("Games: Us 1 · Them 0Levels restart at 2.");
    const buttons = [...host.querySelectorAll("button")].map((b) => b.textContent);
    expect(buttons).toContain("Next game");
    expect(buttons).not.toContain("Next round");
    expect(buttons).toContain("Leave game");
    expect(buttons).not.toContain("Back to lobby");
    const next = [...host.querySelectorAll("button")].find((b) => b.textContent === "Next game")!;
    act(() => next.click());
    expect(sent).toEqual([{ type: "next_round" }]);
  });

  it("the games score puts your team first, and a loss names your side", () => {
    renderModal(makeResult({ point_scored: true, games_won: [2, 3], winner_team: 1 }),
                { ...state, you: 1 });
    expect(host.querySelector("h2")!.textContent).toBe("You & Ada win the game");
    expect(host.querySelector(".result-games > span")!.textContent).toBe("Games: Us 3 · Them 2");
    renderModal(makeResult({ point_scored: true, games_won: [0, 1], winner_team: 1 }));
    expect(host.querySelector("h2")!.textContent).toBe("You & Sam lose the game");
    expect(host.querySelector(".result-games > span")!.textContent).toBe("Games: Us 0 · Them 1");
  });

  it("an ordinary round keeps Next round and no games score", () => {
    renderModal(makeResult());
    expect(host.querySelector(".result-games")).toBeNull();
    expect(host.querySelector(".game-won-crown")).toBeNull();
    expect([...host.querySelectorAll("button")].map((b) => b.textContent)).toContain("Next round");
  });

  it("has no game-over card: even a result marked game_over is a round end with Next game", () => {
    renderModal(makeResult({ point_scored: true, game_over: true, games_won: [1, 0] }));
    expect(host.querySelector(".victory")).toBeNull();
    expect(host.textContent).not.toContain("Back to lobby");
    expect([...host.querySelectorAll("button")].map((b) => b.textContent)).toContain("Next game");
  });

  it("titles the round with the winners and a plural verb, never a colour", () => {
    renderModal(makeResult({ winner_team: 0 }));
    const h2 = host.querySelector("h2")!;
    expect(h2.textContent).toBe("You & Sam win the round");
    expect(host.textContent).not.toMatch(/Blue|Orange/);
  });

  it("says your side lost when the other team wins the round", () => {
    renderModal(makeResult({ winner_team: 1 }));
    const h2 = host.querySelector("h2")!;
    expect(h2.textContent).toBe("You & Sam lose the round");
    expect(h2.className).toContain("team0");
    expect(h2.textContent).not.toContain("Robin & Ada win");
  });

  it("does not show a tally on an ordinary round", () => {
    expect(renderModal(makeResult())).not.toContain("Games won");
  });
});

describe("buried kitty reveal", () => {
  it("labels the kitty with its points", () => {
    renderModal(makeResult({ kitty_cards: ["S5", "HK", "D10", "C3", "C4", "C6", "C7", "C8"] }));
    expect(host.querySelector(".round-end-kitty .round-end-col-label")!.textContent).toBe("Kitty · 25 points");
  });

  it("counts a pointless bury as 0", () => {
    renderModal(makeResult({ kitty_cards: ["S2", "S3", "S4", "S6", "S7", "S8", "S9", "SJ"] }), { ...state, banker: 1 });
    expect(host.querySelector(".round-end-kitty .round-end-col-label")!.textContent).toBe("Kitty · 0 points");
  });

  it("shows nothing when there are no buried cards", () => {
    expect(renderModal(makeResult())).not.toContain("Kitty");
  });
});

describe("leaving from the round-end screen", () => {
  // The dialog is modal, so everything behind it (the HUD's Leave control
  // included) is inert; the way out has to live inside the dialog.
  const waiting: GameState = { ...state, ready: [0] };
  const leaveButton = () =>
    [...host.querySelectorAll("dialog button")].find((b) => b.textContent === "Leave game") as
      HTMLButtonElement | undefined;
  const nextButton = () =>
    [...host.querySelectorAll("dialog button")].find((b) => /Next round|Waiting for others/.test(b.textContent ?? "")) as
      HTMLButtonElement;

  for (const [kind, shown] of [["casual", state], ["ranked", { ...state, matched: true }]] as const) {
    it(`puts Leave beside Next round in one row, the same in a ${kind} room`, () => {
      renderModal(makeResult(), shown);
      const leave = leaveButton()!;
      expect(leave).toBeDefined();
      expect(leave.className).toBe("btn danger big dialog-leave-btn");
      expect(nextButton().className).toContain("btn primary big");
      expect(leave.parentElement).toBe(nextButton().parentElement);
      expect(leave.parentElement!.className).toBe("round-end-actions");
      expect(nextButton().compareDocumentPosition(leave) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    });
  }

  it("stays enabled while you wait for others", () => {
    const text = renderModal(makeResult(), waiting);
    expect(text).toContain("Waiting for others");
    expect(leaveButton()!.disabled).toBe(false);
  });

  const sheet = () => host.querySelector<HTMLDialogElement>("[role='alertdialog']");
  const sheetText = () => `${sheet()!.querySelector("h2")!.textContent} / ${sheet()!.querySelector("p")!.textContent}`;

  for (const [kind, shown] of [["casual", waiting], ["ranked", { ...waiting, matched: true }],
                               ["guest at a ranked", { ...waiting, matched: true, guest: true }]] as const) {
    it(`asks through the leave sheet, which says it is free, in a ${kind} game`, () => {
      renderModal(makeResult(), shown);
      act(() => { leaveButton()!.click(); });
      expect(sent).toEqual([]);
      expect(sheetText()).toBe("Leave the game? / Free. This round's result is kept.");
      expect([...sheet()!.querySelectorAll("button")].map((b) => b.textContent)).toEqual(["Stay", "Leave"]);
      act(() => { sheet()!.querySelector<HTMLButtonElement>(".leave-sheet-leave")!.click(); });
      expect(sent).toEqual([{ type: "leave_room" }]);
      expect(sheet()).toBeNull();
    });
  }

  it("Stay closes the sheet and sends nothing", () => {
    renderModal(makeResult(), { ...state, matched: true });
    act(() => { leaveButton()!.click(); });
    act(() => { sheet()!.querySelector<HTMLButtonElement>(".leave-sheet-stay")!.click(); });
    expect(sheet()).toBeNull();
    expect(sent).toEqual([]);
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
    renderModal(makeResult({ unranked: "joined" }), ranked);
    expect(host.querySelector(".rating-unranked")!.textContent).toBe("Unranked · joined mid-round");
    expect(host.querySelector(".rating-delta")).toBeNull();
  });

  it("puts a signed-in player's change for the round on the result line, with no separate rating line", () => {
    renderModal(makeResult({ rating: { rating: 1712, delta: 9 } }), ranked);
    const bit = host.querySelector(".result-line .result-rating")!;
    expect(bit.textContent).toBe(" · +9");
    expect(bit.className).toContain("delta-up");
    expect(host.querySelector(".rating-line")).toBeNull();
  });

  it("shows a loss, and on the round that wins a game, the game's total", () => {
    renderModal(makeResult({ rating: { rating: 1688, delta: -4 } }), ranked);
    expect(host.querySelector(".result-rating")!.textContent).toBe(" · −4");
    expect(host.querySelector(".result-rating")!.className).toContain("delta-dn");
    act(() => root.unmount());
    host.remove();
    renderModal(makeResult({ point_scored: true, games_won: [1, 0],
                             rating: { rating: 1688, delta: -4, game_delta: 31 } }), ranked);
    expect(host.querySelector(".result-games .result-rating")!.textContent).toBe(" · +31");
  });


  it("tells a guest seat it plays as a guest, from the result's unranked: guest", () => {
    renderModal(makeResult({ unranked: "guest" }), ranked);
    expect(host.querySelector(".rating-guest-note")!.textContent).toBe("Guest");
    expect(host.querySelector(".rating-delta")).toBeNull();
    expect(host.querySelector(".google-signin-slot")).toBeNull();
  });

  it("or from the state's guest at a ranked table", () => {
    renderModal(makeResult(), { ...ranked, guest: true });
    expect(host.querySelector(".rating-guest-note")!.textContent).toBe("Guest");
  });

  it("a signed-out viewer with neither field sees no guest note", async () => {
    await signedOutWithSignIn();
    renderModal(makeResult(), ranked);
    expect(host.querySelector(".rating-guest-note")).toBeNull();
  });

  it("an unranked room shows no rating line and no guest note", async () => {
    await signedOutWithSignIn();
    renderModal(makeResult({ unranked: "guest" }), { ...state, guest: true });
    expect(host.querySelector(".rating-guest-note")).toBeNull();
    renderModal(makeResult({ rating: { rating: 1712, delta: 9 } }));
    expect(host.querySelector(".rating-line")).toBeNull();
    expect(host.querySelector(".result-rating")).toBeNull();
  });

  it("a created room switched to Ranked shows the rating line like a queue room", () => {
    renderModal(makeResult({ rating: { rating: 1712, delta: 9 } }), { ...state, ranked: true });
    expect(host.querySelector(".result-rating")!.textContent).toBe(" · +9");
  });

  it("says nothing about ratings while sign-in is still loading", () => {
    renderModal(makeResult(), ranked);
    expect(host.querySelector(".rating-line")).toBeNull();
  });
});

describe("a minimal top: the title, one result line, the button row", () => {
  it("says the attackers' points, who goes up how far and the next banker in one line", () => {
    renderModal(makeResult({ winner_team: 0, level_change: 1, attacker_points: 35, new_levels: ["3", "2"], next_banker: 2 }), state, 18);
    expect(host.querySelector("h2")!.textContent).toBe("You & Sam win the round");
    const lines = host.querySelectorAll(".modal > p");
    expect(lines.length).toBe(1);
    expect(lines[0].textContent).toBe("Them took 35 of 80. Us go up 1, to 3.Next banker: Sam.");
    const row = host.querySelector(".modal > .round-end-actions")!;
    expect([...row.querySelectorAll("button")].map((b) => b.textContent)).toEqual(["18Next round", "Leave game"]);
    expect(row.querySelector(".timer-ring")).not.toBeNull();
    // the top holds nothing else: no per-team lines, no grid, no ready count
    expect(host.querySelector(".result-team-line")).toBeNull();
    expect(host.querySelector(".result-grid")).toBeNull();
    expect(host.querySelector(".ready-status")).toBeNull();
  });

  it("names the attackers' win and a deal taken with no level change", () => {
    renderModal(makeResult({ winner_team: 1, level_change: 1, attacker_points: 100, next_banker: 1, new_levels: ["2", "4"] }));
    expect(host.querySelector(".result-line")!.textContent).toBe("Them took 100 of 80. Them go up 1, to 4.Next banker: Robin.");
    expect(host.querySelector("h2")!.textContent).toBe("You & Sam lose the round");
    act(() => root.unmount());
    host.remove();
    renderModal(makeResult({ winner_team: 1, level_change: 0, attacker_points: 85, next_banker: 1 }));
    expect(host.querySelector(".result-line")!.textContent).toContain("Them take the deal, no level change.");
    expect(host.textContent).not.toContain("+0");
  });

  it("says when you are the next banker", () => {
    renderModal(makeResult({ next_banker: 0 }));
    expect(host.querySelector(".result-next-banker")!.textContent).toBe("Next banker: you.");
  });

  it("a ranked round's rating change fits on the result line", () => {
    renderModal(makeResult({ new_levels: ["5", "2"], rating: { rating: 1712, delta: 12 } }), ranked);
    expect(host.querySelector(".result-line")!.textContent).toContain("Us go up 3, to 5 · +12.");
    expect(host.querySelector(".result-rating")!.className).toContain("delta-up");
    act(() => root.unmount());
    host.remove();
    renderModal(makeResult({ rating: { rating: 1712, delta: 12 } }));
    expect(host.querySelector(".result-rating")).toBeNull();
  });

  it("drops the ready count; your own Next turns into Waiting for others", () => {
    renderModal(makeResult(), { ...state, ready: [0] });
    expect(host.querySelector(".ready-status")).toBeNull();
    expect(host.textContent).not.toMatch(/\d\/\d ready/);
    const next = host.querySelector<HTMLButtonElement>(".round-end-actions .btn.primary")!;
    expect(next.textContent).toBe("Waiting for others…");
    expect(next.disabled).toBe(true);
  });
});

describe("Details: the kitty and the last trick, closed by default", () => {
  // banker seat 0: Robin (1) and Ada (3) attack
  const lastTrick = {
    leader: 1, winner: 3, points: 10,
    plays: [
      { seat: 1, cards: ["H9"] }, { seat: 2, cards: ["H3"] },
      { seat: 3, cards: ["HA"] }, { seat: 0, cards: ["HK"] },
    ],
  };
  const kitty = ["S5", "C3", "D10", "C4", "C6", "C7", "C8", "D9"];

  it("is a small toggle between the result line and the buttons, closed by default", () => {
    renderModal(makeResult({ kitty_cards: kitty }), { ...state, last_trick: lastTrick });
    const details = host.querySelector<HTMLDetailsElement>(".modal > details.result-details")!;
    expect(details.open).toBe(false);
    expect(details.querySelector("summary")!.textContent).toBe("Details");
    const line = host.querySelector(".result-line")!;
    const row = host.querySelector(".round-end-actions")!;
    expect(line.compareDocumentPosition(details) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(details.compareDocumentPosition(row) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(details.contains(row)).toBe(false);
    expect(host.querySelector(".modal.details-open")).toBeNull();
  });

  it("opened, widens the card and shows the kitty and the last trick side by side", () => {
    renderModal(makeResult({ attacker_points: 115, kitty_points: 30, kitty_cards: kitty, winner_team: 1, level_change: 1, new_levels: ["2", "3"] }),
                { ...state, last_trick: lastTrick });
    const details = host.querySelector<HTMLDetailsElement>("details.result-details")!;
    act(() => {
      details.open = true;
      details.dispatchEvent(new Event("toggle"));
    });
    expect(host.querySelector(".modal.details-open")).not.toBeNull();
    const cols = [...details.querySelectorAll(".round-end-details > .round-end-col")];
    expect(cols.map((c) => c.classList.contains("round-end-kitty"))).toEqual([true, false]);
    const [kittyCol, trickCol] = cols;
    expect(kittyCol.querySelector(".round-end-col-label")!.textContent).toBe("Kitty · 15 points");
    expect(kittyCol.querySelectorAll(".round-end-kitty-cards .card").length).toBe(8);
    expect(kittyCol.querySelector(".kitty-bonus")!.textContent).toBe("Them won the last trick: ×2, +30");
    expect(trickCol.querySelector(".round-end-col-label")!.textContent).toBe("Last trick · Ada, 10 points");
  });

  it("shows the last trick in play order, each card over its player's name, the winner's outlined", () => {
    renderModal(makeResult({ kitty_cards: kitty }), { ...state, last_trick: lastTrick });
    const plays = [...host.querySelectorAll(".round-end-play")];
    expect(plays.map((p) => p.querySelector(".round-end-play-who")!.textContent)).toEqual(["Robin", "Sam", "Ada", "You"]);
    expect(plays.map((p) => p.querySelectorAll(".card").length)).toEqual([1, 1, 1, 1]);
    expect(plays.map((p) => p.classList.contains("winner"))).toEqual([false, false, true, false]);
  });

  it("a pair lead shows both cards of each play; nothing buried still names the multiplier", () => {
    const pairs = { leader: 1, winner: 1, points: 0, plays: [
      { seat: 1, cards: ["S9", "S9"] }, { seat: 2, cards: ["S3", "S4"] },
      { seat: 3, cards: ["S6", "S7"] }, { seat: 0, cards: ["S8", "SJ"] } ] };
    renderModal(makeResult({ kitty_cards: ["S2", "S3", "S4", "S6", "S7", "S8", "S9", "SJ"] }), { ...state, last_trick: pairs });
    expect(host.querySelectorAll(".round-end-play")[0].querySelectorAll(".card").length).toBe(2);
    expect(host.querySelector(".round-end-last-trick > .round-end-col-label")!.textContent).toBe("Last trick · Robin");
    expect(host.querySelector(".kitty-bonus")!.textContent).toBe("Them won the last trick: ×4, +0");
  });

  it("omits the bonus line when the banker's side took the last trick", () => {
    renderModal(makeResult({ kitty_cards: kitty }), { ...state, last_trick: { ...lastTrick, winner: 2 } });
    expect(host.querySelector(".round-end-kitty")).not.toBeNull();
    expect(host.querySelector(".kitty-bonus")).toBeNull();
  });

  it("leaves out the last trick when the state has none, and Details when there is nothing to show", () => {
    renderModal(makeResult({ kitty_cards: kitty }));
    expect(host.querySelector(".round-end-last-trick")).toBeNull();
    expect(host.querySelector(".round-end-kitty")).not.toBeNull();
    act(() => root.unmount());
    host.remove();
    renderModal(makeResult());
    expect(host.querySelector("details")).toBeNull();
  });

  it("a won game keeps the games score on top, with the level restart under it", () => {
    renderModal(makeResult({ point_scored: true, games_won: [1, 0] }));
    expect(host.querySelector(".result-line")).toBeNull();
    const head = host.querySelector(".result-headline")!;
    expect([...head.children].map((c) => c.textContent)).toEqual(["Games: Us 1 · Them 0", "Levels restart at 2."]);
  });
});
