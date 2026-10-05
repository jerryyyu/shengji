import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import Card from "./Card";

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
