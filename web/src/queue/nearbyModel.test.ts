// The nearby lobby's Bots row: the host's select, the value read-only for a
// joiner, from the room frame's bot_level (Standard when it has none).
import { describe, expect, it } from "vitest";
import type { RoomMsg } from "../protocol";
import { nearbyRoomModel } from "./nearbyModel";

const room = (you: number, extra: Partial<RoomMsg> = {}): RoomMsg => ({
  type: "room", room: "ABCD", you, host: 0, start_level: "2",
  players: [{ seat: 0, name: "Host", is_bot: false, connected: true }, { seat: 1, name: "Mei", is_bot: false, connected: true }],
  nearby: { ready: [], bots_in: null, locked: true }, ...extra,
} as RoomMsg);

describe("the nearby lobby's Bots row", () => {
  it("is the host's to pick", () => {
    const m = nearbyRoomModel(room(0, { bot_level: "advanced" }), { now: 0, botsAt: null });
    expect(m.rows?.bots).toBe("advanced");
    expect(m.rows?.opener).toBe(true);
  });

  it("is read-only for a joiner", () => {
    const m = nearbyRoomModel(room(1, { bot_level: "advanced" }), { now: 0, botsAt: null });
    expect(m.rows?.bots).toBe("advanced");
    expect(m.rows?.opener).toBe(false);
  });

  it("reads Standard from a frame that has no level", () => {
    expect(nearbyRoomModel(room(1), { now: 0, botsAt: null }).rows?.bots).toBe("standard");
  });
});
