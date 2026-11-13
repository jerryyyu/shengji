import { afterEach, describe, expect, it, vi } from "vitest";
import type { HandCard, Trump } from "./protocol";
import {
  COACH_KEY, COACH_PLAYS, PLAYS_KEY, coachFor, coachSetting, coachShows, forgetSessionCoach, isNewcomer, playsMade,
  recordPlay, setCoachSetting, subscribeCoach,
} from "./firstTurns";

const hand = (codes: string[]): HandCard[] => codes.map((code, i) => ({ id: i + 1, code }));
const hearts2: Trump = { suit: "H", rank: "2", declarer: 3 };

afterEach(() => {
  localStorage.clear();
  forgetSessionCoach();
  vi.restoreAllMocks();
});

describe("who is a newcomer", () => {
  it("counts plays up to the coach's limit and then stops", () => {
    expect(playsMade()).toBe(0);
    expect(isNewcomer(playsMade())).toBe(true);
    for (let i = 0; i < COACH_PLAYS + 2; i++) recordPlay();
    expect(playsMade()).toBe(COACH_PLAYS);
    expect(isNewcomer(playsMade())).toBe(false);
  });

  it("treats a store that cannot be read as done, so nobody is coached forever", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("blocked"); });
    expect(isNewcomer(playsMade())).toBe(false);
  });

  it("reads a garbled count as a newcomer", () => {
    localStorage.setItem(PLAYS_KEY, "nope");
    expect(playsMade()).toBe(0);
  });
});

describe("the coach switch", () => {
  it("left alone, coaches the first plays and then stops", () => {
    expect(coachSetting()).toBe("auto");
    expect(coachShows("auto", 0)).toBe(true);
    expect(coachShows("auto", COACH_PLAYS - 1)).toBe(true);
    expect(coachShows("auto", COACH_PLAYS)).toBe(false);
  });

  it("on coaches every turn and off none, whatever the count", () => {
    expect(coachShows("on", COACH_PLAYS + 10)).toBe(true);
    expect(coachShows("off", 0)).toBe(false);
  });

  it("is kept in storage and tells its listeners", () => {
    const heard: string[] = [];
    const stop = subscribeCoach((s) => heard.push(s));
    setCoachSetting("off");
    expect(localStorage.getItem(COACH_KEY)).toBe("off");
    expect(coachSetting()).toBe("off");
    setCoachSetting("on");
    expect(coachSetting()).toBe("on");
    stop();
    setCoachSetting("off");
    expect(heard).toEqual(["off", "on"]);
  });

  it("reads anything else in storage as auto", () => {
    localStorage.setItem(COACH_KEY, "maybe");
    expect(coachSetting()).toBe("auto");
  });

  it("holds the switch in memory for the session when storage refuses", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("full"); });
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("blocked"); });
    setCoachSetting("on");
    expect(coachSetting()).toBe("on");
    setCoachSetting("off");
    expect(coachSetting()).toBe("off");
  });

  it("reads as auto when storage cannot be read and nothing was set", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("blocked"); });
    expect(coachSetting()).toBe("auto");
  });
});

describe("what the coach says", () => {
  // AUP6: hearts trump at 2, Bot 3 led a club pair; the guest held two clubs
  const aup6 = hand(["S3", "S4", "D3", "C6", "CK", "H4", "H9", "HA"]);

  it("asks a leader for any card", () => {
    expect(coachFor(aup6, null, hearts2)).toEqual({ text: "Your lead: tap a card, then Play", follow: null });
  });

  it("lights exactly the led suit when it can make the whole play", () => {
    const c = coachFor(aup6, ["C9", "C9"], hearts2);
    expect(c.text).toBe("Your turn: tap 2 ♣ cards (lit up), then Play");
    expect([...c.follow!]).toEqual([4, 5]);
  });

  it("counts trump by its effective suit: a trump-rank card leads trump", () => {
    // H642: clubs trump at 2, Bot 1 led S2; the club ace follows it
    const c = coachFor(hand(["SA", "CA", "D4"]), ["S2"], { suit: "C", rank: "2", declarer: 1 });
    expect(c.text).toBe("Your turn: tap 1 trump card (lit up), then Play");
    expect([...c.follow!]).toEqual([2]);
  });

  it("in no-trump, a led 2 is followed by 2s and jokers", () => {
    // HGL6: no trump at 2, Bot 2 led D2
    const c = coachFor(hand(["C2", "CA", "LJ", "H5"]), ["D2"], { suit: "NT", rank: "2", declarer: 2 });
    expect([...c.follow!]).toEqual([1, 3]);
  });

  it("lights nothing when the suit runs short, and says how many more", () => {
    const c = coachFor(hand(["C6", "S3", "D4"]), ["C9", "C9"], hearts2);
    expect(c).toEqual({ text: "Your turn: tap your 1 ♣ and 1 card more, then Play", follow: null });
  });

  it("frees every card when the suit is gone", () => {
    const c = coachFor(hand(["S3", "D4", "D5"]), ["C9", "C9"], hearts2);
    expect(c).toEqual({ text: "No ♣ left: tap any 2 cards, then Play", follow: null });
  });

  it("falls back to the count when trump is unknown", () => {
    expect(coachFor(aup6, ["C9"], null)).toEqual({ text: "Your turn: tap 1 card, then Play", follow: null });
  });
});
