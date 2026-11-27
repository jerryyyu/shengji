import { describe, expect, it } from "vitest";
import { COMPANIONS, FREE_KINDS, LOOK_UNLOCKS, freeLook, guestLookFor, yoursOrder } from "./look";

// Device keys and the look the server's `accounts.guest_look` draws for each;
// server/tests/test_look.py reads this table and checks it against the server.
const GUEST_VECTORS: [string, string][] = [
  ["AAAAAAAAAAAAAAAAAAAAAA", "bun/taro"],
  ["abcdefghijklmnopqrstuv", "tractor/blue"],
  ["q1w2e3r4t5y6u7i8o9p0aa", "bun/custard"],
  ["0123456789abcdefghijKL", "sparrow/snow"],
  ["________________------", "sparrow/java"],
];

describe("a guest's look", () => {
  it("is the one the server draws from the same device key", () => {
    for (const [device, look] of GUEST_VECTORS) expect(guestLookFor(device)).toBe(look);
  });

  it("is always free from the start, and every free look occurs", () => {
    const free = new Set(FREE_KINDS.flatMap((k) => COMPANIONS[k].map((c) => `${k}/${c}`))
      .filter((id) => !(id in LOOK_UNLOCKS)));
    const drawn = new Set(Array.from({ length: 400 }, (_, n) => freeLook(`guest:${String(n).padStart(22, "0")}`)));
    expect(drawn).toEqual(free);
  });
});

describe("Yours in order of use", () => {
  const kinds = ["tractor", "bun", "chick", "sparrow", "lamb"] as const;

  it("puts the one in use first, then the latest used, then the rest in Collection order", () => {
    expect(yoursOrder(kinds, "chick", ["bun/taro", "sparrow/java", "bun/plain", "chick/ink"]))
      .toEqual(["chick", "bun", "sparrow", "tractor", "lamb"]);
  });

  it("keeps Collection order with no uses, the one in use still first", () => {
    expect(yoursOrder(kinds, "tractor", undefined)).toEqual([...kinds]);
    expect(yoursOrder(kinds, "sparrow", [])).toEqual(["sparrow", "tractor", "bun", "chick", "lamb"]);
  });

  it("skips a look this client cannot draw", () => {
    expect(yoursOrder(kinds, "bun", ["dragon/jade", "lamb/ink", "tractor/mauve"]))
      .toEqual(["bun", "lamb", "tractor", "chick", "sparrow"]);
  });
});
