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
    expect(card(0).textContent).toContain("Partner");
    expect(card(3).textContent).toContain("Empty");
    expect(card(0).querySelector(".host-tag")).not.toBeNull();
    expect(card(2).querySelector(".you-tag")).not.toBeNull();
    expect(card(1).querySelector(".bot-tag")).not.toBeNull();
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
    expect(seats).toHaveLength(3);
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
    expect(card(2).getAttribute("aria-pressed")).toBe("false");
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

describe("tap to swap", () => {
  it("selects one seat, then swaps with the next one tapped", () => {
    render(room());
    act(() => card(1).click());
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
    act(() => card(1).click());
    expect(card(1).getAttribute("aria-pressed")).toBe("false");
    act(() => card(0).click());
    act(() => { card(0).dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })); });
    expect(card(0).getAttribute("aria-pressed")).toBe("false");
    expect(swaps()).toEqual([]);
  });

  it("is reachable by keyboard: seats are buttons in the tab order", () => {
    render(room());
    const buttons = [...host.querySelectorAll<HTMLButtonElement>("button.seat-card")];
    expect(buttons.map((b) => b.dataset.seat).sort()).toEqual(["0", "1", "2"]);
    expect(buttons.every((b) => b.type === "button" && b.tabIndex === 0)).toBe(true);
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
