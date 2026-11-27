import { describe, expect, it } from "vitest";
import { COMPANIONS, FREE_KINDS, freeLook, guestLookFor, yoursOrder } from "./look";

// Device keys and the look the server's `accounts.guest_look` draws for each;
// server/tests/test_look.py reads this table and checks it against the server.
const GUEST_VECTORS: [string, string][] = [
  ["AAAAAAAAAAAAAAAAAAAAAA", "bun/plain"],
  ["abcdefghijklmnopqrstuv", "tractor/red"],
  ["chickchickchickchick02", "chick/yellow"],
  ["0123456789abcdefghijKL", "sparrow/tree"],
  ["________________------", "sparrow/tree"],
];

describe("a guest's look", () => {
  it("is the one the server draws from the same device key", () => {
    for (const [device, look] of GUEST_VECTORS) expect(guestLookFor(device)).toBe(look);
  });

  it("is a free companion in its default colour, and every free companion occurs", () => {
    const defaults = new Set(FREE_KINDS.map((k) => `${k}/${COMPANIONS[k][0]}`));
    const drawn = new Set(Array.from({ length: 400 }, (_, n) => freeLook(`guest:${String(n).padStart(22, "0")}`)));
    expect(drawn).toEqual(defaults);
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
