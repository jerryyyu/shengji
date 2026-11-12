// The room's seats sit around a table as the game draws them, and the host
// rearranges people by dragging one seat onto another or by tapping two.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { RoomMsg } from "../protocol";

const { sent } = vi.hoisted(() => ({ sent: [] as unknown[] }));
vi.mock("../ws", () => ({ conn: { send: (m: unknown) => { sent.push(m); return true; } } }));
vi.mock("./MuteButton", () => ({ default: () => null }));

import Room from "./Room";

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;

const room = (over: Partial<RoomMsg> = {}): RoomMsg => ({
  type: "room", room: "ABCD", you: 0, host: 0, start_level: "2",
  players: [
    { seat: 0, name: "Jerry", is_bot: false, connected: true },
    { seat: 1, name: "Bot 1", is_bot: true, connected: true },
    { seat: 2, name: "Amy", is_bot: false, connected: true },
  ],
  ...over,
});

function render(msg: RoomMsg) {
  act(() => root.render(<Room room={msg} />));
}
const card = (seat: number) => host.querySelector<HTMLElement>(`[data-seat='${seat}']`)!;
const swaps = () => sent.filter((m) => (m as { type: string }).type === "swap_seats");

/** Each seat card's box: seat n at x 100n..100n+80, y 0..60. */
function stubRects() {
  for (const el of host.querySelectorAll<HTMLElement>("[data-seat]")) {
    const n = Number(el.dataset.seat);
    el.getBoundingClientRect = () =>
      ({ left: 100 * n, right: 100 * n + 80, top: 0, bottom: 60, width: 80, height: 60, x: 100 * n, y: 0 }) as DOMRect;
  }
}
const centre = (seat: number) => ({ x: 100 * seat + 40, y: 30 });

function pointer(type: string, target: Element, x: number, y: number, pointerId = 1) {
  const e = new Event(type, { bubbles: true, cancelable: true });
  Object.assign(e, { pointerId, pointerType: "touch", clientX: x, clientY: y, isPrimary: pointerId === 1, button: 0 });
  act(() => { target.dispatchEvent(e); });
  return e;
}

beforeEach(() => {
  sent.length = 0;
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

describe("layout", () => {
  it("places seats around the table relative to you", () => {
    render(room({ you: 2, host: 0 }));
    expect(card(2).className).toContain("pos-bottom");
    expect(card(3).className).toContain("pos-left");
    expect(card(0).className).toContain("pos-top");
    expect(card(1).className).toContain("pos-right");
    expect(card(0).querySelector(".seat-card-role")?.textContent).toBe("Partner · Host");
    expect(card(2).querySelector(".seat-card-role")?.textContent).toBe("You");
    expect(card(1).querySelector(".seat-card-role")?.textContent).toBe("Bot · Opponent");
    expect(card(3).textContent).toContain("Empty");
    expect(card(0).querySelector(".conn-pip.on")).not.toBeNull();
    expect(host.textContent).not.toContain("Team seats");
  });

  it("gives a non-host no handles", () => {
    render(room({ you: 2, host: 0 }));
    expect(host.querySelectorAll("button.seat-card")).toHaveLength(0);
    stubRects();
    const a = centre(2);
    const b = centre(0);
    pointer("pointerdown", card(2), a.x, a.y);
    pointer("pointermove", card(2), b.x, b.y);
    pointer("pointerup", card(0), b.x, b.y);
    act(() => card(2).click());
    act(() => card(0).click());
    expect(card(2).className).not.toContain("lifted");
    expect(swaps()).toEqual([]);
  });

  it("shows no hint text, and describes the host's seat handles to screen readers", () => {
    render(room());
    expect(host.textContent).not.toContain("Drag to swap seats");
    const seats = [...host.querySelectorAll<HTMLButtonElement>("button.seat-card")];
    expect(seats).toHaveLength(4);
    const hint = document.getElementById(seats[0].getAttribute("aria-describedby")!)!;
    expect(hint.hidden).toBe(true);
    expect(hint.textContent).toContain("to swap them");
  });
});

describe("host drag", () => {
  beforeEach(() => {
    render(room());
    stubRects();
  });

  it("drops one seat on another and sends the swap", () => {
    const a = centre(0);
    const b = centre(2);
    pointer("pointerdown", card(0), a.x, a.y);
    const move = pointer("pointermove", card(0), b.x, b.y);
    expect(move.defaultPrevented).toBe(true);
    expect(card(0).className).toContain("lifted");
    expect(card(0).style.transform).toBe(`translate(${b.x - a.x}px, 0px)`);
    expect(card(2).className).toContain("drop-target");
    pointer("pointerup", card(2), b.x, b.y);
    expect(swaps()).toEqual([{ type: "swap_seats", a: 0, b: 2 }]);
    expect(card(0).className).not.toContain("lifted");
    // the release's click is not a tap that selects the seat
    act(() => card(2).click());
    expect(sheet()).toBeNull();
  });

  it("does not prevent default or lift before the move threshold", () => {
    const a = centre(0);
    pointer("pointerdown", card(0), a.x, a.y);
    const small = pointer("pointermove", card(0), a.x + 3, a.y + 2);
    expect(small.defaultPrevented).toBe(false);
    expect(card(0).className).not.toContain("lifted");
    pointer("pointerup", card(0), a.x + 3, a.y + 2);
    expect(swaps()).toEqual([]);
  });

  it("snaps back with nothing sent on a release away from every seat", () => {
    const a = centre(0);
    pointer("pointerdown", card(0), a.x, a.y);
    pointer("pointermove", card(0), a.x, a.y + 200);
    // the clock holds the pointer capture, so the release reaches it
    pointer("pointerup", host.querySelector(".seat-clock")!, a.x, a.y + 200);
    expect(swaps()).toEqual([]);
    expect(card(0).className).not.toContain("lifted");
  });

  it("sends nothing when the drag is cancelled", () => {
    const a = centre(0);
    const b = centre(2);
    pointer("pointerdown", card(0), a.x, a.y);
    pointer("pointermove", card(0), b.x, b.y);
    pointer("pointercancel", card(0), b.x, b.y);
    pointer("pointerup", card(2), b.x, b.y);
    expect(swaps()).toEqual([]);
    expect(card(0).className).not.toContain("lifted");
  });

  it("settles on a second touch and sends nothing", () => {
    const a = centre(0);
    const b = centre(2);
    pointer("pointerdown", card(0), a.x, a.y);
    pointer("pointermove", card(0), b.x, b.y);
    pointer("pointerdown", card(1), centre(1).x, 30, 2);
    expect(card(0).className).not.toContain("lifted");
    pointer("pointerup", card(2), b.x, b.y);
    expect(swaps()).toEqual([]);
  });

  it("never drops on an empty seat", () => {
    const a = centre(0);
    const e = centre(3);
    pointer("pointerdown", card(0), a.x, a.y);
    pointer("pointermove", card(0), e.x, e.y);
    expect(card(3).className).not.toContain("drop-target");
    pointer("pointerup", card(3), e.x, e.y);
    expect(swaps()).toEqual([]);
  });
});

const sheet = () => document.querySelector<HTMLElement>(".room-sheet");
const sheetButton = (label: string) =>
  [...document.querySelectorAll<HTMLButtonElement>(".room-sheet button")].find((b) => b.textContent === label);

describe("tap to swap", () => {
  it("opens the seat, chooses Swap seats, then swaps with the next seat tapped", () => {
    render(room());
    act(() => card(1).click());
    expect(sheet()?.textContent).toContain("Bot 1");
    act(() => sheetButton("Swap seats")!.click());
    expect(sheet()).toBeNull();
    expect(card(1).getAttribute("aria-pressed")).toBe("true");
    const hint = document.getElementById(card(1).getAttribute("aria-describedby")!)!;
    expect(hint.textContent).toContain("Selected Bot 1");
    act(() => card(2).click());
    expect(swaps()).toEqual([{ type: "swap_seats", a: 1, b: 2 }]);
    expect(card(1).getAttribute("aria-pressed")).toBe("false");
  });

  it("deselects on a second tap of the same seat or on Escape", () => {
    render(room());
    act(() => card(1).click());
    act(() => sheetButton("Swap seats")!.click());
    act(() => card(1).click());
    expect(card(1).getAttribute("aria-pressed")).toBe("false");
    expect(sheet()).toBeNull();
    act(() => card(0).click());
    act(() => sheetButton("Swap seats")!.click());
    act(() => { card(0).dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })); });
    expect(card(0).getAttribute("aria-pressed")).toBe("false");
    expect(swaps()).toEqual([]);
  });

  it("is reachable by keyboard: every seat is a button in the tab order", () => {
    render(room());
    const buttons = [...host.querySelectorAll<HTMLButtonElement>("button.seat-card")];
    expect(buttons.map((b) => b.dataset.seat).sort()).toEqual(["0", "1", "2", "3"]);
    expect(buttons.every((b) => b.type === "button" && b.tabIndex === 0)).toBe(true);
  });
});

describe("seat menu", () => {
  afterEach(() => { delete (navigator as { share?: unknown }).share; });

  it("removes a person from the room", () => {
    render(room());
    act(() => card(2).click());
    expect(sheet()?.getAttribute("role")).toBe("dialog");
    act(() => sheetButton("Remove from room")!.click());
    expect(sent).toContainEqual({ type: "remove_player", seat: 2 });
    expect(sheet()).toBeNull();
  });

  it("offers no Remove on the host's own seat", () => {
    render(room());
    act(() => card(0).click());
    expect(sheetButton("Remove from room")).toBeUndefined();
    expect(sheetButton("Swap seats")).toBeDefined();
  });

  it("closes on Cancel with nothing sent", () => {
    render(room());
    act(() => card(2).click());
    act(() => sheetButton("Cancel")!.click());
    expect(sheet()).toBeNull();
    expect(sent).toEqual([]);
  });

  it("invites a friend from an empty seat through the share sheet", async () => {
    const share = vi.fn(() => Promise.resolve());
    Object.assign(navigator, { share });
    render(room());
    act(() => card(3).click());
    expect(sheet()?.textContent).toContain("Empty seat");
    expect(sheet()?.textContent).toContain("A bot plays here unless a friend joins first.");
    await act(async () => sheetButton("Invite a friend")!.click());
    expect(share).toHaveBeenCalledWith(expect.objectContaining({ url: `${window.location.origin}/?code=ABCD` }));
    expect(sheet()).toBeNull();
    expect(sent).toEqual([]);
  });

  it("gives a non-host no seat actions", () => {
    render(room({ you: 2 }));
    for (const s of [0, 1, 2, 3]) act(() => card(s).click());
    expect(sheet()).toBeNull();
    expect(sent).toEqual([]);
  });
});

describe("room screen", () => {
  afterEach(() => { delete (navigator as { share?: unknown }).share; });

  it("has a Leave control, an UNRANKED title and no bot buttons", () => {
    render(room());
    expect(host.querySelector(".room-title")?.textContent).toBe("RoomUNRANKED");
    expect(host.textContent).not.toContain("Add bot");
    expect(host.textContent).not.toContain("Remove bot");
    act(() => host.querySelector<HTMLButtonElement>(".room-leave")!.click());
    expect(sent).toEqual([{ type: "leave_room" }]);
  });

  it("drops the copy captions and labels the code box", () => {
    render(room());
    expect(host.textContent).not.toMatch(/click to copy|Tap to copy/i);
    expect(host.querySelector(".room-code")?.getAttribute("aria-label")).toBe("Room code A B C D");
  });

  it("shows empty seats as a bot's", () => {
    render(room());
    expect(card(3).textContent).toBe("Emptya bot plays");
  });

  it("labels the host's button Start whether or not seats are empty", () => {
    render(room());
    const start = () => host.querySelector<HTMLButtonElement>(".room-start")!;
    expect(start().textContent).toBe("Start");
    act(() => start().click());
    expect(sent).toEqual([{ type: "start_game" }]);
    render(room({ players: [0, 1, 2, 3].map((seat) => ({ seat, name: `P${seat}`, is_bot: false, connected: true })) }));
    expect(start().textContent).toBe("Start");
  });

  it("gives a non-host no start button", () => {
    render(room({ you: 2 }));
    expect(host.querySelector(".room-start")).toBeNull();
    expect(host.textContent).toContain("Waiting for the host to start");
  });

  it("copies the invite link where there is no share sheet", async () => {
    const writeText = vi.fn(() => Promise.resolve());
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    render(room());
    await act(async () => host.querySelector<HTMLButtonElement>(".room-invite")!.click());
    expect(writeText).toHaveBeenCalledWith(`${window.location.origin}/?code=ABCD`);
    expect(host.querySelector(".copied-tag")?.className).toContain("show");
  });
});

it("keeps the drag when a card hands its touch capture to the clock", () => {
  render(room());
  stubRects();
  const a = centre(0);
  const b = centre(2);
  pointer("pointerdown", card(0), a.x, a.y);
  pointer("pointermove", card(0), b.x, b.y);
  pointer("lostpointercapture", card(0), b.x, b.y);
  expect(card(0).className).toContain("lifted");
  pointer("pointerup", card(2), b.x, b.y);
  expect(swaps()).toEqual([{ type: "swap_seats", a: 0, b: 2 }]);
});
