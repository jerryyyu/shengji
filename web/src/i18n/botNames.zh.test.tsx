// Bot seats read "机器人 N" in Chinese wherever a seat's name shows: the seat
// chips, the declaration tag, the team lines, Last trick, the chat's names and
// system lines, the round end and a nearby table's seats; a person's name
// stays as typed, even one shaped like a bot's. In English they read "Bot N".
import { act } from "react";
import type { ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import type { ChatMsg, GameState, RoundResult, StatePlayer } from "../protocol";

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
vi.mock("../components/offlineGame", () => ({ offlineGame: { startFromPlay: () => {} }, offlineOffered: () => true }));

const { default: Table } = await import("../components/Table");
const { default: LastTrickPanel } = await import("../components/LastTrickPanel");
const { default: ChatPanel } = await import("../components/ChatPanel");
const { default: RoundEndModal } = await import("../components/RoundEndModal");
const { formatSystemLine, formatTableMessage } = await import("../messageCopy");
const { nextBankerText, teamMembers } = await import("../tableCopy");
const { fromNearbyJoin } = await import("../queue/nearbyModel");
const { displayName, setLanguageChoice } = await import(".");

/** You (Mei) at seat 0, bots at 1 and 2, a person, Sam, at 3. */
function player(seat: number, name: string, isBot: boolean): StatePlayer {
  return { seat, name, is_bot: isBot, connected: true, team: (seat % 2) as 0 | 1, cards_left: 25,
    is_banker: false, takeover_in: null, controller: isBot ? "bot" : "human", reserved_for: null, reserved_secs: null };
}
const PLAYERS = [player(0, "Mei", false), player(1, "Bot 1", true), player(2, "Bot 2", true), player(3, "Sam", false)];
const ALL_BOTS = [player(0, "Mei", false), player(1, "Bot 1", true), player(2, "Bot 2", true), player(3, "Bot 3", true)];

function state(over: Partial<GameState> = {}): GameState {
  return {
    type: "state", room: "T", you: 0, phase: "play", players: PLAYERS,
    hand: [], levels: ["2", "2"], games_won: [0, 0], banker: 1, trump: null, turn: 1,
    declare_options: [], current_declaration: null, passed: [], trick: null, last_trick: null,
    attacker_points: 0, kitty_count: 8, round_result: null, message: null, notice: null, ...over,
  };
}

const RESULT: RoundResult = {
  attacker_points: 20, kitty_points: 0, kitty_cards: [], winner_team: 0, level_change: 2,
  next_banker: 2, new_levels: ["4", "2"], games_won: [0, 0], point_scored: false, game_over: false,
};

beforeAll(() => {
  class SilentAudioContext { state = "running"; currentTime = 0; async resume() {} }
  (window as unknown as { AudioContext: unknown }).AudioContext = SilentAudioContext;
});

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
beforeEach(() => {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  Object.defineProperty(Element.prototype, "scrollIntoView", { configurable: true, value: vi.fn() });
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", { configurable: true,
    value: function (this: HTMLDialogElement) { this.setAttribute("open", ""); } });
  Object.defineProperty(HTMLDialogElement.prototype, "close", { configurable: true,
    value: function (this: HTMLDialogElement) { this.removeAttribute("open"); } });
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  setLanguageChoice("system");
  delete (Element.prototype as { scrollIntoView?: unknown }).scrollIntoView;
});
const render = (node: ReactNode) => act(() => root.render(node));
const seatNames = () => [...host.querySelectorAll(".opponent .opp-name-text")].map((e) => e.textContent);

describe("bot names in zh-Hans", () => {
  beforeEach(() => setLanguageChoice("zh-Hans"));

  it("the seat chips name the bots 机器人 N and keep a person's name", () => {
    render(<Table state={state({ players: ALL_BOTS })} />);
    expect(seatNames().sort()).toEqual(["机器人 1", "机器人 2", "机器人 3"]);
    render(<Table state={state()} />);
    expect(seatNames().sort()).toEqual(["Sam", "机器人 1", "机器人 2"]);
    expect(host.textContent).not.toMatch(/Bot \d/);
  });

  it("the declaration, banker and team lines", () => {
    expect(formatTableMessage("Seat 2 declared H2 (pair)", PLAYERS, 0)).toBe("机器人 2 亮一对♥2");
    render(<Table state={state({ players: PLAYERS.map((p) => ({ ...p, is_banker: p.seat === 1 })) })} />);
    expect(host.querySelector(".opponent .banker-crown")?.getAttribute("aria-label")).toBe("机器人 1，庄家");
    const s = state();
    expect(teamMembers(0, s)).toBe("我和机器人 2");
    expect(teamMembers(1, s)).toBe("机器人 1 和 Sam");
    expect(nextBankerText(s, { next_banker: 2 } as never)).toBe("下局庄家：机器人 2");
  });

  it("Last trick names who won and who played", () => {
    render(<LastTrickPanel state={state()} trick={{ leader: 1, winner: 2, points: 10,
      plays: [{ seat: 1, cards: ["S5"] }, { seat: 2, cards: ["SA"] }, { seat: 3, cards: ["S6"] }, { seat: 0, cards: ["S7"] }] }}
      onClose={() => {}} />);
    expect(host.querySelector(".last-trick-sum")?.textContent).toBe("机器人 2 赢 · 10 分");
    expect(host.textContent).not.toMatch(/Bot \d/);
    expect(host.textContent).toContain("Sam");
  });

  it("the chat's names and system lines", () => {
    const line = (id: number, seat: number, name: string, text: string): ChatMsg =>
      ({ type: "chat", id, room: "T", seat, name, text, t: 0 });
    render(<ChatPanel messages={[
      line(1, -1, "", "Mei took Bot 2's seat"),
      line(2, -1, "", "Sam left"),
      line(3, -1, "", "bot is playing for Sam (disconnected)"),
      line(4, 3, "Sam", "hi"),
    ]} you={0} open onClose={() => {}} />);
    const system = [...host.querySelectorAll(".chat-msg.system")].map((e) => e.textContent?.trim());
    expect(system).toEqual(["Mei 坐了 机器人 2 的位置", "Sam 离开了", "Sam 掉线，机器人代打"]);
    expect(host.querySelector(".chat-name")?.textContent).toBe("Sam");
    expect(formatSystemLine("Bot 3 joined")).toBe("机器人 3 加入了");
    expect(formatSystemLine("something new")).toBe("something new");
  });

  it("the round end names the bot partner and the next banker", () => {
    render(<RoundEndModal state={state({ phase: "round_end", players: ALL_BOTS, banker: 1,
      last_trick: { leader: 1, winner: 2, points: 10,
        plays: [{ seat: 1, cards: ["S5"] }, { seat: 2, cards: ["SA"] }, { seat: 3, cards: ["S6"] }, { seat: 0, cards: ["S7"] }] } })}
      result={RESULT} />);
    expect(host.textContent).toContain("机器人 2");
    expect(host.textContent).not.toMatch(/Bot \d/);
  });

  it("a nearby table's seats", () => {
    const model = fromNearbyJoin({ step: "panel", code: "ABCD", seat: 0, held: null, linked: false,
      peek: { type: "room_seats", room: "ABCD", in_game: true, seats: [
        { seat: 1, name: "Bot 1", is_bot: true, connected: true, team: 1, claimable: true, controller: "bot", reserved_secs: null },
        { seat: 2, name: "Lin", is_bot: false, connected: true, team: 0, claimable: false, controller: "human", reserved_secs: null },
      ] } } as never);
    expect(model.seats?.map((s) => s.name)).toEqual(["我", "机器人 1", "Lin", ""]);
  });

  it("a person who typed a bot-shaped name keeps it where the seat's flag is known", () => {
    expect(displayName("Bot 2", false)).toBe("Bot 2");
    expect(displayName("Bot 2", true)).toBe("机器人 2");
    expect(displayName("Bot 2")).toBe("机器人 2");
    expect(displayName("Botany")).toBe("Botany");
  });
});

describe("bot names in English", () => {
  beforeEach(() => setLanguageChoice("en"));

  it("the seat chips read Bot N", () => {
    render(<Table state={state({ players: ALL_BOTS })} />);
    expect(seatNames().sort()).toEqual(["Bot 1", "Bot 2", "Bot 3"]);
    expect(formatSystemLine("Mei took Bot 2's seat")).toBe("Mei took Bot 2's seat");
    expect(teamMembers(0, state())).toBe("You & Bot 2");
  });
});
