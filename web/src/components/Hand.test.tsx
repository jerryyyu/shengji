// Hand cards are memoized; these pin that they still follow the props that
// matter (selection, selectability, the cards themselves) and that a tap
// reports the right card id through the stable callback.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
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
  expect(cards().map((c) => c.getAttribute("aria-label"))).toEqual(["♠5", "Big Joker"]);

  act(() => root.render(<Hand hand={[{ id: 0, code: "S5" }, { id: 2, code: "BJ" }]} selected={new Set()} selectable={false} onToggle={onToggle} />));
  expect(cards().every((c) => c.tagName === "DIV" && !c.classList.contains("clickable"))).toBe(true);
  act(() => cards()[0].click());
  expect(onToggle).toHaveBeenCalledTimes(1);
});
