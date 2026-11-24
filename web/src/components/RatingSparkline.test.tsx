import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it } from "vitest";
import RatingSparkline, { sparkPath } from "./RatingSparkline";

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
