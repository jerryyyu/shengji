// The invite's message: what the table still needs, in the app's language,
// with the code in the text and the link after it in the share sheet.
import { afterEach, describe, expect, it, vi } from "vitest";
import { HOST_KEY, codeLink, hostToken, inviteAskOf, inviteText, setInviteReporter, shareInvite } from "./codes";
import { reloadLanguage, setLanguageChoice } from "./i18n";

afterEach(() => {
  setInviteReporter(null);
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

  it("with a seat held, the table's code takes it: its holder asks for a partner, anyone else asks plainly", () => {
    // Alice (seat 0) holds seat 2 for her partner; Bob sits at 1
    expect(inviteAskOf(at("you", "person", "held", "open"), 0)).toBe("partner");
    expect(inviteAskOf(at("person", "you", "held", "open"), 1)).toBe("three");
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
      title: "升级", text: "三缺一，来打升级！房间码 FW4X", url: `${window.location.origin}/?code=FW4X&h=${hostToken()}`,
    });
  });
});

describe("the invite link's sender token", () => {
  it("is minted once per device and rides the link beside the code, which still reads", () => {
    const token = hostToken();
    expect(token).toMatch(/^[0-9a-f]{12}$/);
    expect(hostToken()).toBe(token);
    expect(localStorage.getItem(HOST_KEY)).toBe(token);
    const url = new URL(codeLink("FW4X"));
    expect(url.pathname).toBe("/");
    expect(url.searchParams.get("code")).toBe("FW4X");
    expect(url.searchParams.get("h")).toBe(token);
  });

  it("is minted again over a kept value off its pattern", () => {
    localStorage.setItem(HOST_KEY, "Mei");
    expect(hostToken()).toMatch(/^[0-9a-f]{12}$/);
  });

  it("goes with a completed share as created via share, and a copy as created via copy", async () => {
    const steps: unknown[][] = [];
    setInviteReporter((...args) => { steps.push(args); });
    vi.stubGlobal("navigator", { ...navigator, share: vi.fn(() => Promise.resolve()) });
    await shareInvite("FW4X", "one");
    const writeText = vi.fn(() => Promise.resolve());
    vi.stubGlobal("navigator", { ...navigator, share: undefined, clipboard: { writeText } });
    expect(await shareInvite("FW4X", "one")).toBe(true);
    expect(steps).toEqual([["created", "share", hostToken()], ["created", "copy", hostToken()]]);
  });

  it("says nothing for a dismissed share sheet or a refused copy", async () => {
    const steps: unknown[][] = [];
    setInviteReporter((...args) => { steps.push(args); });
    vi.stubGlobal("navigator", { ...navigator, share: vi.fn(() => Promise.reject(new Error("AbortError"))) });
    await shareInvite("FW4X", "one");
    vi.stubGlobal("navigator", { ...navigator, share: undefined,
                                 clipboard: { writeText: vi.fn(() => Promise.reject(new Error("denied"))) } });
    expect(await shareInvite("FW4X", "one")).toBe(false);
    expect(steps).toEqual([]);
  });
});
