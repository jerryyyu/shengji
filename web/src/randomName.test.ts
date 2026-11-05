import { describe, expect, it } from "vitest";
import { DISPLAY_NAME_MAX, checkDisplayName } from "./auth";
import { NAME_ADJECTIVES, NAME_NOUNS, randomName } from "./randomName";

describe("randomName", () => {
  it("has about 30 adjectives and 20 nouns, no repeats", () => {
    expect(NAME_ADJECTIVES).toHaveLength(30);
    expect(NAME_NOUNS).toHaveLength(20);
    expect(new Set(NAME_ADJECTIVES).size).toBe(NAME_ADJECTIVES.length);
    expect(new Set(NAME_NOUNS).size).toBe(NAME_NOUNS.length);
  });

  it("every combination passes the display-name rules unchanged", () => {
    for (const adj of NAME_ADJECTIVES) {
      for (const noun of NAME_NOUNS) {
        const name = `${adj} ${noun}`;
        expect(name.length).toBeLessThanOrEqual(DISPLAY_NAME_MAX);
        expect(/^[A-Z][a-z]+ [A-Z][a-z]+$/.test(name)).toBe(true);
        expect(checkDisplayName(name)).toEqual({ ok: true, value: name });
      }
    }
  });

  it("returns an adjective and a noun from the lists", () => {
    const name = randomName();
    const [adj, noun] = name.split(" ");
    expect(NAME_ADJECTIVES).toContain(adj);
    expect(NAME_NOUNS).toContain(noun);
  });

  it("never returns the name it is asked to avoid, even with a stuck random source", () => {
    expect(randomName("", () => 0)).toBe("Lucky Spades");
    expect(randomName("Lucky Spades", () => 0)).toBe("Lucky Hearts");
    expect(randomName("Lucky Spades", () => 0.999)).toBe("Wise Ten");
    for (let i = 0; i < 200; i++) {
      const before = randomName();
      expect(randomName(before)).not.toBe(before);
    }
  });
});
