// The table panel in Simplified Chinese: your own table, a shared table, a
// code's Join panel and the offline table draw their words from the zh table,
// and the queue's notices are said in zh.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { setLanguageChoice, t } from ".";
import TablePanel, { JoinCodePanel, OfflinePanel, TableAnnouncer } from "../queue/TablePanel";
import { movedNote } from "../queue/store";
import type { QueueView } from "../queue/store";
import { tableFrameFor } from "../queue/testFrames";
import { firstJoinerText, presenceParts } from "../queue/tableText";
import { ERROR_ROUTES } from "../errorCodes";
import type { CodeJoin } from "../codeJoin";
import type { RoomSeats } from "../protocol";

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  setLanguageChoice("zh-Hans");
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  setLanguageChoice("system");
});

const draw = (node: React.ReactNode) => act(() => root.render(node));
const text = () => host.textContent ?? "";
const labels = () => [...host.querySelectorAll("[aria-label]")].map((e) => e.getAttribute("aria-label"));
const buttons = () => [...host.querySelectorAll("button")].map((b) => b.textContent);

const nowSecs = () => Date.now() / 1000;

function view(qs: Record<string, unknown>, over: Partial<QueueView> = {}): QueueView {
  const f = tableFrameFor(qs);
  return {
    count: 1, queued: true, since: Date.now(), waitPlayers: false, front: false, leader: true, partyId: null,
    pending: null, frame: f, offer: null, openTables: 0, botsPaused: false, cooldownUntil: null,
    cooldownTold: false, elsewhere: false, party: null, note: null, presence: null, panelSeq: 1,
    stillHereUntil: null, inGame: null, playMode: "casual", queueMode: "casual", tableChat: [], duo: false,
    duoReady: null, ...over,
  };
}

const own = () => ({ type: "queue_state", queued: true, mode: "casual", code: "4N5Z", opener: true,
                     allow_joiners: true, start_level: "5", bot_level: "advanced", bots_at: null });
const seat = (name: string, over: Record<string, unknown> = {}) => ({
  name, you: false, ready: false, reconnecting: false, since: nowSecs() - 30, sit: `sit-${name}`, pair: false,
  leader: false, ...over,
});
const shared = () => ({
  ...own(),
  table: { id: "t1", code: "4N5Z", opener: 0, you: 0, timer: null, ready: 1, of: 2, you_ready: false,
           seats: [seat("Jerry", { you: true, leader: true }), seat("Alice", { ready: true }), null, null],
           waiting_for: [] },
});

describe("the table panel in zh-Hans", () => {
  it("draws your own table: title, team labels, seats, code, settings, switches and buttons", () => {
    draw(<TablePanel q={view(own())} guarded={false} />);
    expect(host.querySelector(".tp-title")?.textContent).toBe("我的牌桌");
    expect(text()).toContain("我方");
    expect(text()).toContain("对方");
    expect(text()).toContain("牌桌设置");
    expect(text()).toContain("打 5 · 高级");
    expect(text()).toContain("聊天");
    expect(text()).toContain("邀请");
    expect(buttons()).toEqual(expect.arrayContaining(["机器人补位开始", "离开"]));
    expect(labels()).toEqual(expect.arrayContaining([
      "我，我方", "空位，我方", "空位，对方", "邀请，房间码 4 N 5 Z", "牌桌设置，打 5，高级", "聊天",
    ]));
    expect(text()).not.toMatch(/[A-Za-z]{3,}/);
  });

  it("opens the table settings with zh rows", () => {
    draw(<TablePanel q={view(own())} guarded={false} />);
    act(() => (host.querySelector(".tp-settings") as HTMLButtonElement).click());
    expect(text()).toContain("从几打起");
    expect(text()).toContain("机器人");
    expect(text()).toContain("允许中途加入");
    // Wait for people folds into the settings with the other switches
    expect(text()).toContain("等真人");
    const options = [...host.querySelectorAll("option")].map((o) => o.textContent);
    expect(options).toEqual(expect.arrayContaining(["标准", "高级"]));
  });

  it("draws a shared table's ready line, title, the owner's Start and a joiner's Ready", () => {
    draw(<TablePanel q={view(shared())} guarded={false} />);
    expect(host.querySelector(".tp-title")?.textContent).toBe("我和 Alice");
    expect(host.querySelector(".tp-line")?.textContent).toBe("已准备 1/1");
    expect(buttons()).toContain("机器人补位开始");
    expect(labels()).toEqual(expect.arrayContaining(["Alice，已准备，对方。换座", "空位，对方。换到这里"]));
    expect(host.querySelectorAll(".tp-line, .tp-led, .tp-hint")).toHaveLength(1);
    const joiner = { ...shared(), opener: false,
                     table: { ...shared().table, you: 1, you_ready: false,
                              seats: [seat("Jerry", { leader: true }), seat("Alice", { you: true }), null, null] } };
    draw(<TablePanel q={view(joiner)} guarded={false} />);
    expect(buttons()).toContain("准备");
  });

  it("announces your own table in zh", () => {
    draw(<TableAnnouncer q={view(own())} />);
    expect(host.querySelector("[role='status']")?.textContent).toBe("我的牌桌，正在等人。");
  });

  it("draws a code's Join panel as the seat picker", () => {
    const peek: RoomSeats = {
      type: "room_seats", room: "WXYZ", in_game: true,
      seats: [
        { seat: 0, name: "Mei", is_bot: false, connected: true, team: 0, claimable: false, controller: "human", reserved_secs: null },
        { seat: 1, name: "Bot 1", is_bot: true, connected: true, team: 1, claimable: true, controller: "bot", reserved_secs: null },
      ],
    } as RoomSeats;
    const join: CodeJoin = { code: "WXYZ", from: "play", step: "panel", peek, full: false, seat: 1 };
    draw(<JoinCodePanel join={join} busy={false} onJoin={() => {}} onCancel={() => {}} onPick={() => {}} />);
    expect(host.querySelector(".tp-title")?.textContent).toBe("加入 Mei");
    expect(buttons()).toEqual(expect.arrayContaining(["加入", "暂不"]));
    expect(labels()).toEqual(expect.arrayContaining(["我，我方", "Mei，对方"]));
  });

  it("draws the offline table", () => {
    draw(<OfflinePanel ready starting={false} bots="standard" onBots={() => {}} onStart={() => {}} onLeave={() => {}} />);
    expect(host.querySelector(".tp-tag")?.textContent).toBe("离线模式");
    expect(host.querySelector(".tp-title")?.textContent).toBe("我和 3 个机器人");
    expect(text()).toContain("机器人 1");
    expect(labels()).toEqual(expect.arrayContaining(["机器人 2，我方", "机器人 1，对方", "聊天要联网"]));
    expect(buttons()).toEqual(expect.arrayContaining(["开始", "离开"]));
  });

  it("says the queue's notices in zh", () => {
    expect(movedNote({ type: "table_moved", name: "Alice", seat: 1, by: "Sam", you: false, your_team: true,
                       team_changed: true } as Parameters<typeof movedNote>[0])).toBe("Sam 把 Alice 换到了你这队。");
    expect(ERROR_ROUTES.seat_taken.text.map((k) => t(k))).toEqual(["这个位置刚被人坐了。", "换一个吧。"]);
    expect(firstJoinerText({ name: "Li", move_secs: 30, round_end: false }))
      .toBe("Li 加入了牌桌。现在出牌限时，每步 30 秒。");
    expect(presenceParts(null).map((p) => p.text).join("")).toBe("现在没人在玩");
  });
});
