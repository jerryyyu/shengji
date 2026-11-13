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
  it("shows one tag per seat: Host over the role, You · Host on your own", () => {
    render(room({ you: 1, host: 2, players: [...room().players, { seat: 3, name: "Sam", is_bot: false, connected: true }] }));
    expect(card(2).querySelector(".seat-card-role")?.textContent).toBe("Host");
    expect(card(3).querySelector(".seat-card-role")?.textContent).toBe("Partner");
    render(room());
    expect(card(0).querySelector(".seat-card-role")?.textContent).toBe("You · Host");
  });

  it("places seats around the table relative to you", () => {
    render(room({ you: 2, host: 0 }));
    expect(card(2).className).toContain("pos-bottom");
    expect(card(3).className).toContain("pos-left");
    expect(card(0).className).toContain("pos-top");
    expect(card(1).className).toContain("pos-right");
    expect(card(0).querySelector(".seat-card-role")?.textContent).toBe("Host");
    expect(card(2).querySelector(".seat-card-role")?.textContent).toBe("You");
    expect(card(1).querySelector(".seat-card-role")?.textContent).toBe("Opponent");
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
    expect(hint.textContent).toContain("tap your own seat and then another");
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
    expect(swaps()).toEqual([expect.objectContaining({ type: "swap_seats", a: 0, b: 2 })]);
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

  it("drops on an empty seat, moving the person there", () => {
    const a = centre(2);
    const e = centre(3);
    pointer("pointerdown", card(2), a.x, a.y);
    pointer("pointermove", card(2), e.x, e.y);
    expect(card(3).className).toContain("drop-target");
    pointer("pointerup", card(3), e.x, e.y);
    expect(swaps()).toEqual([expect.objectContaining({ type: "swap_seats", a: 2, b: 3 })]);
  });

  it("does not drag an empty seat", () => {
    const e = centre(3);
    const b = centre(2);
    pointer("pointerdown", card(3), e.x, e.y);
    pointer("pointermove", card(3), b.x, b.y);
    expect(card(3).className).not.toContain("lifted");
    pointer("pointerup", card(2), b.x, b.y);
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
    expect(swaps()).toEqual([expect.objectContaining({ type: "swap_seats", a: 1, b: 2 })]);
    expect(card(1).getAttribute("aria-pressed")).toBe("false");
  });

  it("moves the chosen person into an empty seat", () => {
    render(room());
    act(() => card(2).click());
    act(() => sheetButton("Swap seats")!.click());
    expect(card(3).className).toContain("swap-target");
    act(() => card(3).click());
    expect(swaps()).toEqual([expect.objectContaining({ type: "swap_seats", a: 2, b: 3 })]);
    expect(sheet()).toBeNull();
  });

  it("deselects on a second tap of the same seat or on Escape", () => {
    render(room());
    act(() => card(1).click());
    act(() => sheetButton("Swap seats")!.click());
    act(() => card(1).click());
    expect(card(1).getAttribute("aria-pressed")).toBe("false");
    expect(sheet()).toBeNull();
    act(() => card(0).click());
    act(() => { card(0).dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })); });
    expect(card(0).getAttribute("aria-pressed")).toBe("false");
    expect(swaps()).toEqual([]);
  });

  it("a tap on your own seat lifts it with no sheet and says so", () => {
    render(room());
    act(() => card(0).click());
    expect(sheet()).toBeNull();
    expect(card(0).getAttribute("aria-pressed")).toBe("true");
    expect(card(0).className).toContain("selected");
    expect(host.querySelector(".seat-pick-hint")?.textContent).toBe("Tap a seat to move");
  });

  it("a second tap on your own seat cancels the lift", () => {
    render(room());
    act(() => card(0).click());
    act(() => card(0).click());
    expect(card(0).getAttribute("aria-pressed")).toBe("false");
    expect(host.querySelector(".seat-pick-hint")).toBeNull();
    expect(sheet()).toBeNull();
    expect(swaps()).toEqual([]);
  });

  it("after lifting your own seat, the next seat tapped is where you move", () => {
    render(room());
    act(() => card(0).click());
    act(() => card(3).click());
    expect(swaps()).toEqual([{ type: "swap_seats", a: 0, b: 3, expect: [{ name: "Jerry", is_bot: false }, null] }]);
    expect(sheet()).toBeNull();
    expect(card(0).getAttribute("aria-pressed")).toBe("false");
  });

  it("Enter or Space on your own seat lifts it too: the seat is a native button", () => {
    render(room());
    const own = card(0);
    expect(own.tagName).toBe("BUTTON");
    expect((own as HTMLButtonElement).type).toBe("button");
    own.focus();
    act(() => own.click());   // a focused button turns Enter and Space into this click
    expect(own.getAttribute("aria-pressed")).toBe("true");
  });

  it("other seats keep their menus", () => {
    render(room());
    act(() => card(1).click());
    expect(sheet()?.textContent).toContain("Bot 1");
    expect(card(0).getAttribute("aria-pressed")).toBe("false");
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
    expect(sent).toContainEqual({ type: "remove_player", seat: 2, expect: { name: "Amy", is_bot: false } });
    expect(sheet()).toBeNull();
  });

  it("opens no menu on the host's own seat", () => {
    render(room());
    act(() => card(0).click());
    expect(sheet()).toBeNull();
    expect(card(0).getAttribute("aria-haspopup")).toBeNull();
    expect(card(2).getAttribute("aria-haspopup")).toBeNull();   // picking: the next tap moves
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
    expect(host.querySelector(".room-code")?.getAttribute("aria-label")).toBe("Room code A B C D, copy invite link");
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
  expect(swaps()).toEqual([expect.objectContaining({ type: "swap_seats", a: 0, b: 2 })]);
});


it("invalidates an occupant action sheet when the seat is vacated and refilled", () => {
  render(room());
  act(() => card(2).click());
  expect(host.querySelector("[role=dialog]")?.textContent).toContain("Amy");
  render(room({ players: room().players.filter(p => p.seat !== 2) }));
  expect(host.querySelector("[role=dialog]")).toBeNull();
  render(room({ players: room().players.map(p => p.seat === 2 ? { ...p, name: "Bob" } : p) }));
  expect(host.querySelector("[role=dialog]")).toBeNull();
});

describe("a seat that changes hands", () => {
  const frame = (over: Partial<RoomMsg> = {}): RoomMsg => room(over);
  const bob = (msg: RoomMsg): RoomMsg =>
    ({ ...msg, players: msg.players.map((p) => p.seat === 2 ? { ...p, name: "Bob" } : p) });
  const vacant = (msg: RoomMsg): RoomMsg => ({ ...msg, players: msg.players.filter((p) => p.seat !== 2) });

  it("names the occupants it means in remove and swap", () => {
    render(frame());
    act(() => card(2).click());
    act(() => sheetButton("Remove from room")!.click());
    act(() => card(2).click());
    act(() => sheetButton("Swap seats")!.click());
    act(() => card(3).click());
    expect(sent).toEqual([
      { type: "remove_player", seat: 2, expect: { name: "Amy", is_bot: false } },
      { type: "swap_seats", a: 2, b: 3, expect: [{ name: "Amy", is_bot: false }, null] },
    ]);
  });

  for (const [how, change] of [["vacated then refilled", "vacate"], ["replaced directly", "replace"]] as const) {
    const apply = () => {
      if (change === "vacate") render(vacant(frame()));
      render(bob(frame()));
    };

    it(`closes the person menu for good when ${how}`, () => {
      render(frame());
      act(() => card(2).click());
      expect(sheet()?.textContent).toContain("Amy");
      apply();
      expect(sheet()).toBeNull();
      render(bob(frame()));
      expect(sheet()).toBeNull();
      expect(sent).toEqual([]);
    });

    it(`drops a Swap seats choice when ${how}`, () => {
      render(frame());
      act(() => card(2).click());
      act(() => sheetButton("Swap seats")!.click());
      expect(card(2).getAttribute("aria-pressed")).toBe("true");
      apply();
      expect(card(2).getAttribute("aria-pressed")).toBe("false");
      act(() => card(3).click());          // now an ordinary tap: the empty seat's menu
      expect(swaps()).toEqual([]);
      expect(sheet()?.textContent).toContain("Empty seat");
    });

    it(`ends a drag when ${how}`, () => {
      render(frame());
      stubRects();
      const a = centre(2);
      const e = centre(3);
      pointer("pointerdown", card(2), a.x, a.y);
      pointer("pointermove", card(2), e.x, e.y);
      expect(card(2).className).toContain("lifted");
      apply();
      stubRects();
      expect(card(2).className).not.toContain("lifted");
      pointer("pointerup", card(3), e.x, e.y);
      expect(swaps()).toEqual([]);
    });
  }
});

describe("ranked switch", () => {
  const toggle = () => host.querySelector<HTMLButtonElement>(".room-ranked-row[role='switch']");
  const headChip = () => host.querySelector(".room-title .ranked-chip, .room-title .unranked-tag");

  it("a created room starts Unranked; the host sees the switch off", () => {
    render(room());
    expect(toggle()!.getAttribute("aria-checked")).toBe("false");
    expect(headChip()!.className).toBe("unranked-tag");
    expect(headChip()!.textContent).toBe("UNRANKED");
  });

  it("the host's tap sends set_ranked with the other state", () => {
    render(room());
    act(() => { toggle()!.click(); });
    expect(sent).toEqual([{ type: "set_ranked", on: true }]);
    sent.length = 0;
    render(room({ ranked: true }));
    act(() => { toggle()!.click(); });
    expect(sent).toEqual([{ type: "set_ranked", on: false }]);
  });

  it("the header chip shows RANKED in gold once the room is ranked", () => {
    render(room({ ranked: true }));
    expect(toggle()!.getAttribute("aria-checked")).toBe("true");
    expect(headChip()!.className).toBe("ranked-chip");
    expect(headChip()!.textContent).toBe("Ranked");
  });

  it("a seat that is not the host sees the chip and no switch", () => {
    render(room({ you: 2, ranked: true }));
    expect(toggle()).toBeNull();
    expect(headChip()!.className).toBe("ranked-chip");
    render(room({ you: 2 }));
    expect(toggle()).toBeNull();
    expect(headChip()!.textContent).toBe("UNRANKED");
  });

  it("a queue room is ranked with no switch", () => {
    render(room({ matched: true }));
    expect(toggle()).toBeNull();
    expect(headChip()!.className).toBe("ranked-chip");
  });
});
