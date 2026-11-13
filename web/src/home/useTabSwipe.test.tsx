// A phone's sideways swipe between the home tabs: Play, Leaderboard and Me in
// the tab bar's order, by touch only, away from the screen edges and the
// controls that keep their own gestures; at 700px and up nothing swipes.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { auth } from "../auth";
import HomeShell, { TAB_FADE_MS } from "./HomeShell";
import { WIDE, useHomeRoute } from "./route";
import { forgetHomeSession } from "./session";
import { SWIPE_SETTLE_MS, edgeBand } from "./useTabSwipe";

vi.mock("../ws", () => ({ conn: { send: () => {}, reconnect: () => {} } }));

const W = 393;
let media: { wide: boolean; reduce: boolean };
let clock: number;
let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
const realMatchMedia = window.matchMedia;
const realWidth = window.innerWidth;

function Harness() {
  const route = useHomeRoute();
  return (
    <HomeShell active={route?.tab ?? "play"}>
      <div className="screen home-page">
        <p className="plain">page</p>
        <input className="field" />
        <div className="segmented"><button type="button" className="seg">A</button></div>
        <div className="lobby-preview"><span className="lp">table</span></div>
        <div data-no-tab-swipe=""><span className="marked">x</span></div>
        <div className="strip" style={{ overflowX: "auto" }}><button type="button" className="chip">c</button></div>
      </div>
    </HomeShell>
  );
}

beforeEach(async () => {
  forgetHomeSession();
  auth.reset();
  media = { wide: false, reduce: false };
  clock = 1000;
  vi.spyOn(performance, "now").mockImplementation(() => clock);
  Object.defineProperty(window, "innerWidth", { value: W, configurable: true });
  window.history.replaceState(null, "", "/");
  window.matchMedia = ((q: string) => ({
    matches: q === WIDE ? media.wide : q.includes("reduce") ? media.reduce : false,
    media: q, addEventListener: () => {}, removeEventListener: () => {},
  })) as unknown as typeof window.matchMedia;
  globalThis.fetch = vi.fn(async () => ({ status: 401, json: async () => ({}) }) as Response) as typeof fetch;
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  document.querySelectorAll(".q-layer").forEach((n) => n.remove());
  auth.reset();
  vi.restoreAllMocks();
  window.matchMedia = realMatchMedia;
  Object.defineProperty(window, "innerWidth", { value: realWidth, configurable: true });
});

async function render() {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => { root.render(<Harness />); });
  const strip = host.querySelector<HTMLElement>(".strip")!;
  Object.defineProperty(strip, "scrollWidth", { value: 600, configurable: true });
  Object.defineProperty(strip, "clientWidth", { value: 300, configurable: true });
}
const body = () => host.querySelector<HTMLElement>(".home-body")!;
const shift = () => body().style.getPropertyValue("--tab-swipe-x");
const onTab = () => host.querySelector(".tabbar-item.on")?.textContent;
const wait = (ms: number) => act(async () => { await new Promise((r) => setTimeout(r, ms)); });

function touch(type: string, x: number, y: number, el: Element) {
  const e = new Event(type, { bubbles: true, cancelable: true });
  const list = type === "touchend" || type === "touchcancel" ? [] : [{ clientX: x, clientY: y }];
  Object.defineProperty(e, "touches", { value: list });
  act(() => { el.dispatchEvent(e); });
  return e;
}
/** A drag from (x, 300) by `dx` in ten steps over `ms`; returns every move. */
function swipe(dx: number, { x = 200, ms = 500, on = ".plain", release = true, dy = 0 } = {}) {
  const el = host.querySelector(on)!;
  touch("touchstart", x, 300, el);
  const moves: Event[] = [];
  for (let i = 1; i <= 10; i++) {
    clock += ms / 10;
    moves.push(touch("touchmove", x + (dx * i) / 10, 300 + (dy * i) / 10, el));
  }
  if (release) touch("touchend", 0, 0, el);
  return moves;
}

it("walks Play, Leaderboard and Me with leftward swipes past the threshold, and back", async () => {
  await render();
  expect(onTab()).toBe("Play");
  swipe(-150);
  expect(window.location.hash).toBe("#/leaderboard");
  expect(onTab()).toBe("Leaderboard");
  swipe(-150);
  expect(window.location.hash).toBe("#/me");
  expect(onTab()).toBe("Me");
  swipe(150);
  expect(window.location.hash).toBe("#/leaderboard");
  swipe(150);
  expect(window.location.hash).toBe("");
  expect(onTab()).toBe("Play");
});

it("follows the finger, then the new page slides in from beside and comes to rest", async () => {
  await render();
  const el = host.querySelector(".plain")!;
  touch("touchstart", 200, 300, el);
  expect(touch("touchmove", 194, 301, el).defaultPrevented).toBe(false);
  expect(touch("touchmove", 120, 302, el).defaultPrevented).toBe(true);
  clock += 400;
  touch("touchmove", 50, 303, el);
  expect(body().dataset.tabSwipe).toBe("drag");
  expect(shift()).toBe("-150px");
  touch("touchend", 0, 0, body());
  expect(window.location.hash).toBe("#/leaderboard");
  expect(body().dataset.tabSwipe).toBe("settle");
  expect(shift()).toBe("0px");
  await wait(SWIPE_SETTLE_MS + 20);
  expect(body().dataset.tabSwipe).toBeUndefined();
  expect(shift()).toBe("");
});

it("springs back from a short slow drag", async () => {
  await render();
  swipe(-100);
  expect(window.location.hash).toBe("");
  expect(body().dataset.tabSwipe).toBe("settle");
  expect(shift()).toBe("0px");
  await wait(SWIPE_SETTLE_MS + 20);
  expect(body().dataset.tabSwipe).toBeUndefined();
});

it("takes a fast flick however short, but not one that turned back", async () => {
  await render();
  swipe(-60, { ms: 60 });
  expect(window.location.hash).toBe("#/leaderboard");
  const el = host.querySelector(".plain")!;
  touch("touchstart", 200, 300, el);
  for (const x of [230, 260, 290]) { clock += 50; touch("touchmove", x, 300, el); }
  for (const x of [270, 250]) { clock += 20; touch("touchmove", x, 300, el); }
  touch("touchend", 0, 0, el);
  expect(window.location.hash).toBe("#/leaderboard");
});

it("ignores a swipe that starts at either screen edge", async () => {
  await render();
  swipe(200, { x: 10 });
  swipe(-200, { x: W - 10 });
  expect(window.location.hash).toBe("");
  expect(body().dataset.tabSwipe).toBeUndefined();
});

it("leaves a vertical-first gesture to the scroller", async () => {
  await render();
  const el = host.querySelector(".plain")!;
  touch("touchstart", 200, 300, el);
  const down = touch("touchmove", 203, 330, el);
  const across = touch("touchmove", 50, 340, el);
  touch("touchend", 0, 0, el);
  expect(down.defaultPrevented).toBe(false);
  expect(across.defaultPrevented).toBe(false);
  expect(window.location.hash).toBe("");
  swipe(-30, { dy: 200 });
  expect(window.location.hash).toBe("");
});

it("ignores swipes that start on inputs, segments, the table preview, side scrollers or marked elements", async () => {
  await render();
  for (const on of [".field", ".seg", ".lp", ".marked", ".chip"]) {
    const moves = swipe(-200, { on });
    expect(moves[9].defaultPrevented, on).toBe(false);
  }
  expect(window.location.hash).toBe("");
});

it("never swipes while a sheet is open", async () => {
  await render();
  const layer = document.createElement("div");
  layer.className = "q-layer";
  document.body.appendChild(layer);
  swipe(-200);
  expect(window.location.hash).toBe("");
});

it("ignores mouse and pen pointers", async () => {
  await render();
  const el = host.querySelector(".plain")!;
  for (const pointerType of ["mouse", "pen"]) {
    const fire = (type: string, x: number) => {
      const e = new MouseEvent(type, { bubbles: true, cancelable: true, clientX: x, clientY: 300 });
      Object.defineProperty(e, "pointerType", { value: pointerType });
      act(() => { el.dispatchEvent(e); });
    };
    fire("pointerdown", 200);
    fire("mousedown", 200);
    for (let x = 190; x >= 0; x -= 10) { clock += 30; fire("pointermove", x); fire("mousemove", x); }
    fire("pointerup", 0);
    fire("mouseup", 0);
  }
  expect(window.location.hash).toBe("");
  expect(body().dataset.tabSwipe).toBeUndefined();
});

it("rubber-bands past the first and last tab without switching", async () => {
  await render();
  swipe(200, { release: false });
  expect(shift()).toBe(`${edgeBand(200, W)}px`);
  expect(edgeBand(200, W)).toBeLessThan(100);
  touch("touchend", 0, 0, body());
  expect(window.location.hash).toBe("");
  window.history.replaceState(null, "", "/#/me");
  act(() => { window.dispatchEvent(new HashChangeEvent("hashchange")); });
  expect(onTab()).toBe("Me");
  swipe(-250, { ms: 50 });
  expect(window.location.hash).toBe("#/me");
});

it("under Reduce Motion never moves the page and switches at once", async () => {
  media.reduce = true;
  await render();
  swipe(-150, { release: false });
  expect(body().dataset.tabSwipe).toBeUndefined();
  expect(shift()).toBe("");
  touch("touchend", 0, 0, body());
  expect(window.location.hash).toBe("#/leaderboard");
  expect(body().dataset.tabSwipe).toBeUndefined();
  swipe(-60);
  expect(window.location.hash).toBe("#/leaderboard");
  expect(body().dataset.tabSwipe).toBeUndefined();
});

it("does nothing at 700px and up", async () => {
  media.wide = true;
  await render();
  const moves = swipe(-200);
  expect(moves[9].defaultPrevented).toBe(false);
  expect(window.location.hash).toBe("");
  expect(body().dataset.tabSwipe).toBeUndefined();
});

it("does not commit a short flick after the finger stops for a second", async () => {
  await render();
  swipe(-40, { ms: 40, release: false });
  clock += 1000;
  touch("touchend", 160, 300, host.querySelector(".plain")!);
  expect(onTab()).toBe("Play");
});
it("settles a horizontal drag when a second finger touches down", async () => {
  await render();
  swipe(-40, { ms: 500, release: false });
  const e = new Event("touchstart", { bubbles: true, cancelable: true });
  Object.defineProperty(e, "touches", { value: [{clientX:160,clientY:300},{clientX:220,clientY:300}] });
  act(() => host.querySelector(".plain")!.dispatchEvent(e));
  touch("touchend", 0, 0, host.querySelector(".plain")!);
  await wait(SWIPE_SETTLE_MS + 30);
  expect(shift()).toBe("");
  expect(body().dataset.tabSwipe).toBeUndefined();
});

it("still commits a drag past the threshold that paused before the release", async () => {
  await render();
  swipe(-150, { ms: 150, release: false });
  clock += 1000;
  touch("touchend", 0, 0, body());
  expect(onTab()).toBe("Leaderboard");
  expect(window.location.hash).toBe("#/leaderboard");
});

it("springs back and clears the page's offset when the system cancels a drag", async () => {
  await render();
  swipe(-150, { release: false });
  expect(body().dataset.tabSwipe).toBe("drag");
  touch("touchcancel", 0, 0, body());
  expect(window.location.hash).toBe("");
  expect(body().dataset.tabSwipe).toBe("settle");
  expect(shift()).toBe("0px");
  await wait(SWIPE_SETTLE_MS + 30);
  expect(shift()).toBe("");
  expect(body().dataset.tabSwipe).toBeUndefined();
});

it("fades the new page in for 150 ms when a tab is tapped, but not after a swipe, on first load or under Reduce Motion", async () => {
  const animate = vi.fn();
  Object.defineProperty(HTMLElement.prototype, "animate", { value: animate, configurable: true, writable: true });
  try {
    await render();
    expect(animate).not.toHaveBeenCalled();
    act(() => { host.querySelectorAll<HTMLElement>(".tabbar-item")[1].click(); });
    expect(animate).toHaveBeenCalledTimes(1);
    expect(animate.mock.instances[0]).toBe(host.querySelector(".home-body > .screen"));
    expect(animate.mock.calls[0][0]).toEqual([{ opacity: 0 }, { opacity: 1 }]);
    expect(animate.mock.calls[0][1]).toMatchObject({ duration: TAB_FADE_MS });
    swipe(-150);
    expect(onTab()).toBe("Me");
    expect(animate).toHaveBeenCalledTimes(1);
    await wait(SWIPE_SETTLE_MS + 20);
    media.reduce = true;
    act(() => { host.querySelectorAll<HTMLElement>(".tabbar-item")[0].click(); });
    expect(onTab()).toBe("Play");
    expect(animate).toHaveBeenCalledTimes(1);
  } finally {
    delete (HTMLElement.prototype as { animate?: unknown }).animate;
  }
});
