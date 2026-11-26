import { describe, expect, it } from "vitest";
import { DISPLAY_NAME_MAX, checkDisplayName } from "./auth";
import { NAME_ADJECTIVES, NAME_NOUNS, ZH_NAMES, isRandomName, randomName } from "./randomName";
import { setLanguageChoice } from "./i18n";

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

describe("randomName in a Chinese interface", () => {
  it("has 20 moods and 20 game words per script, no repeats, the same shape in both", () => {
    for (const loc of ["zh-Hans", "zh-Hant"]) {
      const { moods, words } = ZH_NAMES[loc];
      expect(moods).toHaveLength(20);
      expect(words).toHaveLength(20);
      expect(new Set(moods).size).toBe(20);
      expect(new Set(words).size).toBe(20);
    }
    // Traditional is the same words, character for character where the scripts agree
    expect(ZH_NAMES["zh-Hant"].words.map((w) => w.length)).toEqual(ZH_NAMES["zh-Hans"].words.map((w) => w.length));
  });

  it("every combination is a mood, 的 and a word, at most six characters, and passes the display-name rules", () => {
    for (const loc of ["zh-Hans", "zh-Hant"]) {
      const { moods, words } = ZH_NAMES[loc];
      for (const mood of moods) {
        for (const word of words) {
          const name = `${mood}的${word}`;
          expect(name.length).toBeLessThanOrEqual(6);
          expect(checkDisplayName(name)).toEqual({ ok: true, value: name });
          expect(isRandomName(name)).toBe(true);
        }
      }
    }
  });

  it("draws from the interface's own list, and English elsewhere", () => {
    expect(randomName("", () => 0, "zh-Hans")).toBe("淡定的庄家");
    expect(randomName("", () => 0.999, "zh-Hant")).toBe("瀟灑的下家");
    expect(randomName("淡定的庄家", () => 0, "zh-Hans")).toBe("淡定的闲家");
    expect(randomName("", () => 0, "en")).toBe("Lucky Spades");
    setLanguageChoice("zh-Hans");
    try {
      const name = randomName();
      const [mood, word] = name.split("的");
      expect(ZH_NAMES["zh-Hans"].moods).toContain(mood);
      expect(ZH_NAMES["zh-Hans"].words).toContain(word);
    } finally {
      setLanguageChoice("system");
    }
    expect(NAME_ADJECTIVES).toContain(randomName().split(" ")[0]);
  });

  it("knows a typed name from a drawn one in either language", () => {
    expect(isRandomName("Lucky Spades")).toBe(true);
    expect(isRandomName("機智的大王")).toBe(true);
    for (const typed of ["Mei Lin", "小明", "淡定的", "的庄家", "淡定的庄家的大王", "Lucky Spades Ace"]) {
      expect(isRandomName(typed)).toBe(false);
    }
  });
});
