// The watcher's broadcast against a real finished round from the server's
// read path (the same fixture the saved-games contract test reads).
import { describe, expect, it } from "vitest";
import fixture from "../replay/server-round-finished.fixture.json";
import { buildReplay } from "../replay/reducer";
import type { RoundReplayDoc } from "../replay/reducer";
import { compareCards } from "../replay/cards";
import {
  LIFT_MS, PLAY_MS, backTrick, beatMs, beatsOf, forwardTrick, handAt, liftedIds, nextSpeed, tabOrder,
} from "./playback";

const doc = fixture as unknown as RoundReplayDoc;
const buried = doc.events.find((e) => e.e === "bury")!.cards as string[];
const replay = buildReplay(doc);
const beats = beatsOf(replay, buried);

describe("the beats of a finished round", () => {
  it("open with the banker's bury, lift each play before it lands and end at the round end", () => {
    expect(beats[0].kind).toBe("bury");
    expect(beats[1]).toMatchObject({ kind: "buryLift", liftSeat: replay.setup.banker, lift: buried });
    expect(beats[2].kind).toBe("start");
    const plays = doc.events.filter((e) => e.e === "play");
    expect(beats.filter((b) => b.kind === "play")).toHaveLength(plays.length);
    beats.forEach((b, i) => {
      if (b.kind === "play") expect(beats[i - 1].kind).toBe("lift");
    });
    expect(beats[beats.length - 1].kind).toBe("end");
    expect(beats.filter((b) => b.kind === "end")).toHaveLength(1);
  });

  it("keep a steady rhythm that the speed scales", () => {
    const lift = beats.find((b) => b.kind === "lift")!;
    const frame = replay.frames[lift.frame];
    expect(beatMs(lift, frame, 1)).toBe(LIFT_MS);
    expect(beatMs(lift, frame, 2)).toBe(LIFT_MS / 2);
    expect(beatMs(lift, frame, 0.5)).toBe(LIFT_MS * 2);
    const play = beats.find((b) => b.kind === "play" && replay.frames[b.frame].winner === null)!;
    expect(beatMs(play, replay.frames[play.frame], 1)).toBe(PLAY_MS);
    expect([nextSpeed(0.5), nextSpeed(1), nextSpeed(2)]).toEqual([1, 2, 0.5]);
  });
});

describe("the hands", () => {
  const banker = replay.setup.banker!;
  it("show the banker the dealt hand with the kitty during the bury, in the game's order", () => {
    const hand = handAt(replay, beats[1], banker);
    expect(hand).toHaveLength(33);
    const codes = hand.map((c) => c.code);
    const sorted = [...codes].sort((a, b) => compareCards(a, b, replay.setup.trumpSuit, replay.setup.trumpRank));
    expect(codes).toEqual(sorted);
    const up = liftedIds(hand, beats[1], banker);
    expect(up.size).toBe(8);
    expect(hand.filter((c) => up.has(c.id)).map((c) => c.code).sort()).toEqual([...buried].sort());
    expect(handAt(replay, beats[2], banker)).toHaveLength(25);
  });

  it("lift the cards about to be played only in that player's own hand", () => {
    const lift = beats.find((b) => b.kind === "lift")!;
    const seat = lift.liftSeat!;
    const hand = handAt(replay, lift, seat);
    expect(liftedIds(hand, lift, seat).size).toBe(lift.lift.length);
    expect(liftedIds(handAt(replay, lift, (seat + 1) % 4), lift, (seat + 1) % 4).size).toBe(0);
  });

  it("every seat's hand is known in a finished round, so any tab can be selected", () => {
    const mid = beats[Math.floor(beats.length / 2)];
    for (const s of [0, 1, 2, 3]) expect(handAt(replay, mid, s).length).toBeGreaterThan(0);
  });

  it("tabs keep table order from the seat the watcher landed behind", () => {
    expect(tabOrder(2)).toEqual([2, 3, 0, 1]);
  });
});

describe("back and forward step whole tricks and stop at the round end", () => {
  const firstOf = (n: number) => beats.findIndex((b) => b.trickNo === n);
  it("forward goes to the next trick's first beat, and never past the end", () => {
    expect(forwardTrick(beats, 0)).toBe(firstOf(1));
    expect(forwardTrick(beats, firstOf(1))).toBe(firstOf(2));
    const end = beats.length - 1;
    expect(forwardTrick(beats, end)).toBe(end);
    expect(forwardTrick(beats, firstOf(replay.trickCount))).toBe(end);
  });
  it("back goes to the start of the trick in view, then to the one before", () => {
    expect(backTrick(beats, firstOf(3) + 3)).toBe(firstOf(3));
    expect(backTrick(beats, firstOf(3))).toBe(firstOf(2));
    expect(backTrick(beats, firstOf(1))).toBe(0);
    expect(backTrick(beats, 0)).toBe(0);
  });
});
