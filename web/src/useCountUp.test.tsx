import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { DUR } from "./motion";
import { useCountUp } from "./useCountUp";

function Probe({ target, snapDown }: { target: number; snapDown?: boolean }) {
  return <span>{Math.round(useCountUp(target, { snapDown }))}</span>;
}

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
const shown = () => Number(host.textContent);
const show = (target: number, snapDown?: boolean) => act(() => root.render(<Probe target={target} snapDown={snapDown} />));

beforeEach(() => {
  vi.useFakeTimers();
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.useRealTimers();
});

it("shows the first value as is and rolls to the next", () => {
  show(20);
  expect(shown()).toBe(20);
  show(60);
  expect(shown()).toBe(20);
  act(() => { vi.advanceTimersByTime(DUR.count + 50); });
  expect(shown()).toBe(60);
});

it("restarts from the number on screen when a new target interrupts a roll", () => {
  show(0);
  show(100);
  act(() => { vi.advanceTimersByTime(DUR.count / 5); });
  const mid = shown();
  expect(mid).toBeGreaterThan(0);
  expect(mid).toBeLessThan(100);
  show(120);
  // the next frame continues upward from `mid`, never back toward 0
  act(() => { vi.advanceTimersByTime(20); });
  expect(shown()).toBeGreaterThanOrEqual(mid);
  act(() => { vi.advanceTimersByTime(DUR.count + 50); });
  expect(shown()).toBe(120);
});

it("snaps down when asked, and rolls down otherwise", () => {
  show(80, true);
  show(0, true);
  expect(shown()).toBe(0);
  show(80);
  act(() => { vi.advanceTimersByTime(DUR.count + 50); });
  show(10);
  expect(shown()).toBe(80);
  act(() => { vi.advanceTimersByTime(DUR.count + 50); });
  expect(shown()).toBe(10);
});
