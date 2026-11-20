// Leaving while the cards are dealt. The table takes a state frame about
// every 200 ms then, and iOS WebKit drops the click of a tap while the page
// changes under it, so these taps arrive as touchstart and touchend alone:
// the menu, the leave sheet and its Leave answer them without a click.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import type { GameState, StatePlayer } from "../protocol";
import { conn } from "../ws";
import Table from "./Table";

function player(seat: number): StatePlayer {
  return {
    seat, name: seat === 0 ? "You" : `Bot ${seat}`, is_bot: seat !== 0, connected: true,
    team: (seat % 2) as 0 | 1, cards_left: 0, is_banker: false, takeover_in: null,
    controller: seat === 0 ? "human" : "bot", reserved_for: null, reserved_secs: null,
  } as StatePlayer;
}

const CODES = ["S3", "S5", "S9", "SK", "SA", "H3", "H4", "H10", "HK", "HA", "D6", "D7", "D10", "DA", "C5", "C8", "CQ", "CA", "BJ", "H2"];

/** The deal's frame once `n` cards are in your hand. */
function deal(n: number): GameState {
  return {
    type: "state", room: "4N5Z", you: 0, phase: "deal", matched: false, opener: 0, allow_joiners: true,
    players: [0, 1, 2, 3].map(player), hand: CODES.slice(0, n).map((code, id) => ({ id, code })),
    levels: ["2", "2"], games_won: [0, 0], banker: null, trump: null, turn: null,
    declare_options: n > 4 ? [[0]] : [], current_declaration: null, passed: [],
    trick: null, last_trick: null, attacker_points: 0, kitty_count: 8,
    round_result: null, message: null, notice: null,
  } as unknown as GameState;
}

/** A tap as iOS WebKit delivers it mid-deal: the touch, and no click. */
function touchOnly(el: Element) {
  const touch = { identifier: 1, clientX: 10, clientY: 10, target: el };
  const fire = (type: string, touches: unknown[]) => {
    const e = new Event(type, { bubbles: true, cancelable: true });
    Object.defineProperty(e, "touches", { value: touches });
    Object.defineProperty(e, "changedTouches", { value: [touch] });
    Object.defineProperty(e, "targetTouches", { value: touches });
    el.dispatchEvent(e);
    return e;
  };
  let end: Event | null = null;
  act(() => {
    fire("touchstart", [touch]);
    end = fire("touchend", []);
  });
  return end!;
}

beforeAll(() => {
  class SilentAudioContext { state = "running"; currentTime = 0; async resume() {} }
  (window as unknown as { AudioContext: unknown }).AudioContext = SilentAudioContext;
});

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
let sent: unknown[];
const originalShow = Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, "showModal");
const originalClose = Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, "close");
beforeEach(() => {
  vi.useFakeTimers();
  sent = [];
  vi.spyOn(conn, "send").mockImplementation((m: unknown) => { sent.push(m); return true; });
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", { configurable: true, value: function (this: HTMLDialogElement) {
    this.setAttribute("open", "");
  } });
  Object.defineProperty(HTMLDialogElement.prototype, "close", { configurable: true, value: function (this: HTMLDialogElement) {
    this.removeAttribute("open");
  } });
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});
afterEach(() => {
  Reflect.deleteProperty(document, "elementFromPoint");
  act(() => root.unmount());
  host.remove();
  vi.restoreAllMocks();
  vi.useRealTimers();
  for (const [name, descriptor] of [["showModal", originalShow], ["close", originalClose]] as const) {
    if (descriptor) Object.defineProperty(HTMLDialogElement.prototype, name, descriptor);
    else Reflect.deleteProperty(HTMLDialogElement.prototype, name);
  }
});

let dealt = 1;
/** The next 200 ms of the deal: one more card. */
function nextFrame() {
  act(() => { vi.advanceTimersByTime(200); });
  dealt += 1;
  act(() => root.render(<Table state={deal(dealt)} />));
}

const more = () => host.querySelector<HTMLButtonElement>(".hud-more-btn")!;
const sheet = () => document.querySelector<HTMLDialogElement>("[role='alertdialog'][open]");

describe("Leave game while the cards are dealt", () => {
  it("opens the menu, keeps it open through the deal, and leaves on touches alone", () => {
    dealt = 1;
    act(() => root.render(<Table state={deal(dealt)} />));
    const end = touchOnly(more());
    // the touch acted and cancelled its click, so no late click acts twice
    expect(end.defaultPrevented).toBe(true);
    expect(more().getAttribute("aria-expanded")).toBe("true");
    for (let i = 0; i < 5; i++) {
      nextFrame();
      expect(more().getAttribute("aria-expanded")).toBe("true");
    }
    touchOnly(host.querySelector(".hud-menu-row.leave")!);
    expect(more().getAttribute("aria-expanded")).toBe("false");
    expect(sheet()).not.toBeNull();
    for (let i = 0; i < 5; i++) {
      nextFrame();
      expect(sheet()).not.toBeNull();
    }
    expect(sent).toEqual([]);
    touchOnly(sheet()!.querySelector(".leave-sheet-leave")!);
    expect(sent).toEqual([{ type: "table_leave" }]);
  });

  it("Stay answers a touch alone too, and the menu opens again", () => {
    dealt = 1;
    act(() => root.render(<Table state={deal(dealt)} />));
    touchOnly(more());
    touchOnly(host.querySelector(".hud-menu-row.leave")!);
    nextFrame();
    touchOnly(sheet()!.querySelector(".leave-sheet-stay")!);
    expect(sheet()).toBeNull();
    nextFrame();
    touchOnly(more());
    expect(more().getAttribute("aria-expanded")).toBe("true");
    expect(sent).toEqual([]);
  });

  it("a finger that slides away is not a tap", () => {
    dealt = 1;
    act(() => root.render(<Table state={deal(dealt)} />));
    const el = more();
    act(() => {
      const begin = new Event("touchstart", { bubbles: true, cancelable: true });
      const t0 = { identifier: 1, clientX: 10, clientY: 10, target: el };
      Object.defineProperty(begin, "touches", { value: [t0] });
      Object.defineProperty(begin, "changedTouches", { value: [t0] });
      el.dispatchEvent(begin);
      const end = new Event("touchend", { bubbles: true, cancelable: true });
      Object.defineProperty(end, "touches", { value: [] });
      Object.defineProperty(end, "changedTouches", { value: [{ ...t0, clientY: 60 }] });
      el.dispatchEvent(end);
    });
    expect(more().getAttribute("aria-expanded")).toBe("false");
  });

  it.each(["outside", "excursion"])("does not confirm Leave after a cancelled %s gesture", (kind) => {
    dealt = 1;
    act(() => root.render(<Table state={deal(dealt)} />));
    touchOnly(more());
    touchOnly(host.querySelector(".hud-menu-row.leave")!);
    const el = sheet()!.querySelector<HTMLButtonElement>(".leave-sheet-leave")!;
    const backdrop = sheet()!;
    vi.spyOn(el, "getBoundingClientRect").mockReturnValue({ left: 10, right: 110, top: 10, bottom: 50,
      width: 100, height: 40, x: 10, y: 10, toJSON() {} });
    // the Leave button covers x 10..110, y 10..50; elsewhere is the backdrop
    Object.defineProperty(document, "elementFromPoint", { configurable: true,
      value: (x: number, y: number) => x >= 10 && x <= 110 && y >= 10 && y <= 50 ? el : backdrop });
    function fire(type: string, x: number) {
      const t = { identifier: 1, clientX: x, clientY: 20, target: el };
      const e = new Event(type, { bubbles: true, cancelable: true });
      Object.defineProperty(e, "touches", { value: type === "touchend" ? [] : [t] });
      Object.defineProperty(e, "changedTouches", { value: [t] });
      act(() => el.dispatchEvent(e));
    }
    fire("touchstart", 12);
    if (kind === "excursion") {
      fire("touchmove", 60);
      fire("touchmove", 12);
    }
    fire("touchend", kind === "outside" ? 6 : 12);
    expect(sent).toEqual([]);
  });

  it("confirms Leave on a touch that lifts over the button", () => {
    dealt = 1;
    act(() => root.render(<Table state={deal(dealt)} />));
    touchOnly(more());
    touchOnly(host.querySelector(".hud-menu-row.leave")!);
    const el = sheet()!.querySelector<HTMLButtonElement>(".leave-sheet-leave")!;
    Object.defineProperty(document, "elementFromPoint", { configurable: true, value: () => el.firstChild ?? el });
    touchOnly(el);
    expect(sent).toEqual([{ type: "table_leave" }]);
  });

  it("a mouse or keyboard click still opens the menu once", () => {
    dealt = 1;
    act(() => root.render(<Table state={deal(dealt)} />));
    act(() => more().click());
    expect(more().getAttribute("aria-expanded")).toBe("true");
  });
});
