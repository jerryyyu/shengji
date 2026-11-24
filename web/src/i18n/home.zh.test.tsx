// The Play tab and the home shell in Simplified Chinese: the tab bar, the top
// bar, the Play block, the code box, the guest chip and its name sheet, the
// account form and the day labels all read from the home table, and the
// brand drops its English subtitle.
import { act } from "react";
import type { ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AuthState } from "../auth";

const { authState, link } = vi.hoisted(() => ({
  authState: { current: { status: "out", clientId: "cid.apps", user: null } as AuthState },
  link: { listeners: new Set<(m: unknown) => void>(), status: new Set<(s: string) => void>() },
}));
vi.mock("../ws", () => ({
  conn: { send: () => true,
          subscribe: (fn: (m: unknown) => void) => { link.listeners.add(fn); return () => link.listeners.delete(fn); },
          subscribeStatus: (fn: (s: string) => void) => { link.status.add(fn); return () => link.status.delete(fn); },
          generation: 0,
          reconnect: () => {} },
  getSavedName: () => localStorage.getItem("shengji.name") ?? "",
  saveName: (n: string) => localStorage.setItem("shengji.name", n),
  getResumeToken: () => null,
  getSavedRoom: () => null,
  clearSavedRoom: () => {},
  reconnect: () => {},
}));
vi.mock("../auth", async (importOriginal) => {
  const real = await importOriginal<typeof import("../auth")>();
  return {
    ...real,
    useAuth: () => authState.current,
    loadGis: () => new Promise(() => {}),
    auth: { signOut: vi.fn(), signedIn: vi.fn(), init: vi.fn(), updated: vi.fn() },
  };
});

import { setLanguageChoice } from ".";
import Lobby from "../components/Lobby";
import { IdentitySheet } from "../components/GuestChip";
import NameEditForm from "../components/NameEditForm";
import { TabBar, TopBar } from "../home/HomeShell";
import { dayLabel } from "../home/dayLabel";
import YourTablePill from "../queue/YourTablePill";
import { SeatedAtContext } from "../queue/seatedAt";
import { queue } from "../queue/store";
import { codes } from "../codeJoin";
import { guestName } from "../guestName";
import { checkDisplayName } from "../auth";

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;

async function render(node: ReactNode) {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => root.render(node));
}
const texts = (sel: string) => [...host.querySelectorAll(sel)].map((e) => e.textContent);

beforeEach(() => {
  queue.reset();
  codes.reset();
  localStorage.clear();
  guestName.reset();
  localStorage.setItem("shengji.name", "Sam Fox");
  authState.current = { status: "out", clientId: "cid.apps", user: null };
  setLanguageChoice("zh-Hans");
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  setLanguageChoice("system");
});

describe("the Play tab in Chinese", () => {
  it("reads the title, the mode switch, Play, Duo, the code box and the links in zh", async () => {
    await render(<><Lobby status="open" /><IdentitySheet /></>);
    const title = host.querySelector(".game-title")!;
    expect(title.textContent).toBe("升级");
    expect(title.querySelector(".game-title-en")).toBeNull();
    expect(texts(".play-mode button")).toEqual(["排位", "休闲"]);
    expect(host.querySelector(".play-mode")?.getAttribute("aria-label")).toBe("模式");
    expect(texts(".play-ranked-row button")).toEqual(["开始", "组队"]);
    expect(host.querySelector("section.play-section")?.getAttribute("aria-label")).toBe("打牌");
    const code = host.querySelector<HTMLInputElement>(".room-input")!;
    expect(code.placeholder).toBe("房间码");
    expect(code.getAttribute("aria-label")).toBe("房间码");
    expect(host.querySelector(".join-row .btn")?.textContent).toBe("加入");
    expect(host.querySelector(".play-guest-line")?.textContent).toBe("游客身份 · 登录后计入排位");
    expect(host.querySelector(".play-guest-signin")?.textContent).toBe("登录");
    expect(texts(".howto-link")[0]).toBe("怎么玩");
    expect(host.querySelector(".app-store-badge img")?.getAttribute("alt")).toBe("在 App Store 下载");
    expect(host.querySelector(".app-store-badge img")?.getAttribute("src")).toBe("/badges/app-store-zh.svg");
    expect(host.textContent).not.toMatch(/Sheng Ji|Ranked|Casual|Duo|Join|How to play|Playing as a guest/);
  });

  it("the guest chip and its name sheet read in zh", async () => {
    await render(<><Lobby status="open" /><IdentitySheet /></>);
    const chip = host.querySelector<HTMLButtonElement>(".guest-pill")!;
    expect(chip.querySelector(".account-pill-rating")?.textContent).toBe("游客");
    expect(chip.getAttribute("aria-label")).toBe("Sam Fox，游客，改昵称");
    act(() => chip.click());
    const field = host.querySelector<HTMLInputElement>("input[autocomplete='nickname']")!;
    expect(field.getAttribute("aria-label")).toBe("昵称");
    expect(field.placeholder).toBe("比如：小明");
    expect(host.querySelector(".name-reroll")?.getAttribute("aria-label")).toBe("随机昵称");
    expect(host.querySelector(".identity-terms")?.textContent).toBe("登录即表示你同意使用条款。");
    expect(host.querySelector(".identity-terms a")?.textContent).toBe("使用条款");
    expect(texts(".guest-name-sheet .btn.gold")).toEqual(["完成"]);
  });

  it("a connection on its way reads 连接中…", async () => {
    await render(<Lobby status="connecting" />);
    expect(host.querySelector(".play-presence")?.textContent).toBe("连接中…");
  });
});

describe("the home shell in Chinese", () => {
  it("the tab bar reads 打牌 · 排行榜 · 我", async () => {
    await render(<TabBar active="play" />);
    expect(texts(".tabbar-item span:last-child")).toEqual(["打牌", "排行榜", "我"]);
    expect(host.querySelector(".tabbar")?.getAttribute("aria-label")).toBe("主导航");
  });

  it("the top bar's mark is the brand alone, labelled 升级：打牌", async () => {
    await render(<TopBar active="leaderboard" />);
    const mark = host.querySelector(".topbar-mark")!;
    expect(mark.getAttribute("aria-label")).toBe("升级：打牌");
    expect(mark.textContent).toBe("升级");
    expect(mark.querySelector("span")).toBeNull();
    expect(texts(".topbar-tab")).toEqual(["打牌", "排行榜", "我"]);
  });

  it("the Your game pill reads 我的牌局", async () => {
    await render(<SeatedAtContext.Provider value="game"><YourTablePill /></SeatedAtContext.Provider>);
    const pill = host.querySelector(".table-pill")!;
    expect(pill.textContent).toBe("我的牌局");
    expect(pill.getAttribute("aria-label")).toBe("我的牌局，回到打牌");
  });

  it("the account's name form reads in zh, and so do its refusals", async () => {
    const user = { name: "Jerry Yu", email: "j@example.com", picture: null, display_name: null, name_shown: "Jerry" };
    await render(<NameEditForm user={user} onDone={() => {}} />);
    expect(host.querySelector(".name-edit-input")?.getAttribute("aria-label")).toBe("昵称");
    expect(texts(".name-edit-actions button")).toEqual(["保存", "取消"]);
    const check = checkDisplayName("");
    expect(check.ok ? null : check.message).toBe("请输入昵称。");
  });

  it("day headings read 今天 and 昨天", () => {
    const now = new Date(2026, 10, 11, 12);
    expect(dayLabel(new Date(2026, 10, 11, 1).getTime() / 1000, now)).toBe("今天");
    expect(dayLabel(new Date(2026, 10, 10, 23).getTime() / 1000, now)).toBe("昨天");
    expect(dayLabel(new Date(2026, 10, 8, 12).getTime() / 1000, now)).toMatch(/11月8日/);
  });
});
