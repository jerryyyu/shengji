// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  DUR, canAnimate, centerDelta, currentTranslate, easeOutCubic, flightKeyframes,
  prefersReducedMotion, sweepKeyframes, tweenNumber, unionBox,
} from "./motion";
import type { TweenClock } from "./motion";

/** A clock the test drives by hand: frames run only on `tick`. */
function manualClock() {
  let t = 0;
  let next = 1;
  const queue = new Map<number, (t: number) => void>();
  const clock: TweenClock = {
    now: () => t,
    request: (cb) => { const id = next++; queue.set(id, cb); return id; },
    cancel: (id) => { queue.delete(id); },
  };
  const tick = (ms: number) => {
    t += ms;
    const due = [...queue.values()];
    queue.clear();
    for (const cb of due) cb(t);
  };
  return { clock, tick, pending: () => queue.size };
}

function stubReducedMotion(reduce: boolean) {
  const mm = window.matchMedia;
  window.matchMedia = ((q: string) => ({ matches: reduce && q.includes("reduce"), media: q })) as unknown as typeof window.matchMedia;
  return () => { window.matchMedia = mm; };
}

afterEach(() => vi.restoreAllMocks());

describe("FLIP math", () => {
  it("measures the offset between box centers", () => {
    const first = { left: 0, top: 100, width: 20, height: 40 };
    const last = { left: 100, top: 0, width: 60, height: 80 };
    expect(centerDelta(first, last)).toEqual({ dx: 10 - 130, dy: 120 - 40 });
    expect(centerDelta(last, last)).toEqual({ dx: 0, dy: 0 });
  });

  it("unions boxes and refuses an empty list", () => {
    expect(unionBox([])).toBeNull();
    expect(unionBox([
      { left: 10, top: 5, width: 10, height: 10 },
      { left: 30, top: 0, width: 5, height: 30 },
    ])).toEqual({ left: 10, top: 0, width: 25, height: 30 });
  });

  it("starts a flight at the origin and ends exactly at rest", () => {
    const frames = flightKeyframes({ dx: -200, dy: 0 }, -8, 1.4);
    expect(frames[0].offset).toBe(0);
    expect(frames[0].transform).toBe("translate(-200px, 0px) rotate(-8deg) scale(1.4)");
    expect(frames[frames.length - 1]).toEqual({ offset: 1, transform: "none" });
  });

  it("bows every arc upward", () => {
    for (const from of [{ dx: -200, dy: 0 }, { dx: 200, dy: 0 }, { dx: 0, dy: 300 }, { dx: 150, dy: 250 }]) {
      const mid = flightKeyframes(from, 0, 1, 2)[1].transform as string;
      const [, , y] = /translate\((-?[\d.]+)px, (-?[\d.]+)px\)/.exec(mid)!.map(Number);
      // the straight-line midpoint is from.dy / 2; the arc sits above it
      expect(y).toBeLessThanOrEqual(from.dy / 2);
    }
  });

  it("sweeps through the winner's play to the seat and fades", () => {
    const frames = sweepKeyframes({ dx: 10, dy: -20 }, { dx: 300, dy: -400 });
    expect(frames[0]).toMatchObject({ transform: "none", opacity: 1 });
    expect(frames[1].transform).toContain("translate(10px, -20px)");
    expect(frames[2]).toMatchObject({ offset: 1, opacity: 0 });
    expect(frames[2].transform).toContain("translate(300px, -400px)");
  });

  it("reads the live translation of a running transform", () => {
    const el = document.createElement("div");
    vi.spyOn(window, "getComputedStyle").mockReturnValue({ transform: "matrix(1, 0, 0, 1, 12.5, -3)" } as CSSStyleDeclaration);
    expect(currentTranslate(el)).toEqual({ dx: 12.5, dy: -3 });
  });
});

describe("count-up tween", () => {
  it("lands exactly on the target and stops requesting frames", () => {
    const { clock, tick, pending } = manualClock();
    const seen: number[] = [];
    tweenNumber(0, 35, DUR.count, (v) => seen.push(v), clock);
    for (let i = 0; i < 40; i++) tick(16);
    expect(seen[seen.length - 1]).toBe(35);
    expect(seen.every((v, i) => i === 0 || v >= seen[i - 1])).toBe(true);
    expect(pending()).toBe(0);
  });

  it("is instant for a zero duration or an unchanged value", () => {
    const seen: number[] = [];
    tweenNumber(5, 20, 0, (v) => seen.push(v));
    tweenNumber(7, 7, 500, (v) => seen.push(v));
    expect(seen).toEqual([20, 7]);
  });

  it("stops updating once cancelled mid-roll", () => {
    const { clock, tick, pending } = manualClock();
    const seen: number[] = [];
    const cancel = tweenNumber(0, 100, 500, (v) => seen.push(v), clock);
    tick(100);
    const shown = seen.length;
    cancel();
    tick(100);
    tick(500);
    expect(seen.length).toBe(shown);
    expect(pending()).toBe(0);
  });

  it("eases out and clamps its input", () => {
    expect(easeOutCubic(0)).toBe(0);
    expect(easeOutCubic(1)).toBe(1);
    expect(easeOutCubic(2)).toBe(1);
    expect(easeOutCubic(0.5)).toBeGreaterThan(0.5);
  });
});

describe("reduced motion", () => {
  it("bypasses animation when the viewer asks for less motion", () => {
    const el = document.createElement("div");
    (el as unknown as { animate: () => void }).animate = () => {};
    const restore = stubReducedMotion(true);
    try {
      expect(prefersReducedMotion()).toBe(true);
      expect(canAnimate(el)).toBe(false);
    } finally {
      restore();
    }
    const restoreOff = stubReducedMotion(false);
    try {
      expect(canAnimate(el)).toBe(true);
    } finally {
      restoreOff();
    }
  });

  it("does nothing where the Web Animations API is missing", () => {
    expect(canAnimate(document.createElement("div"))).toBe(false);
    expect(canAnimate(null)).toBe(false);
  });
});
