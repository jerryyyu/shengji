// The round end, the leave sheet and the connection pill in Simplified
// Chinese (the round end in Traditional too), and the round end's lanes, points bar and status line in both
// languages on both sides of 80.
import { act } from "react";
import type { ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { GameState, RoundResult, StatePlayer } from "../protocol";

vi.mock("../ws", () => ({ conn: { send: () => true, generation: 1, reconnect: () => {} } }));
vi.mock("../components/offlineGame", () => ({ offlineGame: { startFromPlay: () => {} }, offlineOffered: () => true }));

const { setLanguageChoice } = await import(".");
const { default: RoundEndModal } = await import("../components/RoundEndModal");
const { default: ConnectionPill, SeatHeldPill } = await import("../components/ConnectionPill");
const { leaveCopy } = await import("../components/leaveCopy");

function player(seat: number, name: string, team: 0 | 1, isBot = false): StatePlayer {
  return {
    seat, name, is_bot: isBot, connected: true, team, cards_left: 0,
    is_banker: false, takeover_in: null, controller: isBot ? "bot" : "human",
    reserved_for: null, reserved_secs: null,
  } as StatePlayer;
}

/** Seat 0 is you; `banker` picks who attacks: banker 0, they attack; banker 1, we do. */
function table(banker: 0 | 1, extra: Partial<GameState> = {}): GameState {
  return {
    type: "state", room: "TEST", you: 0, phase: "round_end",
    players: [player(0, "Me", 0), player(1, "Robin", 1), player(2, "Sam", 0), player(3, "Bot 3", 1, true)],
    hand: [], levels: ["2", "2"] as [string, string], games_won: [0, 0], banker, trump: null,
    turn: null, declare_options: [], current_declaration: null, passed: [],
    trick: null, last_trick: null, attacker_points: 0, kitty_count: 8,
    round_result: null, message: null, notice: null,
    ...extra,
  };
}

function result(o: Partial<RoundResult>): RoundResult {
  return {
    attacker_points: 0, kitty_points: 0, kitty_cards: [], winner_team: 0,
    level_change: 1, next_banker: 2, new_levels: ["2", "2"] as [string, string],
    game_over: false, games_won: [0, 0], point_scored: false,
    ...o,
  };
}

let root: ReturnType<typeof createRoot> | null = null;
let host: HTMLDivElement;

function render(node: ReactNode): HTMLDivElement {
  if (root) act(() => root!.unmount());
  host?.remove();
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  act(() => root!.render(node));
  return host;
}

const line = () => host.querySelector(".result-line")!.textContent;
const title = () => host.querySelector("h2")!.textContent;

beforeEach(() => {
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", { configurable: true, value: function (this: HTMLDialogElement) {
    this.setAttribute("open", "");
  } });
  Object.defineProperty(HTMLDialogElement.prototype, "close", { configurable: true, value: function (this: HTMLDialogElement) {
    this.removeAttribute("open");
  } });
});
afterEach(() => {
  setLanguageChoice("system");
  if (root) act(() => root!.unmount());
  root = null;
  host?.remove();
});

const lanes = () => [...host.querySelectorAll(".rank-lane")].map((l) => l.getAttribute("aria-label"));
const laneLabels = () => [...host.querySelectorAll(".lane-label")].map((l) => l.textContent);

// banker 0 (we defend at 2): they took 45 and we go up 1; they took 120 and go up 1.
// banker 1 (we attack, they defend at 2): we took 45 and they go up 1; we took 120 and go up 1.
const CASES = [
  { banker: 0 as const, points: 45, winner: 0 as const, levels: ["3", "2"] as [string, string],
    en: ["Us: 2 to 3", "Them: 2"], zh: ["我方：2 升到 3", "对方：2"] },
  { banker: 0 as const, points: 120, winner: 1 as const, levels: ["2", "3"] as [string, string],
    en: ["Us: 2", "Them: 2 to 3"], zh: ["我方：2", "对方：2 升到 3"] },
  { banker: 1 as const, points: 45, winner: 1 as const, levels: ["2", "3"] as [string, string],
    en: ["Us: 2", "Them: 2 to 3"], zh: ["我方：2", "对方：2 升到 3"] },
  { banker: 1 as const, points: 120, winner: 0 as const, levels: ["3", "2"] as [string, string],
    en: ["Us: 2 to 3", "Them: 2"], zh: ["我方：2 升到 3", "对方：2"] },
];
const trump2 = { suit: "S", rank: "2", declarer: null };

describe("the round end's pictures and status line, both languages, both sides of 80", () => {
  for (const c of CASES) {
    const who = c.banker === 0 ? "They" : "We";
    it(`${who} took ${c.points}: the lanes, the bar and the one status line, no sentence`, () => {
      const r = result({ attacker_points: c.points, winner_team: c.winner, new_levels: c.levels });
      render(<RoundEndModal state={table(c.banker, { trump: trump2 })} result={r} />);
      expect(lanes()).toEqual(c.en);
      expect(laneLabels()).toEqual(["Us", "Them"]);
      expect(host.querySelector(".points-bar-n")!.textContent).toBe(String(c.points));
      expect(line()).toBe("Next banker: Sam.");
      act(() => setLanguageChoice("zh-Hans"));
      expect(lanes()).toEqual(c.zh);
      expect(laneLabels()).toEqual(["我方", "对方"]);
      expect(host.querySelector(".points-bar")!.getAttribute("aria-label")).toBe(`闲家得分：${c.points}，80 分上台`);
      expect(line()).toBe("下局庄家：Sam。");
      expect(host.textContent).not.toMatch(/闲家得 \d+ 分|升 \d 级|上台，不升级/);
      act(() => setLanguageChoice("en"));
      expect(line()).toBe("Next banker: Sam.");
    });
  }

  it("no level change: the winners' lane shows one level, no sentence", () => {
    setLanguageChoice("zh-Hans");
    render(<RoundEndModal state={table(0, { trump: trump2 })}
                          result={result({ attacker_points: 90, winner_team: 1, level_change: 0, next_banker: 1 })} />);
    expect(lanes()).toEqual(["我方：2", "对方：2"]);
    expect(line()).toBe("下局庄家：Robin。");
  });

  it("a won game: the crown past A, the games score, Next game, and no restart line", () => {
    setLanguageChoice("zh-Hans");
    render(<RoundEndModal state={table(0, { trump: { suit: "S", rank: "A", declarer: null } })}
                          before={["A", "Q"]}
                          result={result({ attacker_points: 35, point_scored: true, games_won: [1, 0], next_banker: 0 })} />);
    expect(title()).toBe("我和 Sam 赢了这一盘");
    expect(lanes()).toEqual(["我方：A，赢了这一盘", "对方：Q"]);
    expect(line()).toBe("下局庄家：我。");
    expect(host.querySelector(".result-games")!.textContent).toBe("盘数：我方 1 · 对方 0");
    expect(host.textContent).not.toContain("重新打起");
    expect([...host.querySelectorAll(".round-end-actions button")].map((b) => b.textContent)).toEqual(["下一盘", "离开牌桌"]);
  });

  it("the rating rides on the status line in Chinese punctuation", () => {
    setLanguageChoice("zh-Hans");
    render(<RoundEndModal state={table(0, { matched: true })}
                          result={result({ attacker_points: 45, new_levels: ["3", "2"] as [string, string], rating: { rating: 1712, delta: -4 } })} />);
    expect(line()).toBe("下局庄家：Sam · 积分 1712（−4）。");
  });
});

describe("the round end in Chinese", () => {
  beforeEach(() => setLanguageChoice("zh-Hans"));

  it("titles the round with one sentence per outcome, bots by their Chinese name", () => {
    render(<RoundEndModal state={table(0)} result={result({ winner_team: 0 })} />);
    expect(title()).toBe("我和 Sam 赢了这一局");
    render(<RoundEndModal state={table(0)} result={result({ winner_team: 1 })} />);
    expect(title()).toBe("我和 Sam 输了这一局");
    // a viewer seated on neither team hears the winners by name
    render(<RoundEndModal state={table(0, { you: 9 })} result={result({ winner_team: 1 })} />);
    expect(title()).toBe("Robin 和 机器人 3 赢了这一局");
    // a team of one: the viewer alone
    const alone = table(0);
    alone.players = alone.players.filter((p) => p.seat !== 2);
    render(<RoundEndModal state={alone} result={result({ winner_team: 0 })} />);
    expect(title()).toBe("我赢了这一局");
    act(() => setLanguageChoice("en"));
    expect(title()).toBe("You win the round");
  });

  it("Details: the kitty, the attackers' last trick as 抠底, the last trick as 最后一轮", () => {
    const kitty = ["S5", "C3", "D10", "C4", "C6", "C7", "C8", "D9"];
    const last = { leader: 1, winner: 3, points: 10, plays: [
      { seat: 1, cards: ["H9"] }, { seat: 2, cards: ["H3"] }, { seat: 3, cards: ["HA"] }, { seat: 0, cards: ["HK"] },
    ] };
    render(<RoundEndModal state={table(0, { last_trick: last })}
                          result={result({ attacker_points: 115, kitty_points: 30, kitty_cards: kitty, winner_team: 1 })} />);
    expect(host.querySelector(".round-end-view-btn .on")!.textContent).toBe("详情");
    act(() => host.querySelector<HTMLButtonElement>(".round-end-view-btn")!.click());
    expect(host.querySelector(".round-end-view-btn .on")!.textContent).toBe("级数");
    expect(host.querySelector(".round-end-kitty-label")!.textContent).toBe("底牌 · 15 分");
    expect(host.querySelector(".kitty-bonus")!.textContent).toBe("闲家抠底：15 × 2 × 1 张 = +30");
    expect(host.querySelector(".round-end-trick-label")!.textContent).toBe("最后一轮 · 机器人 3，10 分");
    expect([...host.querySelectorAll(".round-end-play-who")].map((e) => e.textContent)).toEqual(["Robin", "Sam", "机器人 3", "我"]);
  });

  it("Next round and Leave game, then the leave sheet", () => {
    render(<RoundEndModal state={table(0)} result={result({})} />);
    const buttons = [...host.querySelectorAll<HTMLButtonElement>(".round-end-actions button")];
    expect(buttons.map((b) => b.textContent)).toEqual(["下一局", "离开牌桌"]);
    act(() => buttons[1].click());
    const sheet = [...document.querySelectorAll("dialog")].find((d) => d.querySelector("h2")?.textContent === "离开这盘？")!;
    expect(sheet.querySelector("p")!.textContent).toBe("这一局的结果会保留。");
    expect([...sheet.querySelectorAll("button")].map((b) => b.textContent)).toEqual(["留下", "离开"]);
  });

  it("waits for the others in Chinese", () => {
    render(<RoundEndModal state={table(0, { ready: [0] })} result={result({})} />);
    expect(host.querySelector(".round-end-actions .btn.primary")!.textContent).toBe("等其他人…");
  });
});

describe("the leave sheet's lines in Chinese", () => {
  beforeEach(() => setLanguageChoice("zh-Hans"));

  it("one title and one line per place", () => {
    expect(leaveCopy({ kind: "queue", others: ["Alice"] })).toEqual({ title: "离开牌桌？", line: "Alice 留在牌桌。" });
    expect(leaveCopy({ kind: "duo", partner: "Jerry", opener: true })).toEqual({ title: "退出组队？", line: "Jerry 留着牌桌和房间码。" });
    expect(leaveCopy({ kind: "duo", partner: "Jerry", opener: false }).line).toBe("Jerry 留着牌桌。");
    expect(leaveCopy({ kind: "game", ranked: true })).toEqual({ title: "离开这盘？", line: "这一局最多算平局。" });
    expect(leaveCopy({ kind: "game", ranked: true }, true).line).toBe("打完这一局再走，不然要等 1 分钟才能再玩。");
    expect(leaveCopy({ kind: "game", ranked: false, practice: true }).line).toBe("这盘离线游戏会结束。");
    expect(leaveCopy({ kind: "game", ranked: false }).line).toBeNull();
  });
});

describe("the connection pill in Chinese", () => {
  beforeEach(() => setLanguageChoice("zh-Hans"));

  it("reconnecting, then the seat-held pill", () => {
    render(<ConnectionPill status="closed" inRoom inGame />);
    expect(host.querySelector(".reconnect-text")!.textContent).toBe("重连中…");
    render(<SeatHeldPill onBack={() => {}} />);
    expect(host.querySelector(".reconnect-text")!.textContent).toBe("机器人在替你打");
    expect(host.querySelector("button")!.textContent).toBe("我回来了");
  });

  it("the full screen after a minute", () => {
    vi.useFakeTimers();
    try {
      render(<ConnectionPill status="closed" inRoom inGame />);
      act(() => { vi.advanceTimersByTime(61_000); });
      const dialog = document.querySelector(".conn-lost")!;
      expect(dialog.querySelector("h1")!.textContent).toBe("没有网络连接");
      expect(dialog.querySelector(".conn-lost-body")!.textContent).toBe("机器人在替你打。");
      expect([...dialog.querySelectorAll("button")].map((b) => b.textContent)).toEqual(["重试", "和机器人离线玩"]);
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("the round end in Traditional Chinese", () => {
  beforeEach(() => setLanguageChoice("zh-Hant"));

  it("titles the round, bots as 機器人, and offers Next round and Leave", () => {
    render(<RoundEndModal state={table(0)} result={result({ winner_team: 0 })} />);
    expect(title()).toBe("我和 Sam 贏了這一局");
    render(<RoundEndModal state={table(0, { you: 9 })} result={result({ winner_team: 1 })} />);
    expect(title()).toBe("Robin 和 機器人 3 贏了這一局");
    render(<RoundEndModal state={table(0)} result={result({})} />);
    const buttons = [...host.querySelectorAll<HTMLButtonElement>(".round-end-actions button")];
    expect(buttons.map((b) => b.textContent)).toEqual(["下一局", "離開牌桌"]);
    act(() => buttons[1].click());
    const sheet = [...document.querySelectorAll("dialog")].find((d) => d.querySelector("h2")?.textContent === "離開這盤？")!;
    expect(sheet.querySelector("p")!.textContent).toBe("這一局的結果會保留。");
    expect([...sheet.querySelectorAll("button")].map((b) => b.textContent)).toEqual(["留下", "離開"]);
  });

  it("Details: the kitty, the attackers' 摳底 and the last trick", () => {
    const kitty = ["S5", "C3", "D10", "C4", "C6", "C7", "C8", "D9"];
    const last = { leader: 1, winner: 3, points: 10, plays: [
      { seat: 1, cards: ["H9"] }, { seat: 2, cards: ["H3"] }, { seat: 3, cards: ["HA"] }, { seat: 0, cards: ["HK"] },
    ] };
    render(<RoundEndModal state={table(0, { last_trick: last })}
                          result={result({ attacker_points: 115, kitty_points: 30, kitty_cards: kitty, winner_team: 1 })} />);
    expect(host.querySelector(".round-end-view-btn .on")!.textContent).toBe("詳情");
    act(() => host.querySelector<HTMLButtonElement>(".round-end-view-btn")!.click());
    expect(host.querySelector(".round-end-view-btn .on")!.textContent).toBe("級數");
    expect(host.querySelector(".round-end-kitty-label")!.textContent).toBe("底牌 · 15 分");
    expect(host.querySelector(".kitty-bonus")!.textContent).toBe("閒家摳底：15 × 2 × 1 張 = +30");
    expect(host.querySelector(".round-end-trick-label")!.textContent).toBe("最後一輪 · 機器人 3，10 分");
    expect([...host.querySelectorAll(".round-end-play-who")].map((e) => e.textContent)).toEqual(["Robin", "Sam", "機器人 3", "我"]);
  });
});
