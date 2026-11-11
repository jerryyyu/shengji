// The lobby's live preview: real cards, a loop that keeps advancing, sleep
// while the page is hidden or the box is off screen, and one still frame
// with no timers under reduced motion.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import LobbyPreview, { FRAMES, STILL, TRICKS } from "./LobbyPreview";

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
let reduced = false;
let hidden = false;
let observed: ((entries: { isIntersecting: boolean }[]) => void) | null = null;

const LOOP = FRAMES[FRAMES.length - 1].at;
const advance = (ms: number) => act(() => { vi.advanceTimersByTime(ms); });
const box = () => host.querySelector<HTMLElement>(".lobby-preview")!;
const stage = () => host.querySelector<HTMLElement>(".lp-stage")!;
/** Cards on the felt: played (visible), not in the hands. */
const onFelt = () => [...host.querySelectorAll<HTMLElement>(".lp-x")].filter((e) => e.style.opacity === "1");
const faces = () => [...host.querySelectorAll<HTMLElement>(".lp-face")].map((e) => e.getAttribute("title"));
const setHidden = (h: boolean) => {
  hidden = h;
  act(() => { document.dispatchEvent(new Event("visibilitychange")); });
};

function mount() {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  act(() => root.render(<LobbyPreview />));
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "Date", "performance"] });
  reduced = false;
  hidden = false;
  observed = null;
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    value: (q: string) => ({ matches: reduced && q.includes("reduce"), media: q, addEventListener() {}, removeEventListener() {} }),
  });
  Object.defineProperty(document, "hidden", { configurable: true, get: () => hidden });
  vi.stubGlobal("IntersectionObserver", class {
    constructor(cb: (entries: { isIntersecting: boolean }[]) => void) { observed = cb; }
    observe() {}
    disconnect() {}
  });
});
afterEach(() => {
  act(() => root?.unmount());
  host?.remove();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  // @ts-expect-error: restore jsdom's missing matchMedia
  delete window.matchMedia;
  // @ts-expect-error: back to jsdom's own document.hidden
  delete document.hidden;
});

describe("the lobby preview", () => {
  it("is decoration drawn with the table's cards, no video", () => {
    mount();
    expect(box().getAttribute("aria-hidden")).toBe("true");
    expect(host.querySelector("video")).toBeNull();
    expect(host.querySelectorAll(".lp-fan .card.back").length).toBe(28);
    expect(faces()).toEqual(["♣10", "♣K", "♣A", "♣7"]);
  });

  it("plays the tricks in seat order, shows the winner, then loops", () => {
    mount();
    expect(onFelt().length).toBe(0);
    advance(FRAMES.find((f) => f.state.played === 2)!.at);
    expect(onFelt().map((e) => e.dataset.seat)).toEqual(["top", "right"]);
    advance(FRAMES.find((f) => f.state.phase === "won")!.at - FRAMES.find((f) => f.state.played === 2)!.at);
    expect(stage().dataset.phase).toBe("won");
    expect(host.querySelector(".lp-flip.win")!.closest<HTMLElement>(".lp-x")!.dataset.seat).toBe(TRICKS[0].winner);
    expect(host.querySelector(".win-tag.shown")).not.toBeNull();
    const second = FRAMES.find((f) => f.state.trick === 1)!.at;
    advance(second - FRAMES.find((f) => f.state.phase === "won")!.at);
    expect(faces()).toContain("♥Q");
    // Past the end it starts over at the first trick rather than holding.
    advance(LOOP - second + 50);
    expect(box().dataset.status).toBe("playing");
    expect(faces()).toContain("♣A");
    advance(LOOP);
    expect(box().dataset.status).toBe("playing");
  });

  it("pauses while the page is hidden and resumes when it is shown", () => {
    mount();
    advance(300);
    setHidden(true);
    expect(box().dataset.status).toBe("paused");
    const before = onFelt().length;
    advance(5000);
    expect(onFelt().length).toBe(before);
    setHidden(false);
    expect(box().dataset.status).toBe("playing");
    advance(1200);
    expect(onFelt().length).toBeGreaterThan(before);
  });

  it("pauses off screen and resumes in view", () => {
    mount();
    advance(300);
    act(() => observed!([{ isIntersecting: false }]));
    expect(box().dataset.status).toBe("paused");
    const before = onFelt().length;
    advance(5000);
    expect(onFelt().length).toBe(before);
    act(() => observed!([{ isIntersecting: true }]));
    expect(box().dataset.status).toBe("playing");
  });

  it("under reduced motion shows one still frame and runs no timer", () => {
    reduced = true;
    mount();
    expect(box().dataset.still).toBe("true");
    expect(box().getAttribute("aria-hidden")).toBe("true");
    expect(vi.getTimerCount()).toBe(0);
    expect(stage().dataset.phase).toBe(STILL.phase);
    expect(faces()).toContain("Big Joker");
    expect(onFelt().length).toBe(4);
    const html = box().innerHTML;
    advance(LOOP * 2);
    expect(box().innerHTML).toBe(html);
  });
});
