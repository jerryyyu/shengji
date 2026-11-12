// A phone's bottom sheet drags down to dismiss, by touch only and below
// 700px: from the grab handle or header at any time, or from the body when
// nothing under the finger is scrolled down; never from a control.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { WIDE } from "../home/route";
import Sheet from "./Sheet";
import { SHEET_SETTLE_MS } from "./useSheetDrag";

const H = 400;
let media: { wide: boolean; reduce: boolean };
let clock: number;
let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
let onClose: ReturnType<typeof vi.fn<() => void>>;
const realMatchMedia = window.matchMedia;

beforeEach(async () => {
  media = { wide: false, reduce: false };
  clock = 1000;
  vi.spyOn(performance, "now").mockImplementation(() => clock);
  window.matchMedia = ((q: string) => ({
    matches: q === WIDE ? media.wide : q.includes("reduce") ? media.reduce : false,
    media: q, addEventListener: () => {}, removeEventListener: () => {},
  })) as unknown as typeof window.matchMedia;
  onClose = vi.fn<() => void>();
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.restoreAllMocks();
  window.matchMedia = realMatchMedia;
});

async function render() {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => {
    root.render(
      <Sheet title="Find a game" onClose={onClose}>
        <div className="q-sheet-pad">
          <p className="plain">body</p>
          <input className="field" />
          <button type="button" className="btn">Play</button>
          <div className="list" style={{ overflowY: "auto" }}><p className="row">row</p></div>
        </div>
      </Sheet>,
    );
  });
  vi.spyOn(sheet(), "getBoundingClientRect").mockReturnValue({ height: H } as DOMRect);
}
const layer = () => host.querySelector<HTMLElement>(".q-layer")!;
const sheet = () => host.querySelector<HTMLElement>(".q-sheet")!;
const shift = () => layer().style.getPropertyValue("--sheet-drag-y");
const scrim = () => layer().style.getPropertyValue("--sheet-scrim");
const wait = (ms: number) => act(async () => { await new Promise((r) => setTimeout(r, ms)); });

function touch(type: string, y: number, el: Element, { x = 200, fingers = 1 } = {}) {
  const e = new Event(type, { bubbles: true, cancelable: true });
  const pts = Array.from({ length: fingers }, (_, i) => ({ clientX: x + i * 40, clientY: y }));
  const ended = type === "touchend" || type === "touchcancel";
  Object.defineProperty(e, "touches", { value: ended ? [] : pts });
  Object.defineProperty(e, "changedTouches", { value: [{ clientX: x, clientY: y }] });
  act(() => { el.dispatchEvent(e); });
  return e;
}
/** A drag from y=100 down by `dy` in ten steps over `ms`, released where it
 *  stopped after `hold` ms; returns every move. */
function drag(dy: number, { ms = 500, on = ".q-grab", release = true, hold = 0 } = {}) {
  const el = host.querySelector(on)!;
  touch("touchstart", 100, el);
  const moves: Event[] = [];
  for (let i = 1; i <= 10; i++) {
    clock += ms / 10;
    moves.push(touch("touchmove", 100 + (dy * i) / 10, el));
  }
  clock += hold;
  if (release) touch("touchend", 100 + dy, el);
  return moves;
}

it("follows the finger and fades the scrim, then slides out past a quarter of its height and closes once", async () => {
  await render();
  const grab = host.querySelector(".q-grab")!;
  touch("touchstart", 100, grab);
  expect(touch("touchmove", 105, grab).defaultPrevented).toBe(false);
  touch("touchend", 105, grab);
  const moves = drag(120, { release: false });
  expect(moves[9].defaultPrevented).toBe(true);
  expect(layer().dataset.sheetDrag).toBe("drag");
  expect(shift()).toBe("120px");
  expect(scrim()).toBe(String(1 - 120 / H));
  touch("touchend", 220, sheet());
  expect(layer().dataset.sheetDrag).toBe("out");
  expect(shift()).toBe(`${H}px`);
  expect(onClose).not.toHaveBeenCalled();
  await wait(SHEET_SETTLE_MS + 20);
  expect(onClose).toHaveBeenCalledTimes(1);
  drag(200);
  await wait(SHEET_SETTLE_MS + 20);
  expect(onClose).toHaveBeenCalledTimes(1);
});

it("springs back from a short slow drag", async () => {
  await render();
  drag(60);
  expect(layer().dataset.sheetDrag).toBe("settle");
  expect(shift()).toBe("0px");
  await wait(SHEET_SETTLE_MS + 20);
  expect(layer().dataset.sheetDrag).toBeUndefined();
  expect(shift()).toBe("");
  expect(onClose).not.toHaveBeenCalled();
});

it("takes a fast downward flick however short", async () => {
  await render();
  drag(60, { ms: 60 });
  await wait(SHEET_SETTLE_MS + 20);
  expect(onClose).toHaveBeenCalledTimes(1);
});

it("does not take a quick drag whose finger stopped before lifting", async () => {
  await render();
  drag(60, { ms: 60, hold: 300 });
  expect(layer().dataset.sheetDrag).toBe("settle");
  await wait(SHEET_SETTLE_MS + 20);
  expect(onClose).not.toHaveBeenCalled();
});

it("rubber-bands an upward drag from the handle and never dismisses it", async () => {
  await render();
  drag(-200, { release: false });
  const y = parseFloat(shift());
  expect(y).toBeLessThan(0);
  expect(y).toBeGreaterThan(-H / 5);
  touch("touchend", -100, sheet());
  await wait(SHEET_SETTLE_MS + 20);
  expect(onClose).not.toHaveBeenCalled();
  expect(layer().dataset.sheetDrag).toBeUndefined();
});

it("settles with the transform cleared when a second finger lands mid-drag", async () => {
  await render();
  const el = host.querySelector(".q-grab")!;
  drag(150, { release: false });
  touch("touchstart", 250, el, { fingers: 2 });
  expect(layer().dataset.sheetDrag).toBe("settle");
  expect(shift()).toBe("0px");
  expect(touch("touchmove", 300, el, { fingers: 2 }).defaultPrevented).toBe(false);
  touch("touchend", 300, el);
  await wait(SHEET_SETTLE_MS + 20);
  expect(layer().dataset.sheetDrag).toBeUndefined();
  expect(shift()).toBe("");
  expect(scrim()).toBe("");
  expect(onClose).not.toHaveBeenCalled();
});

it("settles when a second finger shows up in a move", async () => {
  await render();
  const el = host.querySelector(".q-grab")!;
  drag(150, { release: false });
  touch("touchmove", 260, el, { fingers: 2 });
  touch("touchend", 260, el);
  await wait(SHEET_SETTLE_MS + 20);
  expect(layer().dataset.sheetDrag).toBeUndefined();
  expect(onClose).not.toHaveBeenCalled();
});

it("settles on touchcancel", async () => {
  await render();
  drag(150, { release: false });
  touch("touchcancel", 250, sheet());
  expect(layer().dataset.sheetDrag).toBe("settle");
  await wait(SHEET_SETTLE_MS + 20);
  expect(layer().dataset.sheetDrag).toBeUndefined();
  expect(shift()).toBe("");
  expect(onClose).not.toHaveBeenCalled();
});

it("drags from the header and from the body when nothing is scrolled", async () => {
  await render();
  drag(200, { on: "h2" });
  await wait(SHEET_SETTLE_MS + 20);
  expect(onClose).toHaveBeenCalledTimes(1);
  act(() => root.unmount());
  host.remove();
  await render();
  drag(200, { on: ".plain" });
  await wait(SHEET_SETTLE_MS + 20);
  expect(onClose).toHaveBeenCalledTimes(2);
});

it("leaves an upward-first or sideways move in the body alone", async () => {
  await render();
  const el = host.querySelector(".plain")!;
  touch("touchstart", 300, el);
  expect(touch("touchmove", 280, el).defaultPrevented).toBe(false);
  expect(touch("touchmove", 500, el).defaultPrevented).toBe(false);
  touch("touchend", 500, el);
  touch("touchstart", 300, el, { x: 100 });
  expect(touch("touchmove", 305, el, { x: 160 }).defaultPrevented).toBe(false);
  expect(touch("touchmove", 500, el, { x: 160 }).defaultPrevented).toBe(false);
  touch("touchend", 500, el);
  await wait(SHEET_SETTLE_MS + 20);
  expect(layer().dataset.sheetDrag).toBeUndefined();
  expect(onClose).not.toHaveBeenCalled();
});

it("ignores drags that start on the input, a button or Cancel", async () => {
  await render();
  for (const on of [".field", ".btn", ".q-sheet-head .q-link"]) {
    const moves = drag(250, { on });
    expect(moves[9].defaultPrevented, on).toBe(false);
  }
  await wait(SHEET_SETTLE_MS + 20);
  expect(layer().dataset.sheetDrag).toBeUndefined();
  expect(onClose).not.toHaveBeenCalled();
});

it("leaves a body drag alone while the list under it is scrolled down, but the handle still drags", async () => {
  await render();
  const list = host.querySelector<HTMLElement>(".list")!;
  list.scrollTop = 40;
  Object.defineProperty(list, "scrollTop", { value: 40, configurable: true });
  const moves = drag(250, { on: ".row" });
  expect(moves[9].defaultPrevented).toBe(false);
  await wait(SHEET_SETTLE_MS + 20);
  expect(onClose).not.toHaveBeenCalled();
  drag(250);
  await wait(SHEET_SETTLE_MS + 20);
  expect(onClose).toHaveBeenCalledTimes(1);
});

it("ignores the mouse", async () => {
  await render();
  const el = host.querySelector(".q-grab")!;
  const fire = (type: string, y: number) => {
    act(() => { el.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, clientX: 200, clientY: y })); });
    act(() => { el.dispatchEvent(new PointerEvent(type.replace("mouse", "pointer"), { bubbles: true, cancelable: true, clientX: 200, clientY: y, pointerType: "mouse" })); });
  };
  fire("mousedown", 100);
  for (let y = 120; y <= 350; y += 23) { clock += 20; fire("mousemove", y); }
  fire("mouseup", 350);
  await wait(SHEET_SETTLE_MS + 20);
  expect(layer().dataset.sheetDrag).toBeUndefined();
  expect(onClose).not.toHaveBeenCalled();
});

it("under Reduce Motion never moves the sheet and dismisses or stays at once", async () => {
  media.reduce = true;
  await render();
  drag(60);
  expect(layer().dataset.sheetDrag).toBeUndefined();
  expect(shift()).toBe("");
  expect(onClose).not.toHaveBeenCalled();
  const moves = drag(200, { release: false });
  expect(moves[9].defaultPrevented).toBe(true);
  expect(layer().dataset.sheetDrag).toBeUndefined();
  expect(shift()).toBe("");
  touch("touchend", 300, sheet());
  expect(onClose).toHaveBeenCalledTimes(1);
});

it("does nothing from 700px, where the sheet is a centred dialog", async () => {
  media.wide = true;
  await render();
  const moves = drag(250);
  expect(moves[9].defaultPrevented).toBe(false);
  await wait(SHEET_SETTLE_MS + 20);
  expect(layer().dataset.sheetDrag).toBeUndefined();
  expect(onClose).not.toHaveBeenCalled();
});

it("still closes on Escape, a scrim tap and Cancel", async () => {
  await render();
  act(() => { document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" })); });
  act(() => { host.querySelector<HTMLElement>(".q-scrim")!.click(); });
  act(() => { host.querySelector<HTMLElement>(".q-sheet-head .q-link")!.click(); });
  expect(onClose).toHaveBeenCalledTimes(3);
  expect(document.activeElement).toBe(sheet());
});
