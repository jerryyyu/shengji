// Bot seats read "机器人 N" in Chinese wherever a seat's name shows: the seat
// chips, the declaration tag, the team lines, Last trick, the bot side of a
// chat system line, the round end, a nearby table's seats and a replay; a
// person's name stays as typed, even one shaped like a bot's (a chat line's
// sender is always a person). In English they read "Bot N".
import { act } from "react";
import type { ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import type { ChatMsg, GameState, RoundResult, StatePlayer, SystemEventKind } from "../protocol";

const link = vi.hoisted(() => ({ listeners: new Set<(m: unknown) => void>(), history: [] as unknown[] }));
vi.mock("../ws", () => ({
  conn: {
    status: "open",
    generation: 1,
    send: () => true,
    subscribe: (fn: (m: unknown) => void) => { link.listeners.add(fn); return () => link.listeners.delete(fn); },
    subscribeStatus: (fn: (s: string) => void) => { fn("open"); return () => {}; },
    chatHistory: () => link.history.slice(),
    reconnect: () => {},
  },
}));
vi.mock("../native", () => ({ haptic: () => {} }));
// the connection buffers a live line before telling subscribers, as ws.ts does
const serverSays = (m: ChatMsg) => act(() => {
  link.history.push(m);
  for (const fn of link.listeners) fn(m);
});
vi.mock("../components/offlineGame", () => ({ offlineGame: { startFromPlay: () => {} }, offlineOffered: () => true }));

const { default: Table } = await import("../components/Table");
const { default: LastTrickPanel } = await import("../components/LastTrickPanel");
const { default: ChatPanel } = await import("../components/ChatPanel");
const { default: RoundEndModal } = await import("../components/RoundEndModal");
const { formatSystemLine, formatTableMessage } = await import("../messageCopy");
const { nextBankerText, teamMembers } = await import("../tableCopy");
const { fromNearbyJoin } = await import("../queue/nearbyModel");
const { ReplayBoard } = await import("../components/ReplayView");
const { buildReplay } = await import("../replay/reducer");
const { displayName, setLanguageChoice } = await import(".");
import roundFixture from "../replay/round.fixture.json";
import type { RoundReplayDoc } from "../replay/reducer";

/** You (Mei) at seat 0, bots at 1 and 2, a person, Sam, at 3. */
function player(seat: number, name: string, isBot: boolean): StatePlayer {
  return { seat, name, is_bot: isBot, connected: true, team: (seat % 2) as 0 | 1, cards_left: 25,
    is_banker: false, takeover_in: null, controller: isBot ? "bot" : "human", reserved_for: null, reserved_secs: null };
}
const PLAYERS = [player(0, "Mei", false), player(1, "Bot 1", true), player(2, "Bot 2", true), player(3, "Sam", false)];
/** A guest who typed "Bot 2" at seat 3, beside a real bot at seat 1. */
const GUEST_BOT2 = [player(0, "Mei", false), player(1, "Bot 1", true), player(2, "Lin", false), player(3, "Bot 2", false)];
const chat = (id: number, seat: number, name: string, text: string, extra: Partial<ChatMsg> = {}): ChatMsg =>
  ({ type: "chat", id, room: "T", seat, name, text, t: 0, ...extra });
/** A seat claim as both servers post it: the text, and its participants. */
const tookSeat = (id: number, actor: string, target: string, isBot: boolean): ChatMsg =>
  chat(id, -1, "", `${actor} took ${target}'s seat`, { event: "took_seat", actor, target, target_is_bot: isBot });
const said = (id: number, event: SystemEventKind, actor: string, text: string): ChatMsg =>
  chat(id, -1, "", text, { event, actor });
const tookOver = (id: number, actor: string, target: string): ChatMsg =>
  chat(id, -1, "", `${actor} took over for ${target} (offline)`, { event: "took_over", actor, target, target_is_bot: false });

/** The fixture's round (Ana at seat 0, Bots 1-3), seat 2 made a guest who typed "Bot 2". */
function replay() {
  const doc = structuredClone(roundFixture) as unknown as RoundReplayDoc;
  const start = doc.events.find((e) => e.e === "round_start") as unknown as { players: { seat: number; is_bot: boolean }[] };
  start.players[2].is_bot = false;
  return buildReplay(doc);
}
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
  link.history = [];
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

  it("the chat's system lines name only a bot target as a bot", () => {
    render(<ChatPanel messages={[
      tookSeat(1, "Bot 2", "Bot 1", true),
      tookSeat(2, "Sam took Lee", "Bot 1", true),
      tookOver(3, "Sam took Lee", "Ann"),
      tookOver(4, "Ann", "Sam took Lee"),
      tookSeat(5, "Mei", "Sam took Lee", false),
    ]} you={0} open onClose={() => {}} />);
    const system = [...host.querySelectorAll(".chat-msg.system")].map((e) => e.textContent?.trim());
    expect(system).toEqual([
      "Bot 2 坐了 机器人 1 的位置",
      "Sam took Lee 坐了 机器人 1 的位置",
      "Sam took Lee 替掉线的 Ann 接手",
      "Ann 替掉线的 Sam took Lee 接手",
      "Mei 坐了 Sam took Lee 的位置",
    ]);
  });

  it("the one-person system lines, from their fields, keep the name verbatim", () => {
    render(<ChatPanel messages={[
      said(1, "joined", "Bot 2 joined", "Bot 2 joined joined"),
      said(2, "left", "Bot 2", "Bot 2 left"),
      said(3, "disconnected", "Sam left", "Sam left disconnected"),
      said(4, "reconnected", "Bot 1", "Bot 1 reconnected"),
      said(5, "reconnected_from_bot", "Mei", "Mei reconnected — taking over from the bot"),
      said(6, "bot_playing_for", "Bot 2", "bot is playing for Bot 2 (disconnected)"),
    ]} you={0} open onClose={() => {}} />);
    const system = [...host.querySelectorAll(".chat-msg.system")].map((e) => e.textContent?.trim());
    expect(system).toEqual(["Bot 2 joined 加入了", "Bot 2 离开了", "Sam left 掉线了", "Bot 1 回来了",
      "Mei 回来了，从机器人手里接回", "Bot 2 掉线，机器人代打"]);
  });

  it("a system line without its fields, from an older server, is shown as sent", () => {
    for (const text of ["Sam took Lee took Bot 1's seat", "Mei took over for Ann (offline)", "Bot 2 joined",
      "Sam left", "bot is playing for Sam (disconnected)", "something new"]) {
      expect(formatSystemLine(chat(1, -1, "", text))).toBe(text);
    }
    // a kind this client does not know falls back to the text too
    expect(formatSystemLine(chat(1, -1, "", "Sam waved", { event: "waved" as SystemEventKind, actor: "Sam" }))).toBe("Sam waved");
    // a seat claim missing its target is not guessed at
    expect(formatSystemLine(chat(1, -1, "", "Sam took Bot 1's seat", { event: "took_seat", actor: "Sam" }))).toBe("Sam took Bot 1's seat");
  });

  it("a guest's chat named Bot 2 keeps its name in the log and the bubble", () => {
    render(<ChatPanel messages={[chat(1, 3, "Bot 2", "hi")]} you={0} open onClose={() => {}} />);
    expect(host.querySelector(".chat-name")?.textContent).toBe("Bot 2");
    render(<Table state={state({ players: GUEST_BOT2 })} />);
    serverSays(chat(2, 3, "Bot 2", "nice"));
    expect(host.querySelector(".chat-bubble-who")?.textContent).toBe("Bot 2：");
    expect(seatNames().sort()).toEqual(["Bot 2", "Lin", "机器人 1"]);
  });

  it("a replay names its bots 机器人 N and keeps a guest's bot-shaped name", () => {
    render(<ReplayBoard replay={replay()} />);
    const chips = () => [...host.querySelectorAll(".replay-seat-name")].map((e) => e.textContent);
    expect(chips()).toEqual(["Ana (you)", "机器人 1", "Bot 2", "机器人 3"]);
    const next = host.querySelector<HTMLButtonElement>('button[aria-label="Next play"]')!;
    const caption = () => host.querySelector(".replay-caption")?.textContent ?? "";
    const seen: string[] = [];
    for (let i = 0; i < 8; i++) { act(() => next.click()); seen.push(caption()); }
    expect(seen.some((c) => /^Trick \d+: 机器人 [13] /.test(c))).toBe(true);
    expect(seen.some((c) => /^Trick \d+: Bot 2 /.test(c))).toBe(true);
    expect(seen.join(" ")).not.toMatch(/Bot [13]/);
    const last = host.querySelector<HTMLButtonElement>('button[aria-label="Next trick"]')!;
    for (let i = 0; i < 40 && !last.disabled; i++) act(() => last.click());
    const show = [...host.querySelectorAll("button")].find((b) => b.textContent === "Show other hands")!;
    act(() => show.click());
    expect([...host.querySelectorAll(".replay-mini-label")].map((e) => e.textContent).filter((n) => n !== "Kitty"))
      .toEqual(["机器人 1", "Bot 2", "机器人 3"]);
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
    expect(formatSystemLine(tookSeat(1, "Sam took Lee", "Bot 1", true))).toBe("Sam took Lee took Bot 1's seat");
    expect(formatSystemLine(tookOver(2, "Ann", "Sam took Lee"))).toBe("Ann took over for Sam took Lee (offline)");
    expect(formatSystemLine(chat(3, -1, "", "Sam took Lee took Bot 1's seat"))).toBe("Sam took Lee took Bot 1's seat");
    expect(formatSystemLine(said(4, "joined", "Bot 2 joined", "Bot 2 joined joined"))).toBe("Bot 2 joined joined");
    expect(formatSystemLine(said(5, "bot_playing_for", "Bot 2", "bot is playing for Bot 2 (disconnected)")))
      .toBe("bot is playing for Bot 2 (disconnected)");
    expect(teamMembers(0, state())).toBe("You & Bot 2");
  });

  it("a guest's chat named Bot 2 and a replay", () => {
    render(<ChatPanel messages={[chat(1, 3, "Bot 2", "hi")]} you={0} open onClose={() => {}} />);
    expect(host.querySelector(".chat-name")?.textContent).toBe("Bot 2");
    render(<Table state={state({ players: GUEST_BOT2 })} />);
    serverSays(chat(2, 3, "Bot 2", "nice"));
    expect(host.querySelector(".chat-bubble-who")?.textContent).toBe("Bot 2: ");
    render(<ReplayBoard replay={replay()} />);
    expect([...host.querySelectorAll(".replay-seat-name")].map((e) => e.textContent))
      .toEqual(["Ana (you)", "Bot 1", "Bot 2", "Bot 3"]);
  });
});
