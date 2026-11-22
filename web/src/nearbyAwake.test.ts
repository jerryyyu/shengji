// The joiner's host-left window counts the page's own awake time: each
// one-second tick counts once however late it comes, so a page back from
// the background after 70 s still gives the host the whole window.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { HOST_WINDOW_MS, afterAwake } from "./nearbyJoin";

beforeEach(() => { vi.useFakeTimers(); });
afterEach(() => { vi.useRealTimers(); });

describe("the host-left window", () => {
  it("runs out after HOST_WINDOW_MS of the page's time", () => {
    const fn = vi.fn();
    afterAwake(fn, HOST_WINDOW_MS);
    vi.advanceTimersByTime(HOST_WINDOW_MS - 1000);
    expect(fn).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1000);
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it("leaves out a pause: the tick held over it counts as one", () => {
    const fn = vi.fn();
    const real = window.setTimeout;
    // the page's timers, held: each runs only when the test lets it
    const held: (() => void)[] = [];
    window.setTimeout = ((cb: () => void) => { held.push(cb); return held.length; }) as typeof window.setTimeout;
    try {
      afterAwake(fn, HOST_WINDOW_MS);
      const tick = () => held.shift()!();
      for (let i = 0; i < 10; i++) tick();
      // 70 s in the background: the one tick due then runs late, once
      tick();
      for (let i = 0; i < HOST_WINDOW_MS / 1000 - 12; i++) tick();
      expect(fn).not.toHaveBeenCalled();
      tick();
      expect(fn).toHaveBeenCalledTimes(1);
    } finally {
      window.setTimeout = real;
    }
  });

  it("is cancelled by its returned call", () => {
    const fn = vi.fn();
    const cancel = afterAwake(fn, HOST_WINDOW_MS);
    vi.advanceTimersByTime(5000);
    cancel();
    vi.advanceTimersByTime(HOST_WINDOW_MS);
    expect(fn).not.toHaveBeenCalled();
  });
});
