// A lobby error is about the tab it came from: switching tabs takes it down,
// so it never covers the next page's title. A notice keeps its time.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it } from "vitest";
import HomeShell from "./HomeShell";
import type { Tab } from "./route";
import { clearToast, currentToast, showToast } from "../toast";

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
const draw = (active: Tab) => act(() => root.render(<HomeShell active={active}><p>page</p></HomeShell>));

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  clearToast();
});

it("clears an error toast when the tab changes", () => {
  draw("play");
  act(() => { showToast("No table has that code."); });
  draw("play");
  expect(currentToast()?.text).toBe("No table has that code.");
  draw("leaderboard");
  expect(currentToast()).toBeNull();
});

it("leaves a notice up across a tab change", () => {
  draw("play");
  act(() => { showToast("Alice joined.", { info: true }); });
  draw("me");
  expect(currentToast()?.text).toBe("Alice joined.");
});
