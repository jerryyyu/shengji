import { describe, expect, it } from "vitest";
import { nameWidthClass } from "./nameWidth";

describe("nameWidthClass", () => {
  it("steps long and wide names down", () => {
    expect(nameWidthClass("Bot 1")).toBe("s");
    expect(nameWidthClass("Alexandria")).toBe("l");
    expect(nameWidthClass("Jonathan")).toBe("m");
    expect(nameWidthClass("Christopher-Jonathan")).toBe("l");
    expect(nameWidthClass("李小龙")).toBe("s");
    expect(nameWidthClass("王思聪的朋友们")).toBe("l");
    expect(nameWidthClass("😀😀 Party")).toBe("l");
    expect(nameWidthClass("WWWWWWWWWWWW")).toBe("l");
    expect(nameWidthClass("x".repeat(32))).toBe("l");
  });
});
