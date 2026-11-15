// The phone home pages' large title, which collapses into a compact bar on
// scroll, and their pull to refresh; at 700px and up neither is drawn.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import Leaderboard from "../components/Leaderboard";
import { auth } from "../auth";
import { forgetHomeSession } from "./session";
import { WIDE } from "./route";
import { PULL_MIN_MS, rubberBand } from "./usePullToRefresh";

vi.mock("../ws", () => ({ conn: { send: () => {}, reconnect: () => {} } }));

const BOARD = {
  period: "week",
  players: [{ rank: 1, name: "Ann", rating: 1700, rounds: 120, levels_per_round: 0.3, week_delta: 4,
              provisional: false, you: false }],
  me: null,
  anchor: { name: "Sheng Ji bot", rating: 1500 },
};

let board: () => Promise<unknown>;
let calls: string[];
let media: { wide: boolean; reduce: boolean };
let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
const realMatchMedia = window.matchMedia;

beforeEach(() => {
  forgetHomeSession();
  auth.reset();
  calls = [];
  media = { wide: false, reduce: false };
  board = async () => BOARD;
  window.matchMedia = ((q: string) => ({
    matches: q === WIDE ? media.wide : q.includes("reduce") ? media.reduce : false,
    media: q, addEventListener: () => {}, removeEventListener: () => {},
  })) as unknown as typeof window.matchMedia;
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    calls.push(url);
    if (url === "/api/auth/config") return { status: 200, json: async () => ({ google_client_id: "" }) } as Response;
    if (url === "/api/me") return { status: 401, json: async () => ({}) } as Response;
    const body = await board();
    return { status: 200, json: async () => body } as Response;
  }) as typeof fetch;
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  auth.reset();
  window.matchMedia = realMatchMedia;
});

const wait = (ms: number) => act(async () => { await new Promise((r) => setTimeout(r, ms)); });
async function render() {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => { root.render(<Leaderboard />); });
  await wait(0);
}
const page = () => host.querySelector<HTMLDivElement>(".lb-page")!;
const boardCalls = () => calls.filter((c) => c.startsWith("/api/leaderboard")).length;

function touch(type: string, x: number, y: number, el: Element = page()) {
  const e = new Event(type, { bubbles: true, cancelable: true });
  const list = type === "touchend" || type === "touchcancel" ? [] : [{ clientX: x, clientY: y }];
  Object.defineProperty(e, "touches", { value: list });
  act(() => { el.dispatchEvent(e); });
  return e;
}
/** A drag from (x, 100) down by `dy` in steps, then a release. */
function pull(dy: number, x = 150, release = true) {
  touch("touchstart", x, 100);
  for (let y = 10; y < dy; y += 10) touch("touchmove", x, 100 + y);
  const last = touch("touchmove", x, 100 + dy);
  if (release) touch("touchend", 0, 0);
  return last;
}
/** The raw drag that resistance turns into `px`. */
const rawFor = (px: number) => px / (1 - px / 320);

function boxes(barBottom: number, titleBottom: number) {
  const rect = (bottom: number) => () => ({ bottom, top: bottom - 40, left: 0, right: 0, width: 0, height: 40, x: 0, y: 0,
                                             toJSON: () => ({}) }) as DOMRect;
  host.querySelector(".nav-bar")!.getBoundingClientRect = rect(barBottom);
  host.querySelector(".large-title")!.getBoundingClientRect = rect(titleBottom);
}

it("collapses the large title into the bar once it scrolls under it, and back", async () => {
  await render();
  const bar = host.querySelector(".nav-bar")!;
  expect(bar.className).toBe("nav-bar");
  expect(bar.querySelector(".nav-bar-title")?.textContent).toBe("Leaderboard");
  expect(host.querySelector("h1.large-title")?.textContent).toBe("Leaderboard");
  boxes(44, 90);
  act(() => { page().dispatchEvent(new Event("scroll")); });
  await wait(40);
  expect(bar.classList.contains("collapsed")).toBe(false);
  boxes(44, 44);
  act(() => { page().dispatchEvent(new Event("scroll")); });
  await wait(40);
  expect(bar.classList.contains("collapsed")).toBe(true);
  boxes(44, 60);
  act(() => { page().dispatchEvent(new Event("scroll")); });
  await wait(40);
  expect(bar.classList.contains("collapsed")).toBe(false);
});

it("refreshes once on a release past the threshold, never below it", async () => {
  await render();
  expect(boardCalls()).toBe(1);
  pull(rawFor(60));
  await wait(PULL_MIN_MS + 50);
  expect(boardCalls()).toBe(1);
  const move = pull(rawFor(70));
  expect(move.defaultPrevented).toBe(true);
  await wait(PULL_MIN_MS + 50);
  expect(boardCalls()).toBe(2);
});

it("leaves mouse and pen drags, the left-edge swipe, sideways drags and a scrolled page alone", async () => {
  await render();
  const el = page();
  for (const pointerType of ["mouse", "pen"]) {
    for (const [type, y] of [["pointerdown", 100], ["pointermove", 300], ["pointerup", 300]] as const) {
      const e = new Event(type, { bubbles: true });
      Object.assign(e, { pointerType, clientX: 150, clientY: y });
      act(() => { el.dispatchEvent(e); });
    }
  }
  for (const [type, y] of [["mousedown", 100], ["mousemove", 300], ["mouseup", 300]] as const) {
    act(() => { el.dispatchEvent(new MouseEvent(type, { bubbles: true, clientX: 150, clientY: y })); });
  }
  pull(300, 10);
  touch("touchstart", 150, 100);
  touch("touchmove", 300, 130);
  touch("touchmove", 300, 400);
  touch("touchend", 0, 0);
  el.scrollTop = 40;
  pull(300);
  el.scrollTop = 0;
  await wait(PULL_MIN_MS + 50);
  expect(boardCalls()).toBe(1);
  expect(el.className).not.toContain("ptr-on");
});

it("keeps the spinner until the reload settles, and at least the minimum time", async () => {
  await render();
  let finish: () => void = () => {};
  board = () => new Promise((r) => { finish = () => r(BOARD); });
  pull(rawFor(80));
  const el = page();
  expect(el.classList.contains("ptr-refreshing")).toBe(true);
  expect(host.querySelector(".ptr")?.getAttribute("role")).toBe("status");
  expect(el.style.getPropertyValue("--ptr")).toBe("52px");
  await wait(PULL_MIN_MS + 100);
  expect(el.classList.contains("ptr-refreshing")).toBe(true);
  // a second pull while reloading starts nothing
  pull(rawFor(80));
  expect(boardCalls()).toBe(2);
  await act(async () => { finish(); });
  await wait(0);
  expect(el.classList.contains("ptr-refreshing")).toBe(false);
  expect(el.style.getPropertyValue("--ptr")).toBe("0px");
  await wait(350);
  expect(el.className).not.toContain("ptr-on");

  // a fast reload still shows the spinner for the minimum time
  board = async () => BOARD;
  pull(rawFor(80));
  await wait(PULL_MIN_MS / 2);
  expect(el.classList.contains("ptr-refreshing")).toBe(true);
  await wait(PULL_MIN_MS);
  expect(el.classList.contains("ptr-refreshing")).toBe(false);
});

it("follows the finger with resistance and marks the threshold", async () => {
  await render();
  const el = page();
  pull(40, 150, false);
  expect(el.style.getPropertyValue("--ptr")).toBe(`${rubberBand(40)}px`);
  expect(el.className).toContain("ptr-drag");
  expect(el.className).not.toContain("ptr-armed");
  touch("touchmove", 150, 100 + rawFor(70));
  expect(el.className).toContain("ptr-armed");
  touch("touchcancel", 0, 0);
  expect(el.style.getPropertyValue("--ptr")).toBe("0px");
  expect(el.className).not.toContain("ptr-drag");
  expect(boardCalls()).toBe(1);
  expect(rubberBand(100)).toBeLessThan(100);
});

it("under Reduce Motion animates nothing: no transitions, no easing back", async () => {
  media.reduce = true;
  await render();
  const el = page();
  expect(el.className).toContain("has-nav");
  expect(el.className).not.toContain("nav-animate");
  pull(rawFor(40));
  expect(el.className).not.toContain("ptr-on");
  media.reduce = false;
});

it("draws no bar and takes no pull at 700px and up", async () => {
  media.wide = true;
  await render();
  const el = page();
  expect(el.className).toBe("screen home-page lb-page");
  expect(host.querySelector(".nav-bar")).toBeNull();
  expect(host.querySelector(".ptr")).toBeNull();
  expect(el.firstElementChild?.className).toBe("home-col");
  expect(host.querySelector(".home-col > h1.large-title")?.textContent).toBe("Leaderboard");
  pull(rawFor(100));
  await wait(PULL_MIN_MS + 50);
  expect(boardCalls()).toBe(1);
});
