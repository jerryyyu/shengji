// Mute and report on another player's seat: a long press opens the options,
// Mute hides that seat's chat lines for this viewer, Report sends the seat
// and a reason, and a bot's seat offers neither.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeAll, beforeEach, expect, it, vi } from "vitest";
import type { ChatMsg, GameState, StatePlayer } from "../protocol";

vi.mock("../native", () => ({ haptic: () => {} }));
const sent = vi.hoisted(() => [] as unknown[]);
vi.mock("../ws", () => ({
  conn: {
    status: "open",
    generation: 1,
    send: (m: unknown) => { sent.push(m); return true; },
    subscribe: () => () => {},
    subscribeStatus: (fn: (s: string) => void) => { fn("open"); return () => {}; },
    chatHistory: () => [],
  },
}));

const { default: Table } = await import("./Table");
const { default: ChatPanel } = await import("./ChatPanel");
const { clearMutes, isMuted } = await import("../chatMute");

function player(seat: number, over: Partial<StatePlayer> = {}): StatePlayer {
  return { seat, name: ["You", "Bea", "Bot 2", "Cy"][seat], is_bot: seat === 2, connected: true,
    team: (seat % 2) as 0 | 1, cards_left: 25, is_banker: false, takeover_in: null,
    controller: seat === 2 ? "bot" : "human", reserved_for: null, reserved_secs: null, ...over };
}

function state(): GameState {
  return {
    type: "state", room: "ROOM1", you: 0, phase: "play", players: [0, 1, 2, 3].map((s) => player(s)),
    hand: [], levels: ["2", "2"], games_won: [0, 0], banker: 1, trump: null, turn: 1,
    declare_options: [], current_declaration: null, passed: [], trick: null, last_trick: null,
    attacker_points: 0, kitty_count: 8, round_result: null, message: null, notice: null,
  };
}

const line = (id: number, seat: number, text: string): ChatMsg => ({
  type: "chat", id, room: "ROOM1", seat, name: ["You", "Bea", "Bot 2", "Cy"][seat] ?? "", text, t: id,
});

beforeAll(() => {
  class SilentAudioContext { state = "running"; currentTime = 0; async resume() {} }
  (window as unknown as { AudioContext: unknown }).AudioContext = SilentAudioContext;
  Object.defineProperty(Element.prototype, "scrollIntoView", { configurable: true, value: () => {} });
});

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
beforeEach(() => {
  sent.length = 0;
  clearMutes();
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.useRealTimers();
});

const seatOf = (name: string) =>
  [...host.querySelectorAll<HTMLElement>(".opponent")].find((el) => el.querySelector(".opp-name-text")?.textContent === name)!;
const dialog = () => document.querySelector<HTMLElement>(".opp-actions");
const rowButton = (text: string) =>
  [...document.querySelectorAll<HTMLButtonElement>(".opp-actions button")].find((b) => b.textContent === text);

function longPress(el: HTMLElement) {
  vi.useFakeTimers();
  act(() => el.dispatchEvent(new Event("pointerdown", { bubbles: true })));
  act(() => vi.advanceTimersByTime(450));
  act(() => el.dispatchEvent(new Event("pointerup", { bubbles: true })));
  vi.useRealTimers();
}

it("a long press on a person's seat offers Mute chat and Report player", () => {
  act(() => root.render(<Table state={state()} />));
  longPress(seatOf("Bea"));
  expect(dialog()?.getAttribute("aria-label")).toBe("Bea: player options");
  expect(rowButton("Mute chat")).toBeDefined();
  expect(rowButton("Report player")).toBeDefined();
  act(() => rowButton("Cancel")!.click());
  expect(dialog()).toBeNull();
  expect(sent).toEqual([]);
});

it("a bot's seat offers neither", () => {
  act(() => root.render(<Table state={state()} />));
  longPress(seatOf("Bot 2"));
  expect(dialog()).toBeNull();
  act(() => { seatOf("Bot 2").dispatchEvent(new MouseEvent("contextmenu", { bubbles: true, cancelable: true })); });
  expect(dialog()).toBeNull();
});

it("Report player asks why, then sends the seat and the reason", () => {
  act(() => root.render(<Table state={state()} />));
  act(() => { seatOf("Cy").dispatchEvent(new MouseEvent("contextmenu", { bubbles: true, cancelable: true })); });
  act(() => rowButton("Report player")!.click());
  expect(document.querySelector(".opp-actions-title")?.textContent).toBe("Report Cy");
  expect(rowButton("Abusive chat")).toBeDefined();
  act(() => rowButton("Spam")!.click());
  expect(sent).toEqual([{ type: "report_player", seat: 3, reason: "spam" }]);
  expect(dialog()).toBeNull();
});

it("Mute hides that seat's chat lines for this viewer, and Unmute brings them back", () => {
  const messages = [line(1, 1, "hello from Bea"), line(2, 3, "hi from Cy"), line(3, -1, "Bea joined")];
  act(() => root.render(
    <>
      <Table state={state()} />
      <ChatPanel messages={messages} you={0} open onClose={() => {}} />
    </>,
  ));
  const log = () => document.querySelector(".chat-log")!.textContent ?? "";
  expect(log()).toContain("hello from Bea");
  longPress(seatOf("Bea"));
  act(() => rowButton("Mute chat")!.click());
  expect(isMuted("ROOM1", 1)).toBe(true);
  expect(log()).not.toContain("hello from Bea");
  expect(log()).toContain("hi from Cy");
  expect(log()).toContain("Bea joined");
  // the mute belongs to this game's room only
  expect(isMuted("OTHER", 1)).toBe(false);
  expect(sent).toEqual([]);
  longPress(seatOf("Bea"));
  act(() => rowButton("Unmute chat")!.click());
  expect(log()).toContain("hello from Bea");
});
