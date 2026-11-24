import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { GameState, RoundResult, StatePlayer } from "../protocol";
import RoundEndModal from "./RoundEndModal";
import { auth } from "../auth";
import { guestName } from "../guestName";
import { IdentitySheet } from "./GuestChip";

const sent: unknown[] = [];
vi.mock("../ws", () => ({ conn: { send: (m: unknown) => { sent.push(m); return true; } } }));

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

/** We bank at A: holding them under 80 wins a game. */
const aceDefence: GameState = { ...state, trump: { suit: "S", rank: "A", declarer: null } };

/** A team's lane: the outlined old level and the filled new one. */
function lane(team: 0 | 1): { was: string | null; now: string | null } {
  const el = host.querySelector(`.rank-lane.team${team}`)!;
  return { was: el.querySelector(".lane-cell.was")?.textContent ?? null, now: el.querySelector(".lane-cell.now")?.textContent ?? null };
}

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
function renderModal(result: RoundResult, shown: GameState = state, clock: number | null = null,
                     extra: { before?: [string, string] | null; live?: boolean } = {}): string {
  sent.length = 0;
  // one round end at a time: an earlier one still mounted would stay an open dialog
  if (host?.isConnected) {
    act(() => root.unmount());
    host.remove();
  }
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  act(() => { root.render(<RoundEndModal state={shown} result={result} clock={clock} {...extra} />); });
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
  it("shows a level change on an ordinary round as the lanes, not a sentence", () => {
    const text = renderModal(makeResult({ new_levels: ["5", "2"] }));
    expect(lane(0)).toEqual({ was: "2", now: "5" });
    expect(text).not.toContain("go up");
    expect(text).not.toContain("win the game");
  });

  it("says a GAME was won, not '+levels', when a team holds Ace, and never that the levels restart", () => {
    // The bug this guards: the levels reset to 2 while the modal still
    // announced "+3 levels", which reads as the game losing your progress.
    const text = renderModal(makeResult({ point_scored: true, games_won: [1, 0] }), aceDefence, null, { before: ["A", "Q"] });
    expect(text).toContain("win the game");
    expect(text).not.toMatch(/restart/i);
    expect(text).not.toContain("go up");
    // the winners' lane ends past A on the crown; the other lane keeps Q
    expect(lane(0)).toEqual({ was: "A", now: "👑" });
    expect(lane(1)).toEqual({ was: null, now: "Q" });
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
    expect(games.textContent).toBe("Games: Us 1 · Them 0");
    const buttons = [...host.querySelectorAll("button")].map((b) => b.textContent);
    expect(buttons).toContain("Next game");
    expect(buttons).not.toContain("Next round");
    expect(buttons).toContain("Leave game");
    expect(buttons).not.toContain("Back to lobby");
    const next = [...host.querySelectorAll("button")].find((b) => b.textContent === "Next game")!;
    act(() => next.click());
    expect(sent).toEqual([{ type: "next_round" }]);
  });

  it("Next round goes once per state: taps while it is on its way send nothing; the next state frees it", () => {
    const result = makeResult();
    renderModal(result);
    const next = () => [...host.querySelectorAll("button")].find((b) => b.textContent === "Next round")!;
    act(() => next().click());
    act(() => next().click());
    act(() => next().click());
    expect(sent).toEqual([{ type: "next_round" }]);
    expect(next().disabled).toBe(true);
    // a new state (a resumed link's, the seat not yet ready): it may go again
    act(() => { root.render(<RoundEndModal state={{ ...state }} result={result} clock={null} />); });
    expect(next().disabled).toBe(false);
    act(() => next().click());
    expect(sent).toHaveLength(2);
  });

  it("the games score puts your team first, and a loss names your side", () => {
    renderModal(makeResult({ point_scored: true, games_won: [2, 3], winner_team: 1 }),
                { ...state, you: 1 });
    expect(host.querySelector("h2")!.textContent).toBe("You & Ada win the game");
    expect(host.querySelector(".result-games")!.textContent).toBe("Games: Us 3 · Them 2");
    renderModal(makeResult({ point_scored: true, games_won: [0, 1], winner_team: 1 }));
    expect(host.querySelector("h2")!.textContent).toBe("You & Sam lose the game");
    expect(host.querySelector(".result-games")!.textContent).toBe("Games: Us 0 · Them 1");
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
      expect(sheetText()).toBe("Leave the game? / This round's result is kept.");
      expect([...sheet()!.querySelectorAll("button")].map((b) => b.textContent)).toEqual(["Stay", "Leave"]);
      act(() => { sheet()!.querySelector<HTMLButtonElement>(".leave-sheet-leave")!.click(); });
      expect(sent).toEqual([{ type: "table_leave" }]);
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
    expect(bit.textContent).toBe(" · rating 1712 (+9)");
    expect(bit.className).toContain("delta-up");
    expect(host.querySelector(".rating-unranked")).toBeNull();
  });

  it("shows a loss, and on the round that wins a game, the game's total", () => {
    renderModal(makeResult({ rating: { rating: 1688, delta: -4 } }), ranked);
    expect(host.querySelector(".result-rating")!.textContent).toBe(" · rating 1688 (−4)");
    expect(host.querySelector(".result-rating")!.className).toContain("delta-dn");
    act(() => root.unmount());
    host.remove();
    renderModal(makeResult({ point_scored: true, games_won: [1, 0],
                             rating: { rating: 1688, delta: -4, game_delta: 31 } }), ranked);
    expect(host.querySelector(".result-line .result-rating")!.textContent).toBe(" · rating 1688 (+31)");
  });


  it("a guest seat at a ranked table reads 'Sign in to be ranked', from the result's unranked: guest or the state's guest", () => {
    renderModal(makeResult({ unranked: "guest" }), ranked);
    expect(host.querySelector(".rating-unranked")!.textContent).toBe("Sign in to be ranked");
    expect(host.textContent).not.toContain("Guest");
    expect(host.querySelector(".google-signin-slot")).toBeNull();
    act(() => root.unmount());
    host.remove();
    renderModal(makeResult(), { ...ranked, guest: true });
    expect(host.querySelector(".rating-unranked")!.textContent).toBe("Sign in to be ranked");
    expect(host.textContent).not.toContain("Guest");
  });

  it("an unranked room shows no rating note", async () => {
    await signedOutWithSignIn();
    renderModal(makeResult({ unranked: "joined" }), { ...state, guest: true });
    expect(host.querySelector(".rating-unranked")).toBeNull();
    renderModal(makeResult({ rating: { rating: 1712, delta: 9 } }));
    expect(host.querySelector(".rating-unranked")).toBeNull();
    expect(host.querySelector(".result-rating")).toBeNull();
  });

  it("says nothing about ratings while sign-in is still loading", () => {
    renderModal(makeResult(), ranked);
    expect(host.querySelector(".rating-unranked")).toBeNull();
  });

  async function signedInAccount() {
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/auth/config") return { status: 200, json: async () => ({ google_client_id: "cid" }) } as Response;
      if (url === "/api/me") {
        return { status: 200, json: async () => ({ name: "Ada", email: "a@x", picture: null, display_name: null, name_shown: "Ada" }) } as Response;
      }
      return { status: 404, json: async () => ({}) } as Response;
    }) as typeof fetch;
    await auth.init();
  }

  it("a guest's line at a ranked table is a button that opens the identity sheet", async () => {
    await signedOutWithSignIn();
    const open = vi.spyOn(guestName, "open").mockImplementation(() => {});
    try {
      for (const [result, shown] of [[makeResult(), { ...ranked, guest: true }],
                                      [makeResult({ unranked: "guest" }), ranked]] as const) {
        renderModal(result, shown);
        const line = host.querySelector(".rating-unranked")!;
        expect(line.textContent).toBe("Sign in to be ranked");
        const button = line.querySelector<HTMLButtonElement>("button.rating-signin")!;
        expect(button.type).toBe("button");
        expect(button.textContent).toBe("Sign in to be ranked");
        open.mockClear();
        act(() => button.click());
        expect(open).toHaveBeenCalledTimes(1);
        expect(sent).toEqual([]);
        act(() => root.unmount());
        host.remove();
      }
      renderModal(makeResult(), state);
    } finally {
      open.mockRestore();
    }
  });

  it("joined mid-round and an unranked room keep their lines, with nothing to tap", async () => {
    await signedOutWithSignIn();
    renderModal(makeResult({ unranked: "joined" }), { ...ranked, guest: true });
    expect(host.querySelector(".rating-unranked")!.textContent).toBe("Unranked · joined mid-round");
    expect(host.querySelector(".rating-signin")).toBeNull();
    act(() => root.unmount());
    host.remove();
    renderModal(makeResult({ unranked: "guest" }), { ...state, guest: true });
    expect(host.querySelector(".rating-unranked")).toBeNull();
    expect(host.querySelector(".rating-signin")).toBeNull();
  });

  it("an account sees no sign-in line, even on the round it signed in during", async () => {
    await signedInAccount();
    expect(auth.state.status).toBe("in");
    renderModal(makeResult({ unranked: "guest" }), ranked);
    expect(host.querySelector(".rating-unranked")).toBeNull();
    expect(host.textContent).not.toContain("Sign in");
  });

  it("the identity sheet opened over the round end is drawn inside its dialog, and outside once it closes", async () => {
    await signedOutWithSignIn();
    renderModal(makeResult(), { ...ranked, guest: true });
    const app = document.createElement("div");
    document.body.appendChild(app);
    const appRoot = createRoot(app);
    act(() => appRoot.render(<IdentitySheet />));
    try {
      act(() => host.querySelector<HTMLButtonElement>(".rating-signin")!.click());
      const dialog = host.querySelector("dialog")!;
      const sheet = document.querySelector(".identity-sheet")!;
      expect(sheet).not.toBeNull();
      expect(sheet.closest("dialog")).toBe(dialog);
      expect(app.querySelector(".identity-sheet")).toBeNull();
      act(() => root.unmount());
      host.remove();
      const after = document.querySelector(".identity-sheet")!;
      expect(after).not.toBeNull();
      expect(after.closest("dialog")).toBeNull();
      expect(app.contains(after)).toBe(true);
      root = createRoot(host = document.createElement("div"));
      document.body.appendChild(host);
    } finally {
      act(() => guestName.close());
      act(() => appRoot.unmount());
      app.remove();
    }
  });
});

describe("a minimal top: the title, one result line, the button row", () => {
  it("says the attackers' points, who goes up how far and the next banker in one line", () => {
    renderModal(makeResult({ winner_team: 0, level_change: 1, attacker_points: 35, new_levels: ["3", "2"], next_banker: 2 }), state, 18);
    expect(host.querySelector("h2")!.textContent).toBe("You & Sam win the round");
    const lines = host.querySelectorAll(".modal > p");
    expect(lines.length).toBe(1);
    expect(lines[0].textContent).toBe("Next banker: Sam.");
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
    expect(host.querySelector(".result-line")!.textContent).toBe("Next banker: Robin.");
    expect(host.querySelector("h2")!.textContent).toBe("You & Sam lose the round");
    expect(lane(1)).toEqual({ was: "3", now: "4" });
    expect(lane(0)).toEqual({ was: null, now: "2" });
    act(() => root.unmount());
    host.remove();
    renderModal(makeResult({ winner_team: 1, level_change: 0, attacker_points: 85, next_banker: 1 }));
    expect(lane(1)).toEqual({ was: null, now: "2" });
    expect(host.textContent).not.toContain("take the deal");
    expect(host.textContent).not.toContain("+0");
  });

  it("says when you are the next banker", () => {
    renderModal(makeResult({ next_banker: 0 }));
    expect(host.querySelector(".result-next-banker")!.textContent).toBe("Next banker: you.");
  });

  it("a ranked round's rating change fits on the result line", () => {
    renderModal(makeResult({ new_levels: ["5", "2"], rating: { rating: 1712, delta: 12 } }), ranked);
    expect(host.querySelector(".result-line")!.textContent).toBe("Next banker: Sam · rating 1712 (+12).");
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
    expect(kittyCol.querySelector(".kitty-bonus")!.textContent).toBe("They won the last trick: ×2, +30");
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
    expect(host.querySelector(".kitty-bonus")!.textContent).toBe("They won the last trick: ×4, +0");
  });

  it("speaks in the first person when your side attacked: We took …, They go up …, We won the last trick", () => {
    renderModal(makeResult({ winner_team: 1, level_change: 2, attacker_points: 40, kitty_points: 10, new_levels: ["2", "4"], next_banker: 3,
                             kitty_cards: ["S5", "C3", "C4", "C6", "C7", "C8", "C9", "CJ"] }),
                { ...state, banker: 1, last_trick: { ...lastTrick, winner: 2 } });
    expect(host.querySelector(".result-line")!.textContent).toBe("Next banker: Ada.");
    // the bar is ours: we attacked
    expect(host.querySelector(".points-bar")!.className).toContain("team0");
    expect(host.querySelector(".kitty-bonus")!.textContent).toBe("We won the last trick: ×2, +10");
    // labels keep Us / Them
    expect(host.textContent).not.toMatch(/\b(Us|Them) (took|go|take|won)\b/);
  });

  it("a 5-card throw keeps all four plays in one row, five cards each, the winner's group outlined", () => {
    const throwTrick = { leader: 1, winner: 0, points: 35, plays: [
      { seat: 1, cards: ["SQ", "SQ", "SJ", "SJ", "SA"] }, { seat: 2, cards: ["S3", "S4", "S5", "S8", "S10"] },
      { seat: 3, cards: ["S6", "S7", "S9", "SK", "HK"] }, { seat: 0, cards: ["C2", "C2", "S2", "S2", "H2"] } ] };
    renderModal(makeResult({ kitty_cards: kitty }), { ...state, last_trick: throwTrick });
    const row = host.querySelector(".round-end-plays")!;
    const plays = [...row.querySelectorAll(":scope > .round-end-play")];
    expect(plays.length).toBe(4);
    expect(plays.map((p) => p.querySelectorAll(".round-end-play-cards > .card").length)).toEqual([5, 5, 5, 5]);
    expect(plays.map((p) => p.classList.contains("winner"))).toEqual([false, false, false, true]);
    expect(host.querySelector(".round-end-last-trick > .round-end-col-label")!.textContent).toBe("Last trick · You, 35 points");
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

  it("a won game is the round-end card: one result line, then the games score as a label, then Details", () => {
    renderModal(makeResult({ point_scored: true, games_won: [1, 0], attacker_points: 35, kitty_cards: kitty }));
    const card = host.querySelector(".modal.round-end")!;
    const order = [...card.children].map((c) => c.className.split(" ")[0] || c.tagName);
    expect(order).toEqual(["game-won-crown", "modal-title", "round-end-ladder", "result-headline", "result-games",
                           "result-details", "round-end-actions"]);
    expect(host.querySelectorAll(".result-headline")).toHaveLength(1);
    expect(host.querySelector(".result-line")!.textContent).toBe("Next banker: Sam.");
    expect(host.querySelector(".result-games")!.textContent).toBe("Games: Us 1 · Them 0");
  });

  it("Next game and Leave game share one row; on a timed table Next game carries the same ring as Next round", () => {
    renderModal(makeResult({ point_scored: true, games_won: [1, 0] }), ranked, 20);
    const row = host.querySelector(".round-end-actions")!;
    expect([...row.querySelectorAll("button")].map((b) => b.textContent?.replace(/^\d+/, "")))
      .toEqual(["Next game", "Leave game"]);
    const gameRing = row.querySelector(".btn.primary .timer-ring")?.outerHTML;
    expect(gameRing).toBeDefined();
    act(() => root.unmount());
    host.remove();
    renderModal(makeResult(), ranked, 20);
    expect(host.querySelector(".round-end-actions .btn.primary .timer-ring")?.outerHTML).toBe(gameRing);
  });
});

describe("the ladder: a rank lane per team and the attackers' points", () => {
  it("draws both lanes 2 to A, labelled Us / Them, each in its team's colour, old outlined and new filled", () => {
    // we defend at J and hold them to 40: we go up one, to Q; they stay at 9
    renderModal(makeResult({ winner_team: 0, level_change: 1, attacker_points: 40, new_levels: ["Q", "9"] }),
                { ...state, trump: { suit: "H", rank: "J", declarer: 0 } }, null, { before: ["J", "9"] });
    const lanes = [...host.querySelectorAll(".rank-lane")];
    expect(lanes.map((l) => l.className)).toEqual(["rank-lane team0", "rank-lane team1"]);
    expect(lanes.map((l) => l.querySelector(".lane-label")!.textContent)).toEqual(["Us", "Them"]);
    for (const l of lanes) {
      expect([...l.querySelectorAll(".lane-cell")].map((c) => c.textContent))
        .toEqual(["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]);
    }
    expect(lane(0)).toEqual({ was: "J", now: "Q" });
    expect(lane(1)).toEqual({ was: null, now: "9" });
    expect(lanes.map((l) => l.getAttribute("aria-label"))).toEqual(["Us: J to Q", "Them: 9"]);
  });

  it("the attackers' lane climbs when they cross 80, read from the result alone after a reconnect", () => {
    // they attack at K and take 125: they go up one, to A; we bank at 5
    renderModal(makeResult({ winner_team: 1, level_change: 1, attacker_points: 125, new_levels: ["5", "A"], next_banker: 1 }),
                { ...state, trump: { suit: "H", rank: "5", declarer: 0 } });
    expect(lane(0)).toEqual({ was: null, now: "5" });
    // A reached by the climb hides where they started; the lane still shows A
    expect(lane(1)).toEqual({ was: null, now: "A" });
    renderModal(makeResult({ winner_team: 1, level_change: 1, attacker_points: 125, new_levels: ["5", "A"], next_banker: 1 }),
                { ...state, trump: { suit: "H", rank: "5", declarer: 0 } }, null, { before: ["5", "K"] });
    expect(lane(1)).toEqual({ was: "K", now: "A" });
  });

  it("ignores a remembered level that disagrees with the result (a round missed while away)", () => {
    renderModal(makeResult({ winner_team: 0, level_change: 1, new_levels: ["4", "2"] }),
                { ...state, trump: { suit: "H", rank: "3", declarer: 0 } }, null, { before: ["7", "2"] });
    expect(lane(0)).toEqual({ was: "3", now: "4" });
  });

  it("puts the attackers' points on a bar with the 80 mark, in the attackers' colour", () => {
    renderModal(makeResult({ attacker_points: 40 }));
    const bar = host.querySelector(".points-bar")!;
    expect(bar.className).toBe("points-bar team1");
    expect(bar.querySelector(".points-bar-n")!.textContent).toBe("40");
    expect(bar.querySelector(".points-bar-80")!.textContent).toBe("80");
    expect(bar.querySelector(".points-bar-mark")).not.toBeNull();
    expect(bar.querySelector<HTMLElement>(".points-bar-fill")!.style.transform).toBe("scaleX(0.25)");
    expect(bar.getAttribute("aria-label")).toBe("Attackers' points: 40 of 80");
    // past 80 the bar runs past the mark, and stops at the track's end
    renderModal(makeResult({ attacker_points: 125, winner_team: 1 }));
    expect(host.querySelector<HTMLElement>(".points-bar-fill")!.style.transform).toBe("scaleX(0.78125)");
    renderModal(makeResult({ attacker_points: 205, winner_team: 1 }));
    expect(host.querySelector<HTMLElement>(".points-bar-fill")!.style.transform).toBe("scaleX(1)");
    expect(host.querySelector(".points-bar-n")!.textContent).toBe("205");
  });

  it("shows no result sentence: no points sentence, no climb, no deal taken", () => {
    for (const r of [makeResult({ attacker_points: 35, level_change: 1, new_levels: ["3", "2"] }),
                     makeResult({ attacker_points: 100, winner_team: 1, level_change: 1, new_levels: ["2", "3"] }),
                     makeResult({ attacker_points: 85, winner_team: 1, level_change: 0 })]) {
      const text = renderModal(r);
      expect(text).not.toMatch(/took \d+ of 80|go up|take the deal|no level change/);
      expect(host.querySelectorAll(".modal > p")).toHaveLength(1);
    }
  });

  it("a won game: the crown at the lane's end, Next game, no restart line, and the tally up by one game", () => {
    const before: GameState = { ...aceDefence, games_won: [0, 0] };
    renderModal(makeResult({ point_scored: true, attacker_points: 35, games_won: [1, 0], new_levels: ["2", "2"] }),
                before, null, { before: ["A", "Q"] });
    const crown = host.querySelector(".rank-lane.team0 .lane-crown")!;
    expect(crown.textContent).toBe("👑");
    expect(crown.classList.contains("now")).toBe(true);
    // the other lane keeps its column, empty, so the two lanes stay aligned
    expect(host.querySelector(".rank-lane.team1 .lane-crown")!.textContent).toBe("");
    expect(host.querySelector(".rank-lane.team0")!.getAttribute("aria-label")).toBe("Us: A, game won");
    expect([...host.querySelectorAll(".round-end-actions button")].map((b) => b.textContent)).toContain("Next game");
    expect(host.textContent).not.toMatch(/restart|Levels/i);
    // the tally counts games, one more than before the round, and no level
    const games = host.querySelector(".result-games")!.textContent!;
    expect(games).toBe(`Games: Us ${before.games_won[0] + 1} · Them ${before.games_won[1]}`);
    expect(games).not.toMatch(/level|\bA\b|\b2\b/);
  });

  it("fills the new level in only when the result arrives at an open table", () => {
    renderModal(makeResult({ new_levels: ["3", "2"], level_change: 1 }), state, null, { live: true });
    expect(host.querySelector(".rank-lane.team0 .lane-cell.now")!.classList.contains("fill")).toBe(true);
    renderModal(makeResult({ new_levels: ["3", "2"], level_change: 1 }), state, null, { live: false });
    expect(host.querySelector(".lane-cell.fill")).toBeNull();
  });
});
