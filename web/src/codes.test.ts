// The invite's message: what the table still needs, in the app's language,
// with the code in the text and the link after it in the share sheet.
import { afterEach, describe, expect, it, vi } from "vitest";
import { inviteAsk, inviteAskOf, inviteText, shareInvite } from "./codes";
import { reloadLanguage, setLanguageChoice } from "./i18n";

afterEach(() => {
  localStorage.clear();
  reloadLanguage();
  vi.unstubAllGlobals();
});

describe("the invite's ask", () => {
  it("counts the people seated, and a held seat asks for a partner", () => {
    expect(inviteAsk(3)).toBe("one");
    expect(inviteAsk(2)).toBe("two");
    expect(inviteAsk(1)).toBe("three");
    expect(inviteAsk(4)).toBe("three");
    expect(inviteAsk(1, true)).toBe("partner");
  });

  it("reads the panel's seats, bots and open seats not counted", () => {
    expect(inviteAskOf(["you", "person", "friend", "open"])).toBe("one");
    expect(inviteAskOf(["you", "bot", "person", "open"])).toBe("two");
    expect(inviteAskOf(["you", "open", "open", "open"])).toBe("three");
    expect(inviteAskOf(["you", "open", "held", "open"])).toBe("partner");
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
