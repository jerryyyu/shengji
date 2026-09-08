import { describe, expect, it } from "vitest";
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
