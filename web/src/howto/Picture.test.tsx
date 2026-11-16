// The guide's animated pictures: autoplay once, hold the last frame, the
// controls, a hidden tab, re-entry, and the still image under reduced motion,
// on the toggle and when an animation throws.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import HowTo from "./HowTo";
import Picture from "./Picture";
import { useHowtoRoute } from "./route";

function Guide() {
  const route = useHowtoRoute();
  return route ? <HowTo route={route} /> : null;
}

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
let reduced = false;
const motionListeners = new Set<(e: { matches: boolean }) => void>();
/** The viewer turns Reduce Motion on or off while the page is open. */
function setReduced(on: boolean) {
  reduced = on;
  act(() => { for (const l of [...motionListeners]) l({ matches: on }); });
}

function mount(node: React.ReactNode) {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  act(() => root.render(node));
}
function open(step: number) {
  window.history.replaceState(null, "", `/#/howto/${step}`);
  mount(<Guide />);
}
const advance = (ms: number) => act(() => { vi.advanceTimersByTime(ms); });
const visual = () => host.querySelector<HTMLElement>(".howto-visual")!;
const isStill = () => visual().dataset.still === "true";
const plays = () => host.querySelectorAll(".trick-play").length;
const btn = (label: string) => host.querySelector<HTMLButtonElement>(`button[aria-label='${label}']`);
const click = (el: HTMLElement | null) => { expect(el).toBeTruthy(); act(() => el!.click()); };
const frameHtml = () => host.querySelector(".howto-frame, .howto-visual")!.innerHTML.replace(/<div class="howto-anim-controls">.*?<\/div>/, "");

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "Date", "performance"] });
  reduced = false;
  motionListeners.clear();
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    value: (q: string) => ({
      matches: reduced && q.includes("reduce"), media: q,
      addEventListener(_: string, l: (e: { matches: boolean }) => void) { if (q.includes("reduce")) motionListeners.add(l); },
      removeEventListener(_: string, l: (e: { matches: boolean }) => void) { motionListeners.delete(l); },
    }),
  });
});
afterEach(() => {
  act(() => root?.unmount());
  host?.remove();
  vi.useRealTimers();
  // @ts-expect-error: restore jsdom's missing matchMedia
  delete window.matchMedia;
  window.history.replaceState(null, "", "/");
});

describe("an animated slide", () => {
  it("plays once in seat order and holds the finished trick, Cal winning", () => {
    open(5);
    expect(isStill()).toBe(false);
    expect(plays()).toBe(0);
    expect(btn("Pause animation")).not.toBeNull();
    advance(1100);
    expect([...host.querySelectorAll<HTMLElement>(".trick-play")].map((e) => e.dataset.seat)).toEqual(["1", "2"]);
    advance(3000);
    expect([...host.querySelectorAll<HTMLElement>(".trick-play")].map((e) => e.dataset.seat)).toEqual(["1", "2", "3", "0"]);
    expect(host.querySelector(".trick-play.winner")?.getAttribute("data-seat")).toBe("3");
    advance(10_000);
    expect(plays()).toBe(4);                       // holds, never clears the table
    expect(btn("Play animation")).not.toBeNull();  // done: play means replay
  });

  it("every slide runs 3-5 s and its last frame is exactly its still image", () => {
    for (let step = 1; step <= 10; step++) {
      open(step);
      advance(2500);
      expect(btn("Pause animation"), `step ${step} still playing at 2.5 s`).not.toBeNull();
      advance(2500);
      expect(btn("Play animation"), `step ${step} done by 5 s`).not.toBeNull();
      const last = frameHtml();
      click(btn("Show still image"));
      expect(isStill()).toBe(true);
      expect(frameHtml(), `step ${step}`).toBe(last);
      act(() => root.unmount());
      host.remove();
    }
  });

  it("pause freezes it, play resumes, replay starts over", () => {
    open(5);
    advance(1100);
    click(btn("Pause animation"));
    advance(5000);
    expect(plays()).toBe(2);
    click(btn("Play animation"));
    advance(5000);
    expect(plays()).toBe(4);
    click(btn("Replay animation"));
    expect(plays()).toBe(0);
    advance(400);
    expect(plays()).toBe(1);
  });

  it("a hidden tab pauses it and showing the tab resumes it", () => {
    open(5);
    advance(1100);
    const setHidden = (h: boolean) => {
      Object.defineProperty(document, "hidden", { configurable: true, get: () => h });
      act(() => { document.dispatchEvent(new Event("visibilitychange")); });
    };
    setHidden(true);
    advance(5000);
    expect(plays()).toBe(2);
    expect(btn("Play animation")).not.toBeNull();
    setHidden(false);
    advance(5000);
    expect(plays()).toBe(4);
    // @ts-expect-error: back to jsdom's own getter
    delete document.hidden;
  });

  it("leaving a slide stops it and coming back starts it afresh", () => {
    open(5);
    advance(5000);
    expect(plays()).toBe(4);
    act(() => { window.location.hash = "#/howto/6"; window.dispatchEvent(new HashChangeEvent("hashchange")); });
    expect(host.querySelector(".howto-title")?.textContent).toBe("Pairs and tractors");
    expect(host.querySelectorAll(".howto-group.howto-in").length).toBe(0);   // step 6 starts from nothing too
    act(() => { window.location.hash = "#/howto/5"; window.dispatchEvent(new HashChangeEvent("hashchange")); });
    expect(host.querySelector(".howto-title")?.textContent).toBe("Play a trick");
    expect(plays()).toBe(0);
    expect(btn("Pause animation")).not.toBeNull();
    advance(400);
    expect(plays()).toBe(1);
  });
});

describe("the still image", () => {
  it("shows under reduced motion, with nothing playing", () => {
    reduced = true;
    open(5);
    expect(isStill()).toBe(true);
    expect(plays()).toBe(4);
    expect(host.querySelector(".trick-play.winner")?.getAttribute("data-seat")).toBe("3");
    expect(btn("Show still image")!.getAttribute("aria-pressed")).toBe("true");
    expect(btn("Play animation")).not.toBeNull();
    advance(10_000);
    expect(plays()).toBe(4);
    click(btn("Play animation"));                  // the viewer can still ask for it
    expect(isStill()).toBe(false);
    expect(plays()).toBe(0);
  });

  it("turning Reduce Motion on mid-play stops the timeline on the still; Replay still plays", () => {
    open(5);
    advance(1100);
    expect(plays()).toBe(2);
    setReduced(true);
    expect(isStill()).toBe(true);
    expect(plays()).toBe(4);
    const still = frameHtml();
    advance(5000);
    expect(frameHtml()).toBe(still);               // no frame advances after the switch
    expect(btn("Show still image")!.getAttribute("aria-pressed")).toBe("true");
    click(btn("Replay animation"));                // a deliberate replay still runs
    expect(isStill()).toBe(false);
    expect(plays()).toBe(0);
    advance(1100);
    expect(plays()).toBe(2);
    setReduced(false);                             // turning it off changes nothing by itself
    expect(isStill()).toBe(false);
  });

  it("a slide entered under Reduce Motion stays still", () => {
    reduced = true;
    open(1);
    const still = frameHtml();
    expect(isStill()).toBe(true);
    advance(6000);
    expect(frameHtml()).toBe(still);
  });

  it("the toggle swaps to the still and back to a fresh run", () => {
    open(5);
    advance(1100);
    const toggle = btn("Show still image")!;
    expect(toggle.getAttribute("aria-pressed")).toBe("false");
    click(toggle);
    expect(isStill()).toBe(true);
    expect(btn("Show still image")!.getAttribute("aria-pressed")).toBe("true");
    expect(plays()).toBe(4);
    advance(5000);
    expect(plays()).toBe(4);
    click(btn("Show still image"));
    expect(isStill()).toBe(false);
    expect(plays()).toBe(0);
  });

  it("replaces an animation that throws, instead of a blank panel", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const error = vi.spyOn(console, "error").mockImplementation(() => {});
    const frames = [{ at: 0, state: 0 }, { at: 500, state: 1 }, { at: 1000, state: 2 }];
    mount(<Picture frames={frames} still={2} render={(n) => {
      if (n === 1) throw new Error("broken frame");
      return <span className="pic">frame {n}</span>;
    }} />);
    expect(host.querySelector(".pic")?.textContent).toBe("frame 0");
    advance(600);
    expect(isStill()).toBe(true);
    expect(host.querySelector(".pic")?.textContent).toBe("frame 2");
    expect(warn).toHaveBeenCalled();
    act(() => root.unmount());
    host.remove();

    mount(<Picture frames={[]} still={2} render={(n) => <span className="pic">frame {n}</span>} />);
    expect(isStill()).toBe(true);
    expect(host.querySelector(".pic")?.textContent).toBe("frame 2");
    warn.mockRestore();
    error.mockRestore();
  });
});
