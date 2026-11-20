import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import cases from "./chatFilterCases.gen.json";
import { containsBlocked, maskChat, parseChatFilter } from "./chatFilter";
import { CHAT_FILTER_WORDS } from "./chatFilterWords.gen";
import { nearbyName, validNearbyName } from "./names";

const SERVER_WORDS = resolve(__dirname, "../../../../../server/shengji/api/chat_filter_words.txt");

describe("bundled name filter", () => {
  it("bundles the server's word list byte for byte", () => {
    expect(CHAT_FILTER_WORDS).toBe(readFileSync(SERVER_WORDS, "utf8"));
  });

  it("gives the Python filter's answer on every recorded case", () => {
    expect(cases.length).toBeGreaterThan(300);
    for (const c of cases) {
      expect({ text: c.text, mask: maskChat(c.text), contains: containsBlocked(c.text) }).toEqual(c);
    }
  });

  it("keeps the list syntax", () => {
    const { latin, cjk } = parseChatFilter(["# a comment", "", "darn*", "heck", "=咦", "哎!呀"]);
    expect(latin!.test("darn") && latin!.test("darnnnn") && latin!.test("darning")).toBe(true);
    expect(latin!.test("heck") && !latin!.test("hecking")).toBe(true);
    expect("咦".match(cjk!)).not.toBeNull();
    expect("咦呀".match(cjk!)).toBeNull();
    expect("哎哟".match(cjk!)).not.toBeNull();
    expect("哎呀".match(cjk!)).toBeNull();
  });

  it("refuses a listed name on the host, which seats it as Player N", () => {
    expect(validNearbyName("sh1thead")).toBeNull();
    expect(validNearbyName("傻B")).toBeNull();
    expect(nearbyName("fuuuck", 2)).toBe("Player 3");
    expect(validNearbyName("Scunthorpe")).toBe("Scunthorpe");
    expect(validNearbyName("曹操")).toBe("曹操");
    expect(validNearbyName("fuck", null)).toBe("fuck");
  });
});
