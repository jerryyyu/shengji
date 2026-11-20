import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import { useMoveClock } from "./useMoveClock";

vi.mock("./native", () => ({ haptic: vi.fn() }));

function Clock({ seconds, stamp }: { seconds: number | null; stamp: number }) {
  return <span>{String(useMoveClock(seconds, stamp, false))}</span>;
}

it("stops expired clocks and restarts only with a fresh deadline", () => {
  vi.useFakeTimers();
  const host = document.createElement("div");
  const root = createRoot(host);
  const render = (seconds: number | null, stamp: number) =>
    act(() => root.render(<Clock seconds={seconds} stamp={stamp} />));
  try {
    render(1, 0);
    expect(vi.getTimerCount()).toBe(1);
    act(() => vi.advanceTimersByTime(1000));
    expect(host.textContent).toBe("0");
    expect(vi.getTimerCount()).toBe(0);
    act(() => vi.advanceTimersByTime(60_000));
    expect(host.textContent).toBe("0");
    render(1, 1);
    expect(vi.getTimerCount()).toBe(1);
    act(() => vi.advanceTimersByTime(250));
    expect(host.textContent).toBe("1");
    render(null, 2);
    expect(host.textContent).toBe("null");
    expect(vi.getTimerCount()).toBe(0);
    render(0, 3);
    expect(host.textContent).toBe("0");
    expect(vi.getTimerCount()).toBe(0);
    render(-2, 4);
    expect(host.textContent).toBe("0");
    expect(vi.getTimerCount()).toBe(0);
    render(10, 5);
    expect(vi.getTimerCount()).toBe(1);
  } finally {
    act(() => root.unmount());
    expect(vi.getTimerCount()).toBe(0);
    vi.useRealTimers();
  }
});
