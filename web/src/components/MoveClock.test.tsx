// The ring's drain is one CSS animation over the whole window: it starts at
// the server's figure, runs on without React restarting it as the seconds
// tick, and starts again only when the deadline moves.
import { act, useState } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { RING_RESYNC_MS, TimerRing } from "./MoveClock";
import { useMoveClock } from "../useMoveClock";

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
const draw = (left: number | null, total = 60) => act(() => root.render(<TimerRing left={left} total={total} />));
const band = () => host.querySelector<HTMLElement>(".timer-ring-band");
const at = () => band()?.style.getPropertyValue("--ring-at");

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

it("starts the drain part way through the window, at the server's figure", () => {
  draw(45);
  expect(band()!.style.getPropertyValue("--ring-total")).toBe("60s");
  expect(at()).toBe("-15s");
  expect(host.querySelector(".timer-ring-secs")!.textContent).toBe("45");
  expect(host.querySelectorAll(".timer-ring-half")).toHaveLength(2);
});

it("lets the drain run on as the seconds tick, without restarting it", () => {
  draw(45);
  const first = band();
  vi.advanceTimersByTime(3000);
  draw(42);
  expect(band()).toBe(first);
  expect(at()).toBe("-15s");
  expect(host.querySelector(".timer-ring-secs")!.textContent).toBe("42");
  // a later server figure within the jitter keeps it too
  vi.advanceTimersByTime(1000);
  draw(41 + (RING_RESYNC_MS - 100) / 1000);
  expect(band()).toBe(first);
});

it("starts again from a deadline that moved, and holds full while an extended window is above its length", () => {
  draw(45);
  const first = band();
  vi.advanceTimersByTime(1000);
  draw(60);                 // the server restarted the window
  expect(band()).not.toBe(first);
  expect(at()).toBe("0s");
  draw(70);                 // extended past the window: full for 10 s, then the drain
  expect(at()).toBe("10s");
});

it("steps the drain once a second under Reduce Motion, from its half-window count", () => {
  draw(5, 5);
  expect(band()!.style.getPropertyValue("--ring-steps")).toBe("3");
  draw(null);
  expect(band()).toBeNull();
});

// The hook's sample and the ring together, as the table draws them: `chosen`
// stands for any local redraw between the clock's ticks.
let redraw: () => void = () => {};
function Clocked({ seconds, stamp }: { seconds: number; stamp: number }) {
  const [, setChosen] = useState(0);
  redraw = () => setChosen((n) => n + 1);
  const left = useMoveClock(seconds, stamp, false);
  return <TimerRing left={left} total={60} />;
}

it("keeps the drain through a local redraw between ticks, and starts again on a new server deadline", () => {
  act(() => root.render(<Clocked seconds={45} stamp={1} />));
  const first = band();
  act(() => { vi.advanceTimersByTime(750); });
  act(() => redraw());                    // a card chosen before the next tick
  expect(band()).toBe(first);
  act(() => { vi.advanceTimersByTime(250); });   // the tick at 44
  expect(host.querySelector(".timer-ring-secs")!.textContent).toBe("44");
  expect(band()).toBe(first);
  act(() => { vi.advanceTimersByTime(600); });
  act(() => redraw());
  expect(band()).toBe(first);
  act(() => root.render(<Clocked seconds={43.4} stamp={2} />));   // the same deadline, a new state
  expect(band()).toBe(first);
  act(() => root.render(<Clocked seconds={60} stamp={3} />));     // the server restarted the window
  expect(band()).not.toBe(first);
  expect(at()).toBe("0s");
});
