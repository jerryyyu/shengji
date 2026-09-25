import { describe, expect, it } from "vitest";
import { RANKS } from "./protocol";
import { createRoomPayload } from "./testPolicy";

describe("W32 create-room opt-in payload", () => {
  it("preserves the ordinary create payload exactly", () => {
    expect(createRoomPayload("Jerry", false, "ignored")).toEqual({
      type: "create_room",
      name: "Jerry",
    });
  });

  it("includes only the constrained W32 fields when enabled", () => {
    expect(createRoomPayload("Jerry", true, "secret")).toEqual({
      type: "create_room",
      name: "Jerry",
      test_policy: "w32",
      test_access_key: "secret",
    });
  });

  it("refuses an enabled payload without a nonempty key", () => {
    expect(createRoomPayload("Jerry", true, "  ")).toBeNull();
  });
});

describe("starting level opt-in payload", () => {
  it("omits start_level at the default, keeping the historical bytes", () => {
    expect(createRoomPayload("Jerry", false, "", "2")).toEqual({
      type: "create_room",
      name: "Jerry",
    });
    expect(
      Object.keys(createRoomPayload("Jerry", false, "", "2")!),
    ).not.toContain("start_level");
  });

  it("defaults to level 2 when the argument is omitted entirely", () => {
    expect(createRoomPayload("Jerry", false, "")).toEqual({
      type: "create_room",
      name: "Jerry",
    });
  });

  it("sends a non-default level", () => {
    expect(createRoomPayload("Jerry", false, "", "10")).toEqual({
      type: "create_room",
      name: "Jerry",
      start_level: "10",
    });
  });

  it("carries the level alongside the W32 fields", () => {
    expect(createRoomPayload("Jerry", true, "secret", "K")).toEqual({
      type: "create_room",
      name: "Jerry",
      start_level: "K",
      test_policy: "w32",
      test_access_key: "secret",
    });
  });

  it("still refuses a keyless W32 payload regardless of level", () => {
    expect(createRoomPayload("Jerry", true, "  ", "A")).toBeNull();
  });

  it("offers every rank the engine accepts", () => {
    for (const r of RANKS) {
      const payload = createRoomPayload("Jerry", false, "", r);
      expect(payload).not.toBeNull();
      if (r !== "2") expect(payload).toHaveProperty("start_level", r);
    }
  });
});
