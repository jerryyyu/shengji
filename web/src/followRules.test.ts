// The follow hint names the lead's effective suit and its card count, from
// the lead and the trump alone.
import { describe, expect, it } from "vitest";
import type { Trump } from "./protocol";
import { followHint, leadSuit } from "./followRules";

const heartsTwo: Trump = { suit: "H", rank: "2", declarer: 0 };

describe("leadSuit", () => {
  it("reads trump-rank cards and jokers as trump, and needs a declared trump", () => {
    expect(leadSuit(["SK"], heartsTwo)).toBe("S");
    expect(leadSuit(["S2", "S2"], heartsTwo)).toBe("T");
    expect(leadSuit(["BJ"], { suit: "NT", rank: "5", declarer: 1 })).toBe("T");
    expect(leadSuit(["SK"], null)).toBeNull();
  });
});

describe("followHint", () => {
  it("names the suit and the count", () => {
    expect(followHint(["SK", "SK", "SA"], heartsTwo)).toBe("Follow ♠: play 3 cards");
    expect(followHint(["BJ"], heartsTwo)).toBe("Follow trump: play 1 card");
    expect(followHint(["D4"], null)).toBe("Follow the lead: play 1 card");
  });
});
