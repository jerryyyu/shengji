// The Collection's stage plays the table's own moments: the way in on a
// tile's tap, the special with a store character's accent, and at rest the
// table's moments in turn, each from the table's beats and builders, with a
// store character's pieces kept on the stage's felt and painted whole on
// every device.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../ws", () => ({ conn: { send: () => {}, reconnect: () => {} } }));

import { Stage } from "../components/CharacterPage";
import { DROOPS, PERKS, lookFrames } from "./beats";
import { ARRIVES, GAITS, QUIRKS, gaitFrames } from "./flair";
import type { Piece } from "./flair";
import { FlairLayer, sessionTier, stateAt } from "./flairLayer";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const FELT = { w: 343, h: 260 };
interface Rec { box: string; frames: Keyframe[]; ms: number; at: number; cancelled: boolean }
let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
let anims: Rec[];
let spawn: ReturnType<typeof vi.spyOn>;
let reduced = false;
/** The figure's width: 100 here unless a test draws the phone's own 176. */
let px = 100;
const realMatch = window.matchMedia;
const realCtx = HTMLCanvasElement.prototype.getContext;
const width = Object.getOwnPropertyDescriptor(Element.prototype, "clientWidth");
const height = Object.getOwnPropertyDescriptor(Element.prototype, "clientHeight");

beforeEach(() => {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  vi.useFakeTimers();
  anims = [];
  reduced = false;
  sessionTier.tier = "full";
  // the stage's felt, and the figure standing 24 px off its foot with 60 px of felt over its head
  px = 100;
  vi.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(function (this: Element) {
    const figure: [number, number, number, number] = [(FELT.w - px) / 2, FELT.h - 24 - px, px, px];
    const rects: Record<string, [number, number, number, number]> = { "char-stage": [0, 0, FELT.w, FELT.h], "char-walk": figure, "char-box": figure };
    const k = Object.keys(rects).find((c) => this.classList.contains(c));
    const [x, y, w, h] = k ? rects[k] : [0, 0, 0, 0];
    return { left: x, top: y, width: w, height: h, right: x + w, bottom: y + h, x, y, toJSON: () => ({}) } as DOMRect;
  });
  Object.defineProperty(Element.prototype, "clientWidth", { configurable: true, get() { return FELT.w; } });
  Object.defineProperty(Element.prototype, "clientHeight", { configurable: true, get() { return FELT.h; } });
  (Element.prototype as unknown as { animate: unknown }).animate = function (this: Element, frames: Keyframe[], o: KeyframeAnimationOptions) {
    const rec: Rec = { box: this.className.toString().split(" ")[0], frames, ms: Number(o?.duration ?? 0), at: Date.now(), cancelled: false };
    anims.push(rec);
    let timer = 0;
    const finished = new Promise<void>((r) => { timer = window.setTimeout(r, rec.ms * Number(o?.iterations ?? 1)); });
    return { finished, cancel() { window.clearTimeout(timer); rec.cancelled = true; } } as unknown as Animation;
  };
  HTMLCanvasElement.prototype.getContext = (() => null) as unknown as typeof realCtx;
  window.matchMedia = ((q: string) => ({ matches: reduced && q.includes("reduce"), addEventListener() {}, removeEventListener() {} })) as unknown as typeof window.matchMedia;
  spawn = vi.spyOn(FlairLayer.prototype, "spawn");
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  delete (Element.prototype as unknown as { animate?: unknown }).animate;
  if (width) Object.defineProperty(Element.prototype, "clientWidth", width);
  if (height) Object.defineProperty(Element.prototype, "clientHeight", height);
  HTMLCanvasElement.prototype.getContext = realCtx;
  window.matchMedia = realMatch;
  sessionTier.tier = "full";
  vi.restoreAllMocks();
  vi.useRealTimers();
});

const tick = (ms: number) => act(async () => { vi.advanceTimersByTime(ms); for (let i = 0; i < 4; i++) await Promise.resolve(); });
const draw = (kind: "panda" | "lamb" | "bun", colour: string, arrives = 0) =>
  act(async () => { root.render(<Stage kind={kind} colour={colour as never} size={px} label={kind} moves arrives={arrives} />); });
const chip = (name: string) => act(async () => { [...host.querySelectorAll<HTMLButtonElement>(".char-move")].find((b) => b.textContent === name)!.click(); });
const calls = (tag: string, from = 0) => (spawn.mock.calls as unknown as [string, boolean, string, Piece[]][])
  .map((c, i) => ({ tag: c[2], pieces: c[3], started: spawn.mock.results[i]?.value as number })).slice(from).filter((c) => c.tag === tag);
/** Every state of a piece that can be seen is on the stage's felt, side to side. */
const onFelt = (pieces: Piece[]) => pieces.flatMap((p) => p.keys.filter((k) => k.o > 0).map((k) => k.x)).every((x) => x >= 0 && x <= FELT.w);
const text = (a: Rec) => a.frames.map((k) => String(k.transform)).join(" | ");
const same = (a: Rec, frames: readonly Keyframe[]) => text(a) === frames.map((k) => String(k.transform)).join(" | ");

describe("the special on the stage", () => {
  it.each([["panda", "classic", "Bamboo bite", [780, 1200], 1], ["lamb", "newyear", "Horn butt", [690], 3]] as const)(
    "the %s's accent is the table's, and at a phone's stage size (176 px on a 343 px felt) every piece of it stays on the felt", async (kind, colour, name, times, each) => {
      px = 176;
      await draw(kind, colour);
      await tick(300);
      const from = spawn.mock.calls.length;
      await chip(name);
      const accent = calls("burst", from);
      expect(accent.map((c) => [c.pieces.length, c.pieces[0].delay, c.started])).toEqual(times.map((t) => [each, t, each]));
      for (const c of accent) expect(onFelt(c.pieces), JSON.stringify(c.pieces.map((p) => p.keys.map((k) => Math.round(k.x))))).toBe(true);
    });

  it.each([["panda", "classic", "Bamboo bite"], ["lamb", "newyear", "Horn butt"]] as const)(
    "the %s's accent is painted on a device the table has stepped down to its slowest tier (Low Power Mode)", async (kind, colour, name) => {
      sessionTier.tier = "minimal";
      await draw(kind, colour);
      await tick(300);
      const from = spawn.mock.calls.length;
      await chip(name);
      const accent = calls("burst", from);
      expect(accent.length).toBeGreaterThan(0);
      for (const c of accent) expect(c.started).toBe(c.pieces.length);
    });

  it("Big play's burst is the table's, on the felt at a phone's stage size: seven pieces and the mark", async () => {
    px = 176;
    await draw("lamb", "newyear");
    await tick(300);
    const from = spawn.mock.calls.length;
    await chip("Big play");
    const burst = calls("burst", from);
    expect(burst).toHaveLength(1);
    expect(burst[0].pieces.filter((p) => p.shape === "petal")).toHaveLength(7);
    expect(burst[0].pieces.filter((p) => p.shape === "blossom")).toHaveLength(1);
    expect(onFelt(burst[0].pieces)).toBe(true);
  });
});

describe("a tile's tap", () => {
  const arrivals = () => anims.filter((a) => a.box === "char-box" && a.frames[0]?.opacity === 0);

  it("plays the character's way in and a store character's entrance, on the felt, once for each tap, the selected tile's too", async () => {
    px = 176;
    await draw("lamb", "newyear", 1);
    await tick(50);
    expect(arrivals()).toHaveLength(1);
    expect(same(arrivals()[0], ARRIVES.lamb[0].frames)).toBe(true);
    expect(calls("entrance")).toHaveLength(1);
    expect(calls("entrance")[0].started).toBe(calls("entrance")[0].pieces.length);
    expect(onFelt(calls("entrance")[0].pieces)).toBe(true);
    // a frame that is no tap plays nothing more
    await draw("lamb", "newyear", 1);
    await tick(1500);
    expect(arrivals()).toHaveLength(1);
    expect(calls("entrance")).toHaveLength(1);
    // the tile tapped again
    await draw("lamb", "newyear", 2);
    await tick(50);
    expect(arrivals()).toHaveLength(2);
    expect(calls("entrance")).toHaveLength(2);
  });

  it("a free companion comes in its own way with no pieces; the page's first figure is drawn settled; nothing plays under Reduce Motion", async () => {
    px = 150;
    await draw("bun", "plain", 1);
    await tick(50);
    expect(arrivals()).toHaveLength(1);
    // the fullest the stage has room for over its head (86 px over a 150 px figure): the lower plop, not the high one
    expect(same(arrivals()[0], ARRIVES.bun[1].frames)).toBe(true);
    expect(spawn).not.toHaveBeenCalled();
    // a chip pressed while it plays is the player's: the way in ends at once
    expect(arrivals()[0].cancelled).toBe(false);
    await chip("Big play");
    expect(arrivals()[0].cancelled).toBe(true);
    await act(async () => { root.render(<div />); });
    anims = [];
    await draw("lamb", "newyear", 0);
    await tick(1500);
    expect(arrivals()).toHaveLength(0);
    expect(calls("entrance")).toHaveLength(0);
    await act(async () => { root.render(<div />); });
    reduced = true;
    await draw("lamb", "newyear", 3);
    await tick(1500);
    expect(anims).toHaveLength(0);
    expect(calls("entrance").every((c) => c.started === 0)).toBe(true);
  });
});

describe("a tile tapped while the stage is out of view", () => {
  it("owes the entrance until the stage is seen, then plays it exactly once (a phone scrolls back up to the stage after the tap)", async () => {
    const seen: { cb: (e: { isIntersecting: boolean }[]) => void }[] = [];
    class IO {
      cb: (e: { isIntersecting: boolean }[]) => void;
      constructor(cb: (e: { isIntersecting: boolean }[]) => void) { this.cb = cb; seen.push(this); }
      observe() {}
      disconnect() {}
    }
    (window as unknown as { IntersectionObserver: unknown }).IntersectionObserver = IO;
    const view = (on: boolean) => act(async () => { for (const io of seen) io.cb([{ isIntersecting: on }]); });
    const arrivals = () => anims.filter((a) => a.box === "char-box" && a.frames[0]?.opacity === 0 && !a.cancelled);
    try {
      px = 176;
      await draw("lamb", "newyear", 0);
      await tick(300);
      await view(false);
      expect(host.querySelector(".char-stage")!.classList.contains("live-paused")).toBe(true);
      // the selected tile tapped twice from further down the page
      await draw("lamb", "newyear", 1);
      await draw("lamb", "newyear", 2);
      await tick(1000);
      expect(calls("entrance")).toHaveLength(0);
      expect(arrivals()).toHaveLength(0);
      await view(true);
      await tick(50);
      expect(calls("entrance")).toHaveLength(1);
      expect(calls("entrance")[0].started).toBe(calls("entrance")[0].pieces.length);
      expect(arrivals()).toHaveLength(1);
      // out of view and back with no tap in between plays nothing more
      await tick(2000);
      await view(false);
      await view(true);
      await tick(500);
      expect(calls("entrance")).toHaveLength(1);
    } finally {
      delete (window as unknown as { IntersectionObserver?: unknown }).IntersectionObserver;
    }
  });
});

describe("a tile tapped further down the page", () => {
  it("whose stage is found out of view just after its entrance began owes it again, and plays it once the page has scrolled back up", async () => {
    const seen: { cb: (e: { isIntersecting: boolean }[]) => void }[] = [];
    class IO {
      cb: (e: { isIntersecting: boolean }[]) => void;
      constructor(cb: (e: { isIntersecting: boolean }[]) => void) { this.cb = cb; seen.push(this); }
      observe() {}
      disconnect() {}
    }
    (window as unknown as { IntersectionObserver: unknown }).IntersectionObserver = IO;
    const view = (on: boolean) => act(async () => { for (const io of seen) io.cb([{ isIntersecting: on }]); });
    const clear = vi.spyOn(FlairLayer.prototype, "clear");
    try {
      px = 132;
      // drawn by the tap, before the page has said the stage is out of view
      await draw("panda", "classic", 1);
      await tick(30);
      const first = calls("entrance").length;
      await view(false);
      expect(clear).toHaveBeenCalled();
      await tick(400);
      expect(calls("entrance")).toHaveLength(first);
      await view(true);
      await tick(50);
      expect(calls("entrance")).toHaveLength(first + 1);
      expect(calls("entrance")[first].started).toBe(calls("entrance")[first].pieces.length);
      // seen through: leaving view later owes nothing
      await tick(2000);
      await view(false);
      await view(true);
      await tick(200);
      expect(calls("entrance")).toHaveLength(first + 1);
    } finally {
      delete (window as unknown as { IntersectionObserver?: unknown }).IntersectionObserver;
    }
  });
});

describe("a way in still owed when the player acts", () => {
  it("is let go: a chip pressed before the stage is seen again is the only thing that plays", async () => {
    const seen: { cb: (e: { isIntersecting: boolean }[]) => void }[] = [];
    class IO {
      cb: (e: { isIntersecting: boolean }[]) => void;
      constructor(cb: (e: { isIntersecting: boolean }[]) => void) { this.cb = cb; seen.push(this); }
      observe() {}
      disconnect() {}
    }
    (window as unknown as { IntersectionObserver: unknown }).IntersectionObserver = IO;
    const view = (on: boolean) => act(async () => { for (const io of seen) io.cb([{ isIntersecting: on }]); });
    const arrivals = () => anims.filter((a) => a.box === "char-box" && a.frames[0]?.opacity === 0 && !a.cancelled);
    try {
      await draw("bun", "plain", 0);
      await tick(300);
      await view(false);
      await draw("bun", "plain", 1);
      await tick(200);
      expect(arrivals()).toHaveLength(0);
      await chip("Hop");
      await view(true);
      await tick(1500);
      expect(arrivals()).toHaveLength(0);
      // the next tap on its tile plays its way in as ever
      await draw("bun", "plain", 2);
      await tick(50);
      expect(arrivals()).toHaveLength(1);
    } finally {
      delete (window as unknown as { IntersectionObserver?: unknown }).IntersectionObserver;
    }
  });
});

describe("by the felt's edge", () => {
  const tap = (x: number) => act(async () => { host.querySelector(".char-stage")!.dispatchEvent(new MouseEvent("click", { bubbles: true, clientX: x })); });
  it.each([[342, 0.9], [342, 0.1], [1, 0.9], [1, 0.1]])(
    "after a walk to x=%i, with every draw at %f, no tip of a piece of Big play, the special or the walk's trail is painted past the felt's edge at any moment of its life", async (x, r) => {
      vi.spyOn(Math, "random").mockReturnValue(r);
      px = 176;
      await draw("lamb", "newyear");
      await tick(300);
      await tap(x);
      await tick(1250);
      const from = spawn.mock.calls.length;
      await chip("Big play");
      await tick(2000);
      await chip("Horn butt");
      const all = (spawn.mock.calls as unknown as [string, boolean, string, Piece[]][]).map((c) => c[3]);
      expect(all.slice(from).length).toBeGreaterThanOrEqual(2);
      // every petal as it is painted, sampled through its life between its keys: the corners of the box its
      // shape is drawn in (a petal's curve bulges to its full height either side), scaled and turned as the canvas does
      let left = Infinity, right = -Infinity, seen = 0;
      for (const p of all.flat().filter((q) => q.shape === "petal")) {
        for (let n = 0; n <= 200; n++) {
          const k = stateAt(p.keys, n / 200);
          if (k.o <= 0.004) continue;
          const a = (k.r * Math.PI) / 180, c = Math.cos(a), s = Math.sin(a);
          for (const [x, y] of [[-p.w / 2, -p.h], [p.w / 2, -p.h], [-p.w / 2, p.h], [p.w / 2, p.h]]) {
            const at = k.x + c * k.sx * x - s * k.sy * y;
            left = Math.min(left, at); right = Math.max(right, at);
          }
          seen++;
        }
      }
      expect(seen).toBeGreaterThan(500);
      expect(right).toBeLessThanOrEqual(FELT.w);
      expect(left).toBeGreaterThanOrEqual(0);
    });

  /** How far to either side of its middle a mark is painted in state `k`, as the layer draws it: the ring or blot
   *  and the line it is drawn in, under the canvas's scale. */
  const painted = (p: Piece, k: { sx: number; sy: number }) => {
    const half = p.w / 2;
    if (p.shape === "blossom") return (half * 0.9 + Math.max(1, half * 0.06) / 2) * Math.max(Math.abs(k.sx), Math.abs(k.sy));
    if (p.shape === "ripple") return (half * 0.9 + Math.max(1.5, half * 0.12) / 2) * Math.abs(k.sx);
    return half * 0.8 * Math.abs(k.sx);
  };
  it.each([["panda", "classic", 342, "ripple"], ["panda", "classic", 1, "ripple"], ["lamb", "newyear", 342, "blossom"], ["lamb", "newyear", 1, "blossom"]] as const)(
    "the %s (%s) walked to x=%i: its Big play %s stays round it, drawn just small enough that its line is on the felt at every moment", async (kind, colour, x, shape) => {
      vi.spyOn(Math, "random").mockReturnValue(0.9);
      px = 176;
      await draw(kind, colour);
      await tick(300);
      await tap(x);
      await tick(1250);
      const from = spawn.mock.calls.length;
      await chip("Big play");
      const marks = (spawn.mock.calls as unknown as [string, boolean, string, Piece[]][]).slice(from).flatMap((c) => c[3]).filter((p) => p.shape === shape);
      expect(marks.length).toBeGreaterThan(0);
      let left = Infinity, right = -Infinity, widest = 0;
      for (const p of marks) for (let n = 0; n <= 200; n++) {
        const k = stateAt(p.keys, n / 200);
        if (k.o <= 0.004) continue;
        const r = painted(p, k);
        left = Math.min(left, k.x - r); right = Math.max(right, k.x + r); widest = Math.max(widest, r);
      }
      expect(right).toBeLessThanOrEqual(FELT.w);
      expect(left).toBeGreaterThanOrEqual(0);
      // still round the figure, and still a mark: its anchor is the figure's middle, and it is not shrunk away
      const anchor = marks[0].keys[0].x;
      for (const p of marks) for (const k of p.keys) expect(k.x).toBe(anchor);
      expect(widest).toBeGreaterThan(40);
    });

  it("a mark with room is drawn as it is: in the middle of the stage Big play's ring is the table's own size", async () => {
    for (const [kind, colour, shape] of [["lamb", "newyear", "blossom"], ["panda", "classic", "ripple"]] as const) {
      await act(async () => { root.render(<div />); });
      px = 100;
      await draw(kind, colour);
      await tick(300);
      const from = spawn.mock.calls.length;
      await chip("Big play");
      const marks = (spawn.mock.calls as unknown as [string, boolean, string, Piece[]][]).slice(from).flatMap((c) => c[3]).filter((p) => p.shape === shape);
      expect(marks.length).toBeGreaterThan(0);
      // the builders' own scales, untouched: the blossom opens to 1.5, the ripple spreads to 1.7 wide
      expect(Math.max(...marks.flatMap((p) => p.keys.map((k) => k.sx)))).toBe(shape === "blossom" ? 1.5 : 1.7);
    }
    });
});

describe("a tap on the stage's felt", () => {
  const xOf = (s: string) => Number(/translate\(([-\d.]+)px/.exec(s)![1]);
  const walkBox = () => host.querySelector<HTMLElement>(".char-stage .char-walk")!;
  const tap = (x: number) => act(async () => { host.querySelector(".char-stage")!.dispatchEvent(new MouseEvent("click", { bubbles: true, clientX: x })); });

  it("walks it there, and a few seconds after it comes to a stand it walks back to the middle at the same pace; a new tap starts the wait again", async () => {
    await draw("bun", "plain");
    await tick(300);
    await tap(FELT.w / 2 + 80);
    const out = anims.filter((a) => a.box === "char-walk")[0];
    expect(xOf(String(out.frames[1].transform))).toBe(80);
    expect(xOf(walkBox().style.transform)).toBe(80);
    await tick(out.ms + 100);
    // a second tap before the wait is up
    await tick(2000);
    await tap(FELT.w / 2 - 60);
    const again = anims.filter((a) => a.box === "char-walk")[1];
    expect(xOf(String(again.frames[1].transform))).toBe(-60);
    await tick(again.ms + 100);
    await tick(2000);
    expect(anims.filter((a) => a.box === "char-walk")).toHaveLength(2);
    expect(xOf(walkBox().style.transform)).toBe(-60);
    for (let s = 0; s < 40 && anims.filter((a) => a.box === "char-walk").length < 3; s++) await tick(250);
    const home = anims.filter((a) => a.box === "char-walk")[2];
    expect(home).toBeTruthy();
    expect(xOf(String(home.frames[0].transform))).toBe(-60);
    expect(xOf(String(home.frames[1].transform))).toBe(0);
    expect(xOf(walkBox().style.transform)).toBe(0);
    // the same pace: half a second a figure's width, with no tap's floor
    expect(home.ms).toBeCloseTo((60 / 100) * 500, 5);
  });

  it("under Reduce Motion a tap moves nothing: it stays in the middle", async () => {
    reduced = true;
    await draw("bun", "plain");
    await tap(FELT.w / 2 + 80);
    await tick(8000);
    expect(anims).toHaveLength(0);
    expect(walkBox().style.transform).toBe("");
  });
});

describe("at rest on the stage", () => {
  /** What it did by itself, in order, told by the table's own keyframes. */
  const told = (kind: "bun" | "panda") => anims.filter((a) => !a.frames[0] || a.frames[0].opacity !== 0).map((a) =>
    (a.box === "char-walk" ? "stroll"
      : a.box === "char-box" && same(a, QUIRKS[kind].frames) ? "habit"
      : a.box === "char-box" && PERKS.some((b) => same(a, b.frames)) ? "ready"
      : a.box === "char-face" && same(a, lookFrames({ dir: 1, lean: 0, up: false }, { dir: 1, lean: 8, up: false }, true)) ? "watch"
      : a.box === "char-face" && same(a, lookFrames({ dir: -1, lean: 0, up: false }, { dir: -1, lean: 8, up: false }, true)) ? "watch"
      : a.box === "char-box" && same(a, DROOPS[0].frames) ? "loss" : "")).filter(Boolean);
  const pose = () => host.querySelector(".char-stage svg.cmp")?.getAttribute("data-pose");

  it("a free companion takes the table's moments in turn: a stroll in its own gait, its habit, ready for a turn, a lean to watch, the droop of a trick lost", async () => {
    await draw("bun", "plain");
    for (let s = 0; s < 80 && new Set(told("bun")).size < 5; s++) await tick(500);
    const seen = told("bun");
    expect(seen.filter((k, i) => seen.indexOf(k) === i)).toEqual(["stroll", "habit", "ready", "watch", "loss"]);
    // the stroll's gait is the Bun's own, as at the table
    const gait = anims.find((a) => a.box === "char-face" && a.frames.length === GAITS.bun.steps.length && text(a).includes("scale(1.08, 0.9)"))!;
    expect(gait).toBeTruthy();
    expect([text(gait)]).toContain(gaitFrames(GAITS.bun, text(gait).includes("scaleX(-1)") ? -1 : 1).map((k) => String(k.transform)).join(" | "));
    // the jump is the highest the stage has room for over its head (60 px over a 100 px figure)
    expect(anims.some((a) => same(a, PERKS[0].frames))).toBe(true);
    expect(spawn).not.toHaveBeenCalled();
  });

  it("a store character's pieces come with them: one falling as it droops, and a round won is its special under its shower, on the felt", async () => {
    await draw("panda", "classic");
    let won = -1;
    for (let s = 0; s < 160 && calls("shower").length === 0; s++) await tick(500);
    won = calls("shower").length;
    expect(told("panda").filter((k, i, all) => all.indexOf(k) === i)).toEqual(["stroll", "habit", "ready", "watch", "loss"]);
    expect(won).toBe(1);
    expect(pose()).toBe("react");
    const shower = calls("shower")[0];
    expect(shower.pieces.filter((p) => p.shape === "leaf")).toHaveLength(6);
    expect(shower.started).toBe(shower.pieces.length);
    expect(onFelt(shower.pieces)).toBe(true);
    const fall = calls("burst").filter((c) => c.pieces.length === 1 && c.pieces[0].delay === 250);
    expect(fall.length).toBeGreaterThanOrEqual(1);
    expect(calls("trail").length).toBeGreaterThan(0);
  });

  it("a chip or a tap on the figure ends a moment in flight at once, and the next waits its full time", async () => {
    await draw("bun", "plain");
    // up to the jump of getting ready, held larger
    for (let s = 0; s < 80 && !anims.some((a) => PERKS.some((b) => same(a, b.frames))); s++) await tick(250);
    const ready = anims.find((a) => PERKS.some((b) => same(a, b.frames)))!;
    expect(ready).toBeTruthy();
    expect(ready.cancelled).toBe(false);
    await chip("Big play");
    expect(ready.cancelled).toBe(true);
    const from = anims.length;
    await tick(3500);
    // only the chip's own move in that time: no walk or lean of the stage's own
    expect(anims.slice(from).filter((a) => a.box === "char-walk" || a.box === "char-face")).toHaveLength(0);
    // the same for a tap on the figure
    for (let s = 0; s < 120 && !anims.slice(from).some((a) => same(a, DROOPS[0].frames) || same(a, QUIRKS.bun.frames)); s++) await tick(250);
    const mine = anims.slice(from).find((a) => same(a, DROOPS[0].frames) || same(a, QUIRKS.bun.frames))!;
    expect(mine).toBeTruthy();
    await act(async () => { host.querySelector<HTMLButtonElement>(".char-stage .coll-figure")!.click(); });
    expect(mine.cancelled).toBe(true);
  });

  it("nothing of it plays under Reduce Motion", async () => {
    reduced = true;
    await draw("panda", "classic");
    await tick(40000);
    expect(anims).toHaveLength(0);
    expect((spawn.mock.results as { value?: unknown }[]).every((r) => r.value === 0)).toBe(true);
  });
});
