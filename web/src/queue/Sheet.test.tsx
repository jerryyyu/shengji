// A phone's bottom sheet drags down to dismiss, by touch only and below
// 700px: from the grab handle or header at any time, or from the body when
// nothing under the finger is scrolled down; never from a control.
import { readFileSync } from "node:fs";
import { act } from "react";
import type { ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { WIDE } from "../home/route";
import Sheet, { SHEET_IN_MS } from "./Sheet";
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

const flush = () => act(async () => { await Promise.resolve(); });
function key(k: string, shiftKey = false) {
  const e = new KeyboardEvent("keydown", { key: k, shiftKey, bubbles: true, cancelable: true });
  act(() => { (document.activeElement ?? document).dispatchEvent(e); });
  return e;
}
/** Renders `node` into a fresh host, with a page button before the host. */
async function mount(node: ReactNode) {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => { root.render(node); });
}
const other = (title: string) => (
  <Sheet title={title} onClose={onClose}>
    <div className="q-sheet-pad"><button type="button" className="btn other">Other</button></div>
  </Sheet>
);
function withAnimate(run: () => Promise<void>) {
  return async () => {
    Object.defineProperty(HTMLElement.prototype, "animate", { value: vi.fn(), configurable: true, writable: true });
    try {
      await run();
    } finally {
      delete (HTMLElement.prototype as { animate?: unknown }).animate;
      document.querySelectorAll(".q-out").forEach((n) => n.remove());
    }
  };
}

it("keeps the handle and header out of the body, which is what scrolls on a short screen", async () => {
  await render();
  const body = host.querySelector<HTMLElement>(".q-sheet-body")!;
  expect(body.parentElement).toBe(sheet());
  expect(body.querySelector(".q-sheet-pad")).not.toBeNull();
  expect(body.contains(host.querySelector(".q-sheet-head"))).toBe(false);
  expect(body.contains(host.querySelector(".q-grab"))).toBe(false);
  const css = readFileSync(`${import.meta.dirname}/../index.css`, "utf8");
  const rule = (sel: string) => css.match(new RegExp(`\\n${sel.replace(/[.]/g, "\\.")} \\{([^}]*)\\}`))?.[1] ?? "";
  expect(rule(".q-sheet")).toMatch(/max-height: calc\(100% - max\(8px, env\(safe-area-inset-top/);
  expect(rule(".q-sheet-body")).toMatch(/overflow-y: auto/);
  expect(rule(".q-sheet-body")).toMatch(/min-height: 0/);
});

it("drags from the body only while the body is scrolled to its top", async () => {
  await render();
  const body = host.querySelector<HTMLElement>(".q-sheet-body")!;
  Object.defineProperty(body, "scrollTop", { value: 30, configurable: true });
  expect(drag(250, { on: ".plain" })[9].defaultPrevented).toBe(false);
  await wait(SHEET_SETTLE_MS + 20);
  expect(onClose).not.toHaveBeenCalled();
  Object.defineProperty(body, "scrollTop", { value: 0, configurable: true });
  expect(drag(250, { on: ".plain" })[9].defaultPrevented).toBe(true);
  await wait(SHEET_SETTLE_MS + 20);
  expect(onClose).toHaveBeenCalledTimes(1);
});

it("keeps Tab and Shift-Tab inside the sheet and makes the page behind it inert", async () => {
  const page = document.createElement("button");
  page.textContent = "Find a game";
  document.body.appendChild(page);
  try {
    page.focus();
    await render();
    expect(page.hasAttribute("inert")).toBe(true);
    const cancel = host.querySelector<HTMLElement>(".q-sheet-head .q-link")!;
    const field = host.querySelector<HTMLElement>(".field")!;
    const play = host.querySelector<HTMLElement>(".btn")!;
    expect(document.activeElement).toBe(sheet());
    expect(key("Tab", true).defaultPrevented).toBe(true);
    expect(document.activeElement).toBe(play);
    expect(key("Tab").defaultPrevented).toBe(true);
    expect(document.activeElement).toBe(cancel);
    expect(key("Tab", true).defaultPrevented).toBe(true);
    expect(document.activeElement).toBe(play);
    field.focus();
    expect(key("Tab").defaultPrevented).toBe(false);
    page.focus();
    expect(key("Tab").defaultPrevented).toBe(true);
    expect(document.activeElement).toBe(cancel);
    act(() => root.render(<></>));
    expect(page.hasAttribute("inert")).toBe(false);
    await flush();
    expect(document.activeElement).toBe(page);
  } finally {
    page.remove();
  }
});

it("does not take focus back to an opener that is gone", async () => {
  const page = document.createElement("button");
  document.body.appendChild(page);
  page.focus();
  await render();
  page.remove();
  act(() => root.render(<></>));
  await flush();
  expect(document.activeElement).toBe(document.body);
});

it("hands focus to a sheet that replaces it, and the opener back when that one closes", async () => {
  const page = document.createElement("button");
  document.body.appendChild(page);
  try {
    page.focus();
    await mount(<div key="a">{other("Find a game")}</div>);
    host.querySelector<HTMLElement>(".other")!.focus();
    await act(async () => { root.render(<div key="b">{other("Queue with a friend")}</div>); });
    await flush();
    expect(host.querySelectorAll(".q-layer")).toHaveLength(1);
    expect(document.activeElement).toBe(sheet());
    expect(host.querySelector("h2")!.textContent).toBe("Queue with a friend");
    expect(page.hasAttribute("inert")).toBe(true);
    act(() => root.render(<></>));
    await flush();
    expect(page.hasAttribute("inert")).toBe(false);
    expect(document.activeElement).toBe(page);
  } finally {
    page.remove();
  }
});

it("catches a sheet that is springing back where it is drawn, and follows the finger on from there", async () => {
  await render();
  drag(40, { hold: 130 });
  expect(layer().dataset.sheetDrag).toBe("settle");
  clock += 40;
  const real = globalThis.getComputedStyle;
  vi.spyOn(globalThis, "getComputedStyle").mockImplementation((el, p) =>
    el === sheet() ? ({ transform: "matrix(1, 0, 0, 1, 0, 26.41)" } as CSSStyleDeclaration) : real(el, p));
  const grab = host.querySelector(".q-grab")!;
  touch("touchstart", 300, grab);
  expect(layer().dataset.sheetDrag).toBe("drag");
  expect(shift()).toBe("26.41px");
  clock += 16;
  touch("touchmove", 309, grab);
  const y = parseFloat(shift());
  expect(y).toBeCloseTo(35.41, 2);
  expect(y).toBeGreaterThanOrEqual(26.41);
  clock += 200;
  touch("touchend", 309, grab);
  expect(layer().dataset.sheetDrag).toBe("settle");
  expect(shift()).toBe("0px");
  await wait(SHEET_SETTLE_MS + 20);
  expect(onClose).not.toHaveBeenCalled();
});

it("springs a caught sheet back when the touch lifts without moving, and dismisses one dragged on past the line", async () => {
  await render();
  const grab = host.querySelector(".q-grab")!;
  const real = globalThis.getComputedStyle;
  let drawn = "matrix(1, 0, 0, 1, 0, 30)";
  vi.spyOn(globalThis, "getComputedStyle").mockImplementation((el, p) =>
    el === sheet() ? ({ transform: drawn } as CSSStyleDeclaration) : real(el, p));
  touch("touchstart", 300, grab);
  expect(shift()).toBe("30px");
  touch("touchend", 300, grab);
  expect(layer().dataset.sheetDrag).toBe("settle");
  expect(shift()).toBe("0px");
  drawn = "matrix(1, 0, 0, 1, 0, 80)";
  touch("touchstart", 300, grab);
  clock += 400;
  touch("touchmove", 325, grab);
  clock += 400;
  touch("touchend", 325, grab);
  expect(layer().dataset.sheetDrag).toBe("out");
  await wait(SHEET_SETTLE_MS + 20);
  expect(onClose).toHaveBeenCalledTimes(1);
});

it("slides in, then leaves a copy that slides out when it closes", withAnimate(async () => {
  await render();
  expect(layer().classList.contains("q-in")).toBe(true);
  await wait(SHEET_IN_MS + 20);
  expect(layer().classList.contains("q-in")).toBe(false);
  act(() => root.render(<></>));
  const ghost = host.querySelector<HTMLElement>(".q-layer.q-out")!;
  expect(ghost).not.toBeNull();
  expect(ghost.hasAttribute("inert")).toBe(true);
  expect(ghost.getAttribute("aria-hidden")).toBe("true");
  expect(ghost.querySelector("[id]")).toBeNull();
  await wait(SHEET_IN_MS + 20);
  expect(host.querySelector(".q-layer")).toBeNull();
}));

it("does not slide a sheet that replaces another, nor leave a copy of the one it replaced", withAnimate(async () => {
  await mount(<div key="a">{other("Find a game")}</div>);
  await act(async () => { root.render(<div key="b">{other("Queue with a friend")}</div>); });
  await flush();
  const layers = host.querySelectorAll<HTMLElement>(".q-layer");
  expect(layers).toHaveLength(1);
  expect(layers[0].classList.contains("q-in")).toBe(false);
}));

it("leaves no copy after a drag has already slid the sheet out", withAnimate(async () => {
  await render();
  drag(200);
  await wait(SHEET_SETTLE_MS + 20);
  expect(onClose).toHaveBeenCalledTimes(1);
  act(() => root.render(<></>));
  expect(host.querySelector(".q-out")).toBeNull();
}));

it("neither slides in nor leaves a copy under Reduce Motion", withAnimate(async () => {
  media.reduce = true;
  await render();
  expect(layer().classList.contains("q-in")).toBe(false);
  act(() => root.render(<></>));
  expect(host.querySelector(".q-out")).toBeNull();
}));
