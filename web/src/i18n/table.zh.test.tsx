// The game table in Simplified Chinese: each phase's controls, the header,
// the coach line, the cards' spoken names and the engine's table messages
// draw their words from messages/table.ts.
import { act } from "react";
import type { ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import type { GameState, HandCard, StatePlayer } from "../protocol";

vi.mock("../ws", () => ({
  conn: {
    status: "open",
    generation: 1,
    send: () => true,
    subscribe: () => () => {},
    subscribeStatus: (fn: (s: string) => void) => { fn("open"); return () => {}; },
    chatHistory: () => [],
    reconnect: () => {},
  },
}));

const { default: Table } = await import("../components/Table");
const { default: LastTrickPanel } = await import("../components/LastTrickPanel");
const { default: ChatPanel } = await import("../components/ChatPanel");
const { spokenLabel } = await import("../components/Card");
const { formatTableMessage } = await import("../messageCopy");
const { buryHelp, nextBankerText, seatStatus, teamMembers } = await import("../tableCopy");
const { followHint } = await import("../followRules");
const { COACH_KEY, forgetSessionCoach } = await import("../firstTurns");
const { setLanguageChoice } = await import(".");

function player(seat: number, over: Partial<StatePlayer> = {}): StatePlayer {
  return { seat, name: seat ? `Bot ${seat}` : "Jerry", is_bot: seat !== 0, connected: true,
    team: (seat % 2) as 0 | 1, cards_left: 25, is_banker: false, takeover_in: null,
    controller: seat ? "bot" : "human", reserved_for: null, reserved_secs: null, ...over };
}

function state(over: Partial<GameState> = {}): GameState {
  return {
    type: "state", room: "T", you: 0, phase: "play", players: [0, 1, 2, 3].map((s) => player(s)),
    hand: [], levels: ["2", "2"], games_won: [0, 0], banker: 1, trump: null, turn: 1,
    declare_options: [], current_declaration: null, passed: [], trick: null, last_trick: null,
    attacker_points: 0, kitty_count: 8, round_result: null, message: null, notice: null, ...over,
  };
}

const hand = (codes: string[]): HandCard[] => codes.map((code, i) => ({ id: i + 1, code }));

beforeAll(() => {
  class SilentAudioContext { state = "running"; currentTime = 0; async resume() {} }
  (window as unknown as { AudioContext: unknown }).AudioContext = SilentAudioContext;
});

const originalScroll = Object.getOwnPropertyDescriptor(Element.prototype, "scrollIntoView");
let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
beforeEach(() => {
  setLanguageChoice("zh-Hans");
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  localStorage.removeItem(COACH_KEY);
  forgetSessionCoach();
  setLanguageChoice("system");
  if (originalScroll) Object.defineProperty(Element.prototype, "scrollIntoView", originalScroll);
  else delete (Element.prototype as { scrollIntoView?: unknown }).scrollIntoView;
});
const render = (node: ReactNode) => act(() => root.render(node));
const buttons = () => [...host.querySelectorAll("button")].map((b) => b.textContent?.trim());

describe("the table in zh-Hans", () => {
  it("declares: the pill, the declare buttons and Pass", () => {
    render(<Table state={state({
      phase: "declare", turn: null, banker: null, hand: hand(["H2", "S2", "S2", "BJ", "BJ"]),
      declare_options: [[1], [2, 3], [4, 5]],
    })} />);
    expect(host.querySelector(".action-bar")?.getAttribute("data-declare-label")).toBe("亮主");
    expect([...host.querySelectorAll(".declare-full")].map((e) => e.textContent)).toEqual(["亮♥2", "亮一对♠2", "亮无主"]);
    expect([...host.querySelectorAll(".declare-short")].map((e) => e.textContent)).toEqual(["♥2", "一对♠2", "无主"]);
    expect(buttons()).toContain("不亮");
    expect(host.querySelector(".trump-none-long")?.textContent).toBe("未亮主");
    expect(host.querySelector(".trump-none-short")?.textContent).toBe("未亮主");
    expect(host.querySelector(".team-word")?.textContent).toBe("我方");
  });

  it("tags a declaration with one sentence", () => {
    render(<Table state={state({
      phase: "declare", turn: null, banker: null, current_declaration: { seat: 1, cards: ["S2", "S2"] },
    })} />);
    expect(host.querySelector(".declare-tag")?.textContent).toBe("Bot 1 亮一对♠2");
  });

  it("buries: the count on the button, the help and the points", () => {
    localStorage.setItem(COACH_KEY, "on");
    const players = [0, 1, 2, 3].map((s) => player(s, { is_banker: s === 0 }));
    render(<Table state={state({ phase: "bury", turn: 0, banker: 0, players, hand: hand(["S5", "SK", "H3"]) })} />);
    expect(buttons()).toContain("埋底（0/8）");
    expect(host.querySelector(".bury-points")?.textContent).toBe("埋底 0 分");
    expect(host.querySelector(".hand-line")?.textContent).toBe(buryHelp());
    expect(buryHelp()).toContain("抠底");
    expect(host.querySelector(".banker-crown")?.getAttribute("aria-label")).toBe("我，庄家");
  });

  it("plays: Play, Your turn, Clear, the coach and the cards' names", () => {
    localStorage.setItem(COACH_KEY, "on");
    render(<Table state={state({
      turn: 0, trump: { suit: "H", rank: "2", declarer: 1 }, hand: hand(["SA", "S10", "BJ", "D4"]),
      trick: { leader: 1, plays: [{ seat: 1, cards: ["S3"] }] },
    })} />);
    expect(host.querySelector(".play-text")?.textContent).toBe("出牌");
    expect(host.querySelector(".your-turn-text")?.textContent).toBe("该你了");
    expect(host.querySelector(".your-turn-tag")?.textContent).toBe("该你了");
    expect(buttons()).toContain("重选");
    expect(host.querySelector(".hand-line")?.textContent).toBe("点 1 张♠，再点出牌");
    expect(host.querySelector(".lead-tag")?.textContent).toBe("首家");
    expect(host.querySelector(".hand")?.getAttribute("aria-label")).toBe("手牌，4 张");
    const names = [...host.querySelectorAll(".hand .card")].map((c) => c.getAttribute("aria-label"));
    expect(names).toEqual(["黑桃 A", "黑桃 10", "大王", "方块 4"]);
    expect(host.querySelector(".trump-suit")?.textContent).toBe("♥");
    expect(host.querySelector(".hud-more-btn")?.getAttribute("aria-label")).toBe("更多");
  });

  it("names each seat's state", () => {
    expect(seatStatus(player(2, { is_bot: false, connected: false, left: true, name: "Alice" }), null))
      .toBe("机器人（Alice 已离开）");
    expect(seatStatus(player(2, { is_bot: false, connected: false, controller: "bot_cover" }), null)).toBe("机器人代打");
    expect(seatStatus(player(2, { is_bot: false, connected: false }), 27.2)).toBe("掉线，机器人接手 28 秒");
  });

  it("shows the last trick", () => {
    const s = state({ phase: "play" });
    render(<LastTrickPanel state={s} trick={{ leader: 1, winner: 0, points: 10,
      plays: [{ seat: 1, cards: ["S5"] }, { seat: 0, cards: ["SA"] }] }} onClose={() => {}} />);
    expect(host.querySelector(".last-trick-head b")?.textContent).toBe("上一轮");
    expect(host.querySelector(".last-trick-sum")?.textContent).toBe("我赢 · 10 分");
    expect(host.querySelector(".last-trick-tag.win")?.textContent).toBe("最大");
  });

  it("opens chat", () => {
    Object.defineProperty(Element.prototype, "scrollIntoView", { configurable: true, value: vi.fn() });
    render(<ChatPanel messages={[]} you={0} open onClose={() => {}} />);
    expect(host.querySelector(".chat-head span")?.textContent).toBe("聊天");
    expect(buttons()).toContain("发送");
    expect(host.querySelector("input")?.getAttribute("placeholder")).toBe("说点什么…");
  });

  it("words the engine's messages, the follow hint and the round-end lines", () => {
    const players = [0, 1, 2, 3].map((s) => player(s));
    expect(formatTableMessage("Seat 1 declared H2 (pair)", players, 0)).toBe("Bot 1 亮一对♥2");
    expect(formatTableMessage("Seat 0 declared NT", players, 0)).toBe("我亮无主");
    expect(formatTableMessage("No declaration — trump flipped from the kitty: C", players, 0)).toBe("没人亮主，翻底定主：♣");
    expect(followHint(["SK", "SK"], { suit: "H", rank: "2", declarer: 1 })).toBe("跟♠：出 2 张牌");
    expect(followHint(["BJ"], { suit: "H", rank: "2", declarer: 1 })).toBe("跟主牌：出 1 张牌");
    const s = state();
    expect(teamMembers(0, s)).toBe("我和 Bot 2");
    expect(teamMembers(1, s)).toBe("Bot 1 和 Bot 3");
    expect(nextBankerText(s, { next_banker: 0 } as never)).toBe("下局庄家：我");
    expect(spokenLabel("C10")).toBe("梅花 10");
    expect(spokenLabel("LJ")).toBe("小王");
  });
});
