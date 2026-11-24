import { act } from "react";
import { createRoot } from "react-dom/client";
import type { Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import RatingSparkline, { pointAt, sparkPath } from "./RatingSparkline";
import { setLanguageChoice } from "../i18n";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

it("maps the lowest rating to the bottom pad and the highest to the top pad, left to right", () => {
  const { line, last } = sparkPath([1000, 1100, 1050], 300, 56);
  expect(line).toBe("M0.0 50.0 L150.0 6.0 L300.0 28.0");
  expect(last).toEqual([300, 28]);
});

it("draws a flat history through the middle", () => {
  expect(sparkPath([1200, 1200, 1200], 300, 56).line).toBe("M0.0 28.0 L150.0 28.0 L300.0 28.0");
});

it("draws nothing for fewer than two rounds", () => {
  const host = document.createElement("div");
  const root = createRoot(host);
  act(() => root.render(<RatingSparkline history={[1000]} />));
  expect(host.innerHTML).toBe("");
  act(() => root.render(<RatingSparkline history={[]} />));
  expect(host.innerHTML).toBe("");
  act(() => root.unmount());
});

it("counts rounds as the history's steps: the server sends the rating before the first round, then one per round", () => {
  const host = document.createElement("div");
  const root = createRoot(host);
  const label = () => host.querySelector(".me-spark")!.getAttribute("aria-label");
  act(() => root.render(<RatingSparkline history={[1000, 1020]} />));
  expect(label()).toBe("Rating over your last 1 round, from 1,000 to 1,020");
  act(() => root.render(<RatingSparkline history={[1000, 1020, 1012]} />));
  expect(label()).toBe("Rating over your last 2 rounds, from 1,000 to 1,012");
  act(() => root.unmount());
});

describe("scrubbing", () => {
  // four points 300px wide: x 0, 100, 200, 300
  const HISTORY = [1000, 1020, 1012, 1040];
  const DAY = 86400;
  const now = Math.floor(new Date(2026, 10, 24, 15, 0).getTime() / 1000);
  const AT = [now - 30 * DAY, now - 9 * DAY, now - 9 * DAY + 600, now - 60];
  let host: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(2026, 10, 24, 16, 0));
    host = document.createElement("div");
    document.body.appendChild(host);
    root = createRoot(host);
    act(() => root.render(<RatingSparkline history={HISTORY} at={AT} />));
    const plot = chart();
    plot.getBoundingClientRect = () => ({ left: 10, top: 0, width: 300, height: 56, right: 310, bottom: 56, x: 10, y: 0, toJSON: () => ({}) });
  });
  afterEach(() => {
    act(() => root.unmount());
    host.remove();
    vi.useRealTimers();
    setLanguageChoice("system");
  });

  const chart = () => host.querySelector<HTMLElement>(".me-spark")!;
  const readout = () => host.querySelector<HTMLElement>(".me-spark-read")!;
  const pointer = (type: string, clientX: number) =>
    act(() => { chart().dispatchEvent(new MouseEvent(type, { bubbles: true, clientX, button: 0 })); });
  const dotLeft = () => host.querySelector<HTMLElement>(".me-spark-dot")!.style.left;

  it("rests on the latest point with no readout, the guide hidden and its name kept", () => {
    expect(readout().textContent).toBe("");
    expect(readout().getAttribute("aria-live")).toBe("polite");
    expect(host.querySelector(".me-spark-guide")).toBeNull();
    expect(dotLeft()).toBe("100%");
    expect(chart().getAttribute("aria-label")).toBe("Rating over your last 3 rounds, from 1,000 to 1,040");
    expect(chart().tabIndex).toBe(0);
  });

  it("a press then a drag picks the point under the finger: its rating, its change and its date", () => {
    pointer("pointerdown", 10 + 95);          // nearest x 100: the first round
    expect(readout().textContent).toBe("1,020 ▲20 · Nov 15");
    expect(dotLeft()).toBe(`${(100 / 300) * 100}%`);
    expect(host.querySelector<HTMLElement>(".me-spark-guide")!.style.left).toBe(dotLeft());
    pointer("pointermove", 10 + 210);         // x 200: down 8
    expect(readout().textContent).toBe("1,012 ▼8 · Nov 15");
    pointer("pointermove", 10 + 400);         // past the end: clamped to the latest, today
    expect(readout().textContent).toBe("1,040 ▲28 · Today");
    pointer("pointermove", -50);              // before the start: the rating before the first round
    expect(readout().textContent).toBe("1,000 · Oct 25");
    expect(chart().getAttribute("aria-label")).toBe("Rating over your last 3 rounds, from 1,000 to 1,040");
    expect(chart().textContent).toBe("");
  });

  it("releasing returns to rest", () => {
    pointer("pointerdown", 110);
    pointer("pointerup", 110);
    expect(readout().textContent).toBe("");
    expect(host.querySelector(".me-spark-guide")).toBeNull();
    expect(dotLeft()).toBe("100%");
    // a move with no press does nothing
    pointer("pointermove", 110);
    expect(readout().textContent).toBe("");
    // the browser taking the gesture for a scroll also ends it
    pointer("pointerdown", 110);
    pointer("pointercancel", 110);
    expect(readout().textContent).toBe("");
  });

  it("the arrow keys step through the points from the latest; Escape and blur rest", () => {
    const key = (k: string) =>
      act(() => { chart().dispatchEvent(new KeyboardEvent("keydown", { key: k, bubbles: true })); });
    act(() => chart().focus());
    key("ArrowLeft");
    expect(readout().textContent).toBe("1,012 ▼8 · Nov 15");
    key("ArrowLeft");
    key("ArrowLeft");
    key("ArrowLeft");                          // stops at the first point
    expect(readout().textContent).toBe("1,000 · Oct 25");
    key("ArrowRight");
    expect(readout().textContent).toBe("1,020 ▲20 · Nov 15");
    key("End");
    expect(readout().textContent).toBe("1,040 ▲28 · Today");
    key("Escape");
    expect(readout().textContent).toBe("");
    key("Home");
    expect(readout().textContent).toBe("1,000 · Oct 25");
    act(() => chart().blur());
    expect(readout().textContent).toBe("");
  });

  it("renders the server's dates in Chinese", () => {
    act(() => setLanguageChoice("zh-Hans"));
    pointer("pointerdown", 110);
    expect(readout().textContent).toBe("1,020 ▲20 · 11月15日");
    pointer("pointermove", 400);
    expect(readout().textContent).toBe("1,040 ▲28 · 今天");
  });

  it("an older server with no times still scrubs, without dates", () => {
    act(() => root.render(<RatingSparkline history={HISTORY} />));
    chart().getBoundingClientRect = () => ({ left: 0, top: 0, width: 300, height: 56, right: 300, bottom: 56, x: 0, y: 0, toJSON: () => ({}) });
    pointer("pointerdown", 100);
    expect(readout().textContent).toBe("1,020 ▲20");
  });
});

it("picks the nearest point and clamps outside the chart", () => {
  expect(pointAt(0, 4)).toBe(0);
  expect(pointAt(0.32, 4)).toBe(1);
  expect(pointAt(0.5, 4)).toBe(2);
  expect(pointAt(-1, 4)).toBe(0);
  expect(pointAt(2, 4)).toBe(3);
});
