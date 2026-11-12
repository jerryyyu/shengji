// Which moves add a history entry. The browser's back button and the iOS
// app's edge swipe walk exactly these entries, so a sub-page (How to play, a
// saved game, a replay, Privacy, Support) is one, while switching tabs
// replaces the current entry the way a native tab bar keeps no back stack.
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { openTab, parseHome } from "./home/route";
import { openHowto } from "./howto/route";
import { navigate } from "./replay/route";
import { openInfoPage } from "./support/route";

let hashChanges = 0;
const onHash = () => { hashChanges++; };

beforeEach(() => {
  window.history.replaceState(null, "", "/");
  hashChanges = 0;
  window.addEventListener("hashchange", onHash);
});
afterEach(() => window.removeEventListener("hashchange", onHash));

/** History entries added by `move`. */
function added(move: () => void): number {
  const before = window.history.length;
  move();
  return window.history.length - before;
}

describe("history entries", () => {
  it("switching tabs replaces the entry and still announces the route", () => {
    expect(added(() => openTab("leaderboard"))).toBe(0);
    expect(parseHome(window.location.hash)).toEqual({ tab: "leaderboard" });
    expect(added(() => openTab("me", "games"))).toBe(0);
    expect(window.location.hash).toBe("#/me/games");
    expect(added(() => openTab("me", "stats"))).toBe(0);
    expect(window.location.hash).toBe("#/me");
    expect(added(() => openTab("play"))).toBe(0);
    expect(window.location.pathname + window.location.hash).toBe("/");
    expect(hashChanges).toBe(4);
  });

  it("the tab already showing is not announced again", () => {
    openTab("leaderboard");
    hashChanges = 0;
    expect(added(() => openTab("leaderboard"))).toBe(0);
    expect(hashChanges).toBe(0);
  });

  it("How to play is an entry, and so is each step", () => {
    expect(added(() => openHowto())).toBe(1);
    expect(window.location.hash).toBe("#/howto");
    expect(added(() => openHowto(2))).toBe(1);
  });

  it("a saved game and its replay are entries", () => {
    openTab("me", "games");
    expect(added(() => navigate({ page: "game", id: "g1" }))).toBe(1);
    expect(added(() => navigate({ page: "replay", id: "g1", round: 2 }))).toBe(1);
    expect(window.location.hash).toBe("#/games/g1/rounds/2");
  });

  it("Privacy and Support are entries", () => {
    expect(added(() => openInfoPage("privacy"))).toBe(1);
    expect(window.location.pathname).toBe("/privacy");
    expect(added(() => openInfoPage("support"))).toBe(1);
    expect(window.location.pathname).toBe("/support");
  });
});
