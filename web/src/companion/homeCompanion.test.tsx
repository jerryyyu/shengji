// Your own companion on the home felt: drawn as the table draws it, none
// where the table draws none, a tap on it hops it, a tap on the felt walks
// it toward the tap and back to its spot, it keeps clear of the felt's cards
// with room to walk, and
// nothing moves while the page is hidden.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const who = vi.hoisted(() => ({ collection: true, user: { look: "bun/plain", companions: "individual" } as Record<string, unknown> }));
vi.mock("../auth", async (real) => ({ ...(await real<typeof import("../auth")>()), useAuth: () => ({ status: "in", user: who.user }) }));
vi.mock("./feature", () => ({ useCollection: () => who.collection }));

import HomeCompanion, { placeFigure } from "./HomeCompanion";
import type { Box } from "./HomeCompanion";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const FELT = { w: 350, h: 200 };
/** The bottom hand and its cards' path: the middle fifth of the felt, all the way down. */
const HAND: Box = { x0: 140, y0: 100, x1: 210, y1: 200 };
interface Rec { box: string; frames: Keyframe[]; ms: number }
let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
let anims: Rec[];
let hidden = false;
const realMatch = window.matchMedia;
const realCtx = HTMLCanvasElement.prototype.getContext;
const width = Object.getOwnPropertyDescriptor(Element.prototype, "clientWidth");
const height = Object.getOwnPropertyDescriptor(Element.prototype, "clientHeight");

beforeEach(() => {
  who.collection = true;
  who.user = { look: "bun/plain", companions: "individual" };
  hidden = false;
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  vi.useFakeTimers();
  anims = [];
  vi.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(function (this: Element) {
    const [x, y, w, h] = this.classList.contains("home-cmp") ? [0, 0, FELT.w, FELT.h] : [0, 0, 0, 0];
    return { left: x, top: y, width: w, height: h, right: x + w, bottom: y + h, x, y, toJSON: () => ({}) } as DOMRect;
  });
  Object.defineProperty(Element.prototype, "clientWidth", { configurable: true, get() { return FELT.w; } });
  Object.defineProperty(Element.prototype, "clientHeight", { configurable: true, get() { return FELT.h; } });
  Object.defineProperty(document, "visibilityState", { configurable: true, get: () => (hidden ? "hidden" : "visible") });
  (Element.prototype as unknown as { animate: unknown }).animate = function (this: Element, frames: Keyframe[], o: KeyframeAnimationOptions) {
    const rec: Rec = { box: this.className.toString().split(" ")[0], frames, ms: Number(o?.duration ?? 0) };
    anims.push(rec);
    let timer = 0;
    const finished = new Promise<void>((r) => { timer = window.setTimeout(r, rec.ms * Number(o?.iterations ?? 1)); });
    return { finished, cancel() { window.clearTimeout(timer); } } as unknown as Animation;
  };
  HTMLCanvasElement.prototype.getContext = (() => null) as unknown as typeof realCtx;
  window.matchMedia = ((q: string) => ({ matches: q === "", addEventListener() {}, removeEventListener() {} })) as unknown as typeof window.matchMedia;
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  delete (Element.prototype as unknown as { animate?: unknown }).animate;
  if (width) Object.defineProperty(Element.prototype, "clientWidth", width);
  if (height) Object.defineProperty(Element.prototype, "clientHeight", height);
  // @ts-expect-error: back to jsdom's own visibilityState
  delete document.visibilityState;
  HTMLCanvasElement.prototype.getContext = realCtx;
  window.matchMedia = realMatch;
  vi.restoreAllMocks();
  vi.useRealTimers();
});

const tick = (ms: number) => act(async () => { vi.advanceTimersByTime(ms); for (let i = 0; i < 4; i++) await Promise.resolve(); });
const draw = () => act(async () => { root.render(<HomeCompanion away={() => [HAND]} />); });
const figure = () => host.querySelector<SVGElement>(".home-cmp svg.cmp");
const walks = () => anims.filter((a) => a.box === "char-walk").map((a) => a.frames.map((k) => String(k.transform)));
const spot = placeFigure(FELT.w, FELT.h, [HAND])!;
const at = (x: number) => `translate(${x}px, 0px)`;

describe("the home felt's companion", () => {
  it("is the viewer's own equipped look, drawn as the table draws it, standing beside the hand clear of it", async () => {
    who.user = { look: "panda/classic", companions: "individual" };
    await draw();
    const svg = figure();
    expect(svg?.classList.contains("cmp-panda")).toBe(true);
    expect(svg?.getAttribute("width")).toBe(String(spot.size));
    // at rest the table's figure draws no frames: its idle is still
    expect(svg?.classList.contains("cmp-rest")).toBe(true);
    expect(host.querySelector<HTMLElement>(".char-walk")?.style.transform).toBe(at(spot.rest));
    // its middle keeps half a figure off the hand's box, on the hand's right, and its spot is its strip's middle
    expect(spot.range[0] + FELT.w / 2 - spot.size / 2).toBeGreaterThanOrEqual(HAND.x1);
    expect(spot.rest).toBe(Math.round((spot.range[0] + spot.range[1] + FELT.w) / 2) - Math.round(FELT.w / 2));
  });

  it("is not drawn with companions switched off, or with the Collection off for this account", async () => {
    who.user = { look: "panda/classic", companions: "off" };
    await draw();
    expect(host.querySelector(".home-cmp")).toBeNull();
    who.user = { look: "panda/classic", companions: "individual" };
    who.collection = false;
    await draw();
    expect(host.querySelector(".home-cmp")).toBeNull();
  });

  it("hops on a tap on the figure", async () => {
    await draw();
    expect(figure()?.getAttribute("data-pose")).toBe("idle");
    await act(async () => { host.querySelector<HTMLElement>(".coll-figure")!.click(); });
    expect(figure()?.getAttribute("data-pose")).toBe("hop");
  });

  it("walks where the felt is tapped, kept to its strip, and walks back to its spot 3 s after it stands", async () => {
    await draw();
    const felt = host.querySelector<HTMLElement>(".home-cmp")!;
    // a tap at the felt's right edge: it goes as far as its strip lets it
    await act(async () => { felt.dispatchEvent(new MouseEvent("click", { bubbles: true, clientX: FELT.w - 4 })); });
    expect(walks()).toHaveLength(1);
    expect(walks()[0]).toEqual([at(spot.rest), at(spot.range[1])]);
    const there = anims.find((a) => a.box === "char-walk")!.ms;
    await tick(there + 100);
    await tick(2500);
    expect(walks()).toHaveLength(1);
    await tick(1000);
    expect(walks()).toHaveLength(2);
    expect(walks()[1]).toEqual([at(spot.range[1]), at(spot.rest)]);
  });

  it("walks toward a tap on either side of it: left of its strip to the strip's left end", async () => {
    await draw();
    await act(async () => { host.querySelector<HTMLElement>(".home-cmp")!.dispatchEvent(new MouseEvent("click", { bubbles: true, clientX: 4 })); });
    expect(walks()).toEqual([[at(spot.rest), at(spot.range[0])]]);
    expect(spot.range[0]).toBeLessThan(spot.rest);
  });

  it("a tap aimed at the middle cards stops at the strip's end, never over the hand", async () => {
    await draw();
    await act(async () => { host.querySelector<HTMLElement>(".home-cmp")!.dispatchEvent(new MouseEvent("click", { bubbles: true, clientX: FELT.w / 2 })); });
    expect(walks().flat().every((t) => Number(/translate\((-?[\d.]+)px/.exec(t)![1]) >= spot.range[0])).toBe(true);
  });

  it("a store character's special keeps to its strip both ways: no step back past its spot, no lunge past its end", async () => {
    who.user = { look: "lamb/newyear", companions: "individual" };
    await draw();
    const xs = (frames: string[]) => frames.map((t) => Number(/translate\((-?[\d.]+)px/.exec(t)![1]));
    // at its spot, the strip's left end, facing right: the lunge goes right and its step back stays put
    await act(async () => { host.querySelector<HTMLElement>(".coll-figure")!.click(); });
    const first = xs(walks()[walks().length - 1]);
    expect(Math.min(...first)).toBeGreaterThanOrEqual(spot.range[0]);
    expect(Math.max(...first)).toBeGreaterThan(spot.range[0]);
    expect(Math.max(...first)).toBeLessThanOrEqual(spot.range[1]);
    await tick(3000);
    // walked to the strip's right end and back to its middle, facing left: neither way leaves the strip
    const felt = host.querySelector<HTMLElement>(".home-cmp")!;
    await act(async () => { felt.dispatchEvent(new MouseEvent("click", { bubbles: true, clientX: FELT.w })); });
    await tick(3200);
    const mid = Math.round((spot.range[0] + spot.range[1]) / 2);
    await act(async () => { felt.dispatchEvent(new MouseEvent("click", { bubbles: true, clientX: FELT.w / 2 + mid })); });
    await tick(3200);
    await act(async () => { host.querySelector<HTMLElement>(".coll-figure")!.click(); });
    const second = xs(walks()[walks().length - 1]);
    expect(Math.min(...second)).toBeGreaterThanOrEqual(spot.range[0]);
    expect(Math.max(...second)).toBeLessThanOrEqual(spot.range[1]);
  });

  it("laid out anew mid-walk, it ends the walk where it is and stands inside its new strip", async () => {
    await draw();
    const felt = host.querySelector<HTMLElement>(".home-cmp")!;
    await act(async () => { felt.dispatchEvent(new MouseEvent("click", { bubbles: true, clientX: FELT.w })); });
    await tick(300);
    // the felt narrows: its strip moves left and is shorter
    FELT.w = 300;
    await act(async () => { window.dispatchEvent(new Event("resize")); });
    const now = placeFigure(FELT.w, FELT.h, [HAND])!;
    const x = Number(/translate\((-?[\d.]+)px/.exec(host.querySelector<HTMLElement>(".char-walk")!.style.transform)![1]);
    expect(x).toBeGreaterThanOrEqual(now.range[0]);
    expect(x).toBeLessThanOrEqual(now.range[1]);
    FELT.w = 350;
  });

  it("plays nothing while the page is hidden: no moment, no walk back, its figure's animations paused", async () => {
    await draw();
    hidden = true;
    await act(async () => { document.dispatchEvent(new Event("visibilitychange")); });
    expect(host.querySelector(".home-cmp")?.classList.contains("live-paused")).toBe(true);
    const before = anims.length;
    await tick(20000);
    expect(anims.length).toBe(before);
    hidden = false;
    await act(async () => { document.dispatchEvent(new Event("visibilitychange")); });
    expect(host.querySelector(".home-cmp")?.classList.contains("live-paused")).toBe(false);
    await tick(5000);
    expect(anims.length).toBeGreaterThan(before);
  });
});

describe("placeFigure", () => {
  it("keeps the figure's strip clear of every box it reaches and inside the felt, else shows none", () => {
    const p = placeFigure(FELT.w, FELT.h, [HAND])!;
    const top = FELT.h - 6 - p.size * 1.2;
    expect(top).toBeGreaterThan(0);
    expect(p.range[1] + FELT.w / 2 + p.size / 2).toBeLessThanOrEqual(FELT.w);
    // a large figure would stand pinned between the hand and a hand above it on the right (its head reaches
    // that one); a smaller one clears it and has room to walk 1.5 figures, so it is the one drawn
    const pinned = [{ x0: 0, y0: 100, x1: 200, y1: 200 }, { x0: 300, y0: 0, x1: 350, y1: 150 }];
    const c = placeFigure(FELT.w, FELT.h, pinned)!;
    expect(c.size).toBeLessThan(Math.round(FELT.w * 0.15));
    expect(c.range[1] - c.range[0]).toBeGreaterThanOrEqual(1.5 * c.size);
    // where no size has that room, the largest that fits at all
    const tight = placeFigure(FELT.w, FELT.h, [{ x0: 0, y0: 100, x1: 280, y1: 200 }])!;
    expect(tight.size).toBe(39);
    expect(tight.range[1] - tight.range[0]).toBeLessThan(1.5 * tight.size);
    // a felt whose whole foot is covered has no room for it
    expect(placeFigure(FELT.w, FELT.h, [{ x0: 0, y0: 20, x1: FELT.w, y1: FELT.h }])).toBeNull();
  });
});
