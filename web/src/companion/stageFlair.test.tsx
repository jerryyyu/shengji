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
import { FlairLayer, sessionTier } from "./flairLayer";

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
    await draw("bun", "plain", 1);
    await tick(50);
    expect(arrivals()).toHaveLength(1);
    expect(same(arrivals()[0], ARRIVES.bun[0].frames)).toBe(true);
    expect(spawn).not.toHaveBeenCalled();
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

  it("nothing of it plays under Reduce Motion", async () => {
    reduced = true;
    await draw("panda", "classic");
    await tick(40000);
    expect(anims).toHaveLength(0);
    expect((spawn.mock.results as { value?: unknown }[]).every((r) => r.value === 0)).toBe(true);
  });
});
