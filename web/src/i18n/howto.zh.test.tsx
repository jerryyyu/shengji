// How to play in Simplified Chinese: the head, every step's title and body,
// the picture captions and the controls come from the zh table, and the
// numbers carry over unchanged.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import HowTo from "../howto/HowTo";
import { setLanguageChoice } from ".";

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;

async function open(step: number) {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => root.render(<HowTo route={{ step }} />));
}
const text = (sel: string) => host.querySelector(sel)?.textContent;
const all = () => host.textContent ?? "";
const labels = () => [...host.querySelectorAll("[aria-label]")].map((el) => el.getAttribute("aria-label"));

beforeEach(() => setLanguageChoice("zh-Hans"));
afterEach(() => {
  act(() => root?.unmount());
  host?.remove();
  setLanguageChoice("system");
});

describe("How to play in zh-Hans", () => {
  it("draws the head, the counter and the nav from the zh table", async () => {
    await open(1);
    const bar = [...host.querySelector(".howto-head")!.children].map((el) => el.textContent);
    expect(bar).toEqual(["‹ 返回", "怎么玩", "1/10"]);
    expect(text(".howto-title")).toBe("从 2 打到 A");
    expect(text(".howto-nav button")).toBe("下一步");
    expect(host.querySelector(".howto-nav")!.getAttribute("aria-label")).toBe("步骤");
    expect(labels()).toEqual(expect.arrayContaining(["级数 2 到 A", "重播动画", "显示静态图"]));
    expect(all()).toContain("Bea · 搭档");
    expect([...host.querySelectorAll(".level-chip")].map((c) => c.textContent)).toEqual(["我方 2", "对方 2"]);
    expect(all()).not.toMatch(/partner|Lv |Us |Them /);
  });

  it("names the trump order and the declarations in Chinese", async () => {
    await open(2);
    expect(text(".howto-title")).toBe("主牌最大");
    expect(text(".howto-body")).toBe("这一局打 7。大小王、所有的 7 和一门花色都是主牌，算作同一门。从大到小：");
    expect(text(".howto-label")).toBe("主");
    expect(all()).toContain("1 大王");
    expect(all()).toContain("2 小王");
    expect(all()).toContain("然后是其余的 ♥，从 A 到 2");
    act(() => root.unmount());
    host.remove();
    await open(3);
    expect(text(".howto-title")).toBe("亮主定主");
    expect([...host.querySelectorAll(".howto-declare-what")].map((el) => el.textContent))
      .toEqual(["一对大王", "一对小王", "一对 7", "一张 7"]);
    expect(all()).toContain("无主");
  });

  it("uses 庄家方 / 闲家 and 埋底 for the banker and kitty", async () => {
    await open(4);
    expect(text(".howto-title")).toBe("庄家和底牌");
    expect(text(".howto-body")).toBe("第一局由亮主成立的人坐庄，没人亮主就由首位坐庄。庄家拿底牌、埋底，然后先出牌。每一局都打庄家方的级数。");
    expect(all()).toContain("庄家方守分");
    expect(all()).toContain("闲家捡分");
    expect(all()).not.toMatch(/守方|攻方|扣底/);
  });

  it("carries every scoring number and band over exactly", async () => {
    await open(9);
    expect(text(".howto-title")).toBe("一局的结算");
    expect(text(".howto-body")).toBe("闲家拿到 80 分就赢下这一局。每多或少 40 分，升降一级。");
    const bands = [...host.querySelectorAll(".howto-bands li")].map((li) => li.textContent);
    expect(bands).toEqual([
      "0庄家方升 3 级", "5–35庄家方升 2 级", "40–75庄家方升 1 级", "80–115闲家上台",
      "120–155闲家升 1 级", "160–195闲家升 2 级", "200+闲家升 3 级，每多 40 分再升 1 级",
    ]);
  });

  it("explains the last-trick multiplier and ends on 完成, or 打一局练习 then 完成 where a round can start", async () => {
    await open(8);
    expect(text(".howto-kitty-head")).toBe("最后一轮抠底");
    expect(text(".howto-kitty-mult")).toBe("×2 单张 · ×4 对子 · ×8 两对的拖拉机");
    act(() => root.unmount());
    host.remove();
    await open(10);
    expect(text(".howto-caption")).toBe("顶栏记着盘数。登录后打完整的一局排位才计入积分，休闲局不计。");
    expect(all()).toContain("盘数 1–0");
    expect([...host.querySelectorAll(".level-chip")].map((c) => c.textContent)).toEqual(["我方 A", "我方 2", "对方 2"]);
    expect(text(".howto-nav button")).toBe("完成");
    act(() => root.unmount());
    host.remove();
    host = document.createElement("div");
    document.body.appendChild(host);
    root = createRoot(host);
    await act(async () => root.render(<HowTo route={{ step: 10 }} onPractice={() => {}} />));
    expect([...host.querySelectorAll(".howto-nav button")].map((b) => b.textContent)).toEqual(["打一局练习", "完成"]);
  });

  it("redraws the open step and its picture when the language changes", async () => {
    await open(4);
    expect(all()).toContain("庄家方守分");
    await act(async () => setLanguageChoice("en"));
    expect(text(".howto-title")).toBe("Banker and kitty");
    expect(all()).toContain("Banker's team defends");
    expect(labels()).toContain("Replay animation");
  });

  it("goes back to English when the choice resets", async () => {
    setLanguageChoice("en");
    await open(1);
    expect(text(".howto-title")).toBe("Climb from 2 to Ace");
    expect(text(".howto-count")).toBe("1 of 10");
  });
});

describe("How to play in zh-Hant", () => {
  beforeEach(() => setLanguageChoice("zh-Hant"));

  it("is written in Traditional characters on every step, with no Simplified form left over", async () => {
    const titles: (string | undefined)[] = [];
    let seen = "";
    for (let step = 1; step <= 10; step++) {
      await open(step);
      titles.push(text(".howto-title"));
      seen += all();
      act(() => root.unmount());
      host.remove();
    }
    expect(titles).toEqual(["從 2 打到 A", "主牌最大", "亮主定主", "莊家和底牌", "出一輪牌",
      "對子和拖拉機", "甩牌", "分數", "一局的結算", "贏下一盤"]);
    expect(seen).not.toMatch(/[庄闲对张门级赢轮队这谁选盘积闲机发]/);
    await open(1);
  });

  it("says who is banker, the round's level and what ranked means in Traditional Chinese", async () => {
    await open(4);
    expect(text(".howto-body")).toBe("第一局由亮主成立的人坐莊，沒人亮主就由首位坐莊。莊家拿底牌、埋底，然後先出牌。每一局都打莊家方的級數。");
    expect(all()).toContain("莊家方守分");
    act(() => root.unmount());
    host.remove();
    await open(10);
    expect(text(".howto-caption")).toBe("畫面上方記著盤數。登入後打完整的一局排位才計入積分，休閒局不計。");
    expect([...host.querySelectorAll(".level-chip")].map((c) => c.textContent)).toEqual(["我方 A", "我方 2", "對方 2"]);
  });
});
