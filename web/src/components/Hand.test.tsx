// Hand cards are memoized; these pin that they still follow the props that
// matter (selection, selectability, the cards themselves) and that a tap
// reports the right card id through the stable callback. A finger slid
// across the hand chooses a run of cards.
import { act, useCallback, useState } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import Hand from "./Hand";

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
afterEach(() => {
  act(() => root.unmount());
  host.remove();
});
function mount() {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
}
const cards = () => [...host.querySelectorAll<HTMLElement>(".hand .card")];
const hand = (codes: string[]) => codes.map((code, id) => ({ id, code }));

it("memoized hand cards still update on selection, selectability and hand changes", () => {
  const onToggle = vi.fn();
  mount();
  act(() => root.render(<Hand hand={hand(["S5", "H7", "BJ"])} selected={new Set()} selectable onToggle={onToggle} />));
  act(() => cards()[1].click());
  expect(onToggle).toHaveBeenCalledWith(1);

  act(() => root.render(<Hand hand={hand(["S5", "H7", "BJ"])} selected={new Set([1])} selectable onToggle={onToggle} />));
  expect(cards().map((c) => c.classList.contains("selected"))).toEqual([false, true, false]);

  // Same ids, fresh array (as every server state delivers): content follows.
  act(() => root.render(<Hand hand={[{ id: 0, code: "S5" }, { id: 2, code: "BJ" }]} selected={new Set([1])} selectable onToggle={onToggle} />));
  expect(cards()).toHaveLength(2);
  expect(cards().map((c) => c.getAttribute("aria-label"))).toEqual(["5 of spades", "Big joker"]);

  act(() => root.render(<Hand hand={[{ id: 0, code: "S5" }, { id: 2, code: "BJ" }]} selected={new Set()} selectable={false} onToggle={onToggle} />));
  expect(cards().every((c) => c.tagName === "DIV" && !c.classList.contains("clickable"))).toBe(true);
  act(() => cards()[0].click());
  expect(onToggle).toHaveBeenCalledTimes(1);
});

/** A pointer event as a finger sends it, at a hand slot found by `at`. */
function finger(type: string, target: Element, x: number, pointerType = "touch") {
  const e = new Event(type, { bubbles: true, cancelable: true });
  Object.assign(e, { pointerId: 7, pointerType, clientX: x, clientY: 10, isPrimary: true });
  act(() => { target.dispatchEvent(e); });
}

describe("drag-select", () => {
  // one card per 10px along the hand; the hit test is what a browser's would be
  const at = (x: number) => host.querySelectorAll(".hand-slot")[Math.floor(x / 10)] ?? null;
  let restore: () => void;
  beforeEach(() => {
    const real = document.elementFromPoint;
    document.elementFromPoint = (x: number) => at(x)?.querySelector(".card") ?? null;
    restore = () => { document.elementFromPoint = real; };
  });
  afterEach(() => restore());

  /** A stateful hand: the parent applies each toggle, as Table does. */
  function Harness({ codes, initial = [] }: { codes: string[]; initial?: number[] }) {
    const [sel, setSel] = useState(new Set(initial));
    const toggle = useCallback((id: number) => setSel((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    }), []);
    return <Hand hand={hand(codes)} selected={sel} selectable onToggle={toggle} />;
  }
  const picked = () => cards().map((c) => c.classList.contains("selected"));

  it("a slide from one card across the next three selects all four, each once", () => {
    mount();
    act(() => root.render(<Harness codes={["S2", "S3", "S4", "S5", "S6", "S7"]} />));
    finger("pointerdown", cards()[1], 15);
    for (const x of [16, 22, 25, 31, 38, 42, 44]) finger("pointermove", cards()[1], x);
    finger("pointerup", cards()[1], 44);
    // the click a browser may still send for the first card is not a tap
    act(() => cards()[1].click());
    expect(picked()).toEqual([false, true, true, true, true, false]);
  });

  it("a slide that starts on a chosen card clears the run, and leaves the others", () => {
    mount();
    act(() => root.render(<Harness codes={["S2", "S3", "S4", "S5", "S6"]} initial={[0, 2, 3]} />));
    finger("pointerdown", cards()[2], 25);
    finger("pointermove", cards()[2], 35);
    finger("pointermove", cards()[2], 45);
    finger("pointerup", cards()[2], 45);
    expect(picked()).toEqual([true, false, false, false, false]);
  });

  it("a tap without a slide still toggles one card, and the next tap is not swallowed", () => {
    mount();
    act(() => root.render(<Harness codes={["S2", "S3", "S4"]} />));
    finger("pointerdown", cards()[0], 5);
    finger("pointermove", cards()[0], 6);   // still on the same card
    finger("pointerup", cards()[0], 6);
    act(() => cards()[0].click());
    expect(picked()).toEqual([true, false, false]);
    finger("pointerdown", cards()[2], 25);
    finger("pointerup", cards()[2], 25);
    act(() => cards()[2].click());
    expect(picked()).toEqual([true, false, true]);
  });

  it("a mouse drag and a hand that cannot be chosen from change nothing", () => {
    mount();
    act(() => root.render(<Harness codes={["S2", "S3", "S4"]} />));
    finger("pointerdown", cards()[0], 5, "mouse");
    finger("pointermove", cards()[0], 25, "mouse");
    finger("pointerup", cards()[0], 25, "mouse");
    expect(picked()).toEqual([false, false, false]);
    const onToggle = vi.fn();
    act(() => root.render(<Hand hand={hand(["S2", "S3"])} selected={new Set()} selectable={false} onToggle={onToggle} />));
    finger("pointerdown", cards()[0], 5);
    finger("pointermove", cards()[0], 15);
    expect(onToggle).not.toHaveBeenCalled();
  });

  it("a finger down lifts the card under it, a slide carries the lift, and lifting the finger drops it", () => {
    mount();
    act(() => root.render(<Harness codes={["S2", "S3", "S4", "S5"]} />));
    const pressed = () => [...host.querySelectorAll(".hand-slot")].map((s) => s.classList.contains("pressed"));
    finger("pointerdown", cards()[1], 15);
    expect(pressed()).toEqual([false, true, false, false]);
    // nothing is chosen until the finger comes up
    expect(picked()).toEqual([false, false, false, false]);
    finger("pointermove", cards()[1], 35);
    expect(pressed()).toEqual([false, false, false, true]);
    finger("pointerup", cards()[1], 35);
    expect(pressed()).toEqual([false, false, false, false]);
  });

  it("a tap still commits on release, through the click", () => {
    mount();
    act(() => root.render(<Harness codes={["S2", "S3"]} />));
    finger("pointerdown", cards()[0], 5);
    expect(host.querySelector(".hand-slot.pressed")).not.toBeNull();
    expect(picked()).toEqual([false, false]);
    finger("pointerup", cards()[0], 5);
    act(() => cards()[0].click());
    expect(picked()).toEqual([true, false]);
    expect(host.querySelector(".hand-slot.pressed")).toBeNull();
  });

  it("a finger that wobbles across a card edge, under the slop, is a tap on the card it went down on", () => {
    mount();
    act(() => root.render(<Harness codes={["S2", "S3", "S4"]} />));
    finger("pointerdown", cards()[1], 11);
    finger("pointermove", cards()[1], 8);   // over card 0's sliver, 3px away
    finger("pointerup", cards()[1], 8);
    act(() => cards()[0].click());           // the click lands where the finger lifted
    expect(picked()).toEqual([false, true, false]);
  });

  it("a tap commits on release even when the browser sends no click", () => {
    mount();
    act(() => root.render(<Harness codes={["S2", "S3"]} />));
    finger("pointerdown", cards()[1], 15);
    finger("pointerup", cards()[1], 15);
    expect(picked()).toEqual([false, true]);
  });

  it("a cancelled press chooses nothing", () => {
    mount();
    act(() => root.render(<Harness codes={["S2", "S3"]} />));
    finger("pointerdown", cards()[1], 15);
    finger("pointercancel", cards()[1], 15);
    expect(picked()).toEqual([false, false]);
  });

  it("a mouse press does not lift; the hover does that", () => {
    mount();
    act(() => root.render(<Harness codes={["S2", "S3"]} />));
    finger("pointerdown", cards()[0], 5, "mouse");
    expect(host.querySelector(".hand-slot.pressed")).toBeNull();
  });
});
