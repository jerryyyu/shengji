import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeAll, beforeEach, expect, it, vi } from "vitest";
import type { ChatMsg, GameState, StatePlayer } from "../protocol";
import { clearMutes, setMuted } from "../chatMute";

vi.mock("../native", () => ({ haptic: () => {} }));
const link = vi.hoisted(() => ({
  listeners: new Set<(m: unknown) => void>(),
  history: [] as unknown[],
}));
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
// the connection buffers a live line before telling subscribers, as ws.ts does
const serverSays = (m: { type: string }) => act(() => {
  if (m.type === "chat") link.history.push(m);
  for (const fn of link.listeners) fn(m);
});

const { default: Table } = await import("./Table");
const { placeBubble } = await import("./ChatBubbles");

function player(seat: number): StatePlayer {
  return { seat, name: ["Me", "Ann", "Bo", "Cy"][seat], is_bot: false, connected: true,
    team: (seat % 2) as 0 | 1, cards_left: 25, is_banker: false, takeover_in: null,
    controller: "human", reserved_for: null, reserved_secs: null };
}
function state(): GameState {
  return {
    type: "state", room: "T", you: 0, phase: "play", players: [0, 1, 2, 3].map(player),
    hand: [], levels: ["2", "2"], games_won: [0, 0], banker: 1, trump: null, turn: 1,
    declare_options: [], current_declaration: null, passed: [], trick: null, last_trick: null,
    attacker_points: 0, kitty_count: 8, round_result: null, message: null, notice: null,
  };
}
const line = (id: number, seat: number, text: string): ChatMsg =>
  ({ type: "chat", id, room: "T", seat, name: seat < 0 ? "" : player(seat).name, text, t: 0 });

beforeAll(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  class SilentAudioContext { state = "running"; currentTime = 0; async resume() {} }
  (window as unknown as { AudioContext: unknown }).AudioContext = SilentAudioContext;
  Object.defineProperty(Element.prototype, "scrollIntoView", { configurable: true, value: () => {} });
});

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
beforeEach(() => {
  vi.useFakeTimers();
  link.history = [];
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
const render = () => act(() => root.render(<Table state={state()} />));
const bubbles = () => [...host.querySelectorAll<HTMLButtonElement>(".chat-bubble")];
const bubbleText = () => bubbles().map((b) => `${b.dataset.seat}:${b.textContent}`);
const later = (ms: number) => act(() => { vi.advanceTimersByTime(ms); });

it("shows a live line at its seat for five seconds, in a polite live region", () => {
  render();
  serverSays(line(1, 1, "nice lead"));
  expect(bubbleText()).toEqual(["1:Ann: nice lead"]);
  expect(host.querySelector(".chat-bubbles")!.getAttribute("aria-live")).toBe("polite");
  later(4900);
  expect(bubbles()).toHaveLength(1);
  later(100);
  expect(bubbles()).toHaveLength(0);
});

it("replaces a seat's bubble with its next line and restarts the clock", () => {
  render();
  serverSays(line(1, 1, "first"));
  later(3000);
  serverSays(line(2, 1, "second"));
  expect(bubbleText()).toEqual(["1:Ann: second"]);
  later(3000);
  expect(bubbleText()).toEqual(["1:Ann: second"]);
  later(2000);
  expect(bubbles()).toHaveLength(0);
});

it("shows several seats at once, your own line included", () => {
  render();
  serverSays(line(1, 1, "hi"));
  serverSays(line(2, 2, "hello"));
  serverSays(line(3, 0, "hey"));
  expect(bubbleText()).toEqual(["1:Ann: hi", "2:Bo: hello", "0:You: hey"]);
  expect(bubbles()[2].classList.contains("mine")).toBe(true);
});

it("pops nothing for a muted seat, a system line or replayed history", () => {
  link.history = [line(1, 1, "buffered before the table")];
  render();
  expect(bubbles()).toHaveLength(0);
  setMuted("T", 2, true);
  serverSays(line(2, 2, "muted"));
  serverSays(line(3, -1, "Cy joined"));
  expect(bubbles()).toHaveLength(0);
  // a reconnect: the snapshot, then a live echo of a line it already holds
  serverSays({ type: "chat_history", room: "T", messages: [line(1, 1, "old"), line(4, 3, "older")] });
  serverSays(line(4, 3, "older"));
  expect(bubbles()).toHaveLength(0);
  serverSays(line(5, 3, "fresh"));
  expect(bubbleText()).toEqual(["3:Cy: fresh"]);
});

it("shows none while the panel is open, clears them when it opens, and a tap opens it", () => {
  render();
  serverSays(line(1, 1, "tap me"));
  act(() => bubbles()[0].click());
  const panel = host.querySelector(".chat-panel")!;
  expect(panel.getAttribute("aria-hidden")).toBeNull();
  expect(bubbles()).toHaveLength(0);
  serverSays(line(2, 2, "while open"));
  expect(bubbles()).toHaveLength(0);
  // the line still reaches the panel
  expect(panel.textContent).toContain("tap me");
});

it("keeps counting a bubbled line as unread until the panel opens", () => {
  render();
  serverSays(line(1, 1, "count me"));
  expect(host.querySelector(".chat-badge")!.textContent).toBe("1");
});

it("places a bubble beside its seat, never over a card", () => {
  const bounds = { x: 0, y: 0, w: 800, h: 400 };
  const seat = { x: 200, y: 50, w: 60, h: 20 };
  const size = { w: 100, h: 24 };
  // open felt to the right: toward the table
  expect(placeBubble(seat, size, ["right", "left"], bounds, [[]])).toMatchObject({ side: "right", x: 268 });
  // a card there: the outer side instead
  const card = { x: 280, y: 40, w: 40, h: 60 };
  expect(placeBubble(seat, size, ["right", "left"], bounds, [[card]])).toMatchObject({ side: "left", x: 92 });
  // nowhere clear of cards: no bubble
  const wall = { x: 0, y: 0, w: 800, h: 400 };
  expect(placeBubble(seat, size, ["right", "left"], bounds, [[wall]])).toBeNull();
});
