// The invite's message: what the table still needs, in the app's language,
// with the code in the text and the link after it in the share sheet.
import { afterEach, describe, expect, it, vi } from "vitest";
import { inviteAskOf, inviteText, shareInvite } from "./codes";
import { reloadLanguage, setLanguageChoice } from "./i18n";

afterEach(() => {
  localStorage.clear();
  reloadLanguage();
  vi.unstubAllGlobals();
});

describe("the invite's ask", () => {
  const at = (...looks: string[]) => looks.map((look, i) => ({ at: i, look }));

  it("counts the open seats a join by your code takes, bots and people not", () => {
    expect(inviteAskOf(at("you", "person", "friend", "open"), 0)).toBe("one");
    expect(inviteAskOf(at("you", "bot", "person", "open"), 0)).toBe("one");
    expect(inviteAskOf(at("you", "open", "person", "open"), 0)).toBe("two");
    expect(inviteAskOf(at("you", "open", "open", "open"), 0)).toBe("three");
    expect(inviteAskOf(at("you", "bot", "person", "bot"), 0)).toBe("three");
  });

  it("asks for a partner only from the Duo opener whose seat is held", () => {
    // Alice (seat 0) holds seat 2 for her partner; Bob sits at 1
    const table = at("you", "person", "held", "open");
    expect(inviteAskOf(table, 0)).toBe("partner");
    expect(inviteAskOf(at("person", "you", "held", "open"), 1)).toBe("one");
    expect(inviteAskOf(at("person", "you", "held", "person"), 1)).toBe("three");
  });
});

describe("the invite's message", () => {
  const cases = [
    ["one", "We need a 4th for Tractor. Code FW4X", "三缺一，来打升级！房间码 FW4X"],
    ["two", "Two seats open for Tractor. Code FW4X", "还差两个人，来打升级！房间码 FW4X"],
    ["three", "Play Tractor with me? Code FW4X", "来打升级吗？房间码 FW4X"],
    ["partner", "Be my partner for Tractor? Code FW4X", "来跟我搭档打升级！房间码 FW4X"],
  ] as const;

  it.each(cases)("%s reads as the mock in English and in Chinese", (ask, en, zh) => {
    setLanguageChoice("en");
    expect(inviteText("FW4X", ask)).toBe(en);
    setLanguageChoice("zh-Hans");
    expect(inviteText("FW4X", ask)).toBe(zh);
  });

  it("goes to the share sheet as the text, the link after it", async () => {
    setLanguageChoice("zh-Hans");
    const share = vi.fn(() => Promise.resolve());
    vi.stubGlobal("navigator", { ...navigator, share });
    await shareInvite("FW4X", "one");
    expect(share).toHaveBeenCalledWith({
      title: "升级", text: "三缺一，来打升级！房间码 FW4X", url: `${window.location.origin}/?code=FW4X`,
    });
  });
});
