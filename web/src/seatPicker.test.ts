import { describe, expect, it } from "vitest";
import type { RoomSeats } from "./protocol";
import { needsSeatPicker } from "./seatPicker";

type Seat = RoomSeats["seats"][number];

function seat(i: number, over: Partial<Seat> = {}): Seat {
  return {
    seat: i, name: `p${i}`, is_bot: false, connected: true, team: i % 2,
    claimable: false, controller: "human", reserved_secs: null, ...over,
  };
}

const bot = (i: number): Seat =>
  seat(i, { is_bot: true, claimable: true, controller: "bot" });
const dropped = (i: number): Seat =>
  seat(i, { is_bot: true, claimable: true, connected: false, controller: "bot_cover" });
const droppedNoCover = (i: number): Seat =>
  seat(i, { claimable: true, connected: false });

describe("needsSeatPicker", () => {
  it("joins straight through when exactly one bot seat is open", () => {
    expect(needsSeatPicker([seat(0), seat(1), seat(2), bot(3)])).toBe(false);
  });

  it("joins straight through when no seat is open", () => {
    expect(needsSeatPicker([seat(0), seat(1), seat(2)])).toBe(false);
  });

  it("offers the picker when more than one seat is open", () => {
    expect(needsSeatPicker([seat(0), bot(1), seat(2), bot(3)])).toBe(true);
    expect(needsSeatPicker([seat(0), bot(1), seat(2), dropped(3)])).toBe(true);
  });

  it("offers the picker when the only open seat is a dropped human in a full lobby", () => {
    expect(needsSeatPicker([seat(0), seat(1), seat(2), droppedNoCover(3)])).toBe(true);
  });
});
