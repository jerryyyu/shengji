import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import Card, { spokenLabel } from "./Card";

it("uses native toggle buttons only for selectable cards, including jokers", () => {
  const host = document.createElement("div");
  const root = createRoot(host);
  const toggle = vi.fn();
  try {
    for (const code of ["H10", "BJ", "LJ"]) {
      act(() => root.render(<Card code={code} selected onClick={toggle} />));
      const button = host.querySelector("button")!;
      expect(button.type).toBe("button");
      expect(button.getAttribute("aria-pressed")).toBe("true");
      expect(button.getAttribute("aria-label")).toBeTruthy();
      act(() => button.click());
    }
    expect(toggle).toHaveBeenCalledTimes(3);
    act(() => root.render(<Card code="H10" />));
    expect(host.querySelector("button")).toBeNull();
  } finally { act(() => root.unmount()); }
});

it("speaks every rank, suit and joker by name", () => {
  const ranks: [string, string][] = [
    ["2", "2"], ["3", "3"], ["4", "4"], ["5", "5"], ["6", "6"], ["7", "7"], ["8", "8"], ["9", "9"],
    ["10", "10"], ["J", "Jack"], ["Q", "Queen"], ["K", "King"], ["A", "Ace"],
  ];
  const suits: [string, string][] = [["S", "spades"], ["H", "hearts"], ["D", "diamonds"], ["C", "clubs"]];
  const expected: [string, string][] = [["BJ", "Big joker"], ["LJ", "Little joker"]];
  for (const [s, suit] of suits) for (const [r, rank] of ranks) expected.push([s + r, `${rank} of ${suit}`]);
  expect(expected).toHaveLength(54);
  const host = document.createElement("div");
  const root = createRoot(host);
  try {
    for (const [code, label] of expected) {
      expect(spokenLabel(code)).toBe(label);
      act(() => root.render(<Card code={code} onClick={() => {}} />));
      expect(host.querySelector("button")!.getAttribute("aria-label")).toBe(label);
      act(() => root.render(<Card code={code} />));
      const face = host.querySelector<HTMLElement>(".card")!;
      expect(face.getAttribute("role")).toBe("img");
      expect(face.getAttribute("aria-label")).toBe(label);
      // the drawn glyphs are hidden, so the card is read once, by its label
      for (const child of face.children) expect(child.getAttribute("aria-hidden")).toBe("true");
    }
  } finally { act(() => root.unmount()); }
});
