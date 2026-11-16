import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import ChatPanel, { SHORT_VISIBLE_PX, visibleArea } from "./ChatPanel";

const send = vi.fn();
vi.mock("../ws", () => ({ conn: { send: (...args: unknown[]) => send(...args) } }));
let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
const originalScroll = Object.getOwnPropertyDescriptor(Element.prototype, "scrollIntoView");

beforeEach(() => {
  send.mockClear();
  Object.defineProperty(Element.prototype, "scrollIntoView", { configurable: true, value: vi.fn() });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  act(() => root.render(<ChatPanel messages={[]} you={0} open onClose={() => {}} />));
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.restoreAllMocks();
  if (originalScroll) Object.defineProperty(Element.prototype, "scrollIntoView", originalScroll);
  else Reflect.deleteProperty(Element.prototype, "scrollIntoView");
});

it("labels the mobile composer and does not send while confirming IME composition", () => {
  const input = host.querySelector("input")!;
  expect(input.getAttribute("aria-label")).toBe("Chat message");
  expect(input.getAttribute("enterkeyhint")).toBe("send");
  act(() => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, "你好");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  act(() => input.dispatchEvent(new KeyboardEvent("keydown", {
    key: "Enter", isComposing: true, bubbles: true,
  })));
  expect(send).not.toHaveBeenCalled();
  expect(input.value).toBe("你好");
  act(() => input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true })));
  expect(send).toHaveBeenCalledExactlyOnceWith({ type: "table_chat", text: "你好" });
  expect(input.value).toBe("");
});

it("does not steal focus on incoming messages and closes on Escape", () => {
  const close = vi.fn();
  const closeButton = host.querySelector<HTMLButtonElement>(".chat-close")!;
  closeButton.focus();
  act(() => root.render(<ChatPanel messages={[{ type: "chat", id: 1, room: "TEST", t: 0, seat: 1, name: "Peer", text: "Hi" }]}
    you={0} open onClose={close} />));
  expect(document.activeElement).toBe(closeButton);
  act(() => closeButton.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })));
  expect(close).toHaveBeenCalledOnce();
});

it("returns focus to the launcher when chat closes", () => {
  act(() => root.render(<ChatPanel messages={[]} you={0} open={false} onClose={() => {}} />));
  const launcher = document.createElement("button");
  document.body.append(launcher);
  try {
    launcher.focus();
    act(() => root.render(<ChatPanel messages={[]} you={0} open onClose={() => {}} />));
    expect(document.activeElement).toBe(host.querySelector("input"));
    act(() => root.render(<ChatPanel messages={[]} you={0} open={false} onClose={() => {}} />));
    expect(document.activeElement).toBe(launcher);
  } finally { launcher.remove(); }
});

it("scales and fades in and out, and does neither under Reduce Motion", () => {
  vi.useFakeTimers();
  const mm = window.matchMedia;
  const had = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "animate");
  Object.defineProperty(HTMLElement.prototype, "animate", { configurable: true, value: () => ({}) });
  const setReduce = (on: boolean) => {
    window.matchMedia = ((q: string) => ({ matches: on && q.includes("reduce"), media: q })) as unknown as typeof window.matchMedia;
  };
  const panel = () => host.querySelector<HTMLElement>(".chat-panel");
  const show = (open: boolean) => act(() => root.render(<ChatPanel messages={[]} you={0} open={open} onClose={() => {}} />));
  try {
    setReduce(false);
    show(false);
    act(() => { vi.advanceTimersByTime(200); });
    show(true);
    expect(panel()!.classList.contains("pop-in")).toBe(true);
    show(false);
    expect(panel()!.classList.contains("pop-out")).toBe(true);
    act(() => { vi.advanceTimersByTime(200); });
    expect(panel()).toBeNull();

    setReduce(true);
    show(true);
    expect(panel()!.className).toBe("chat-panel");
    show(false);
    expect(panel()).toBeNull();
  } finally {
    window.matchMedia = mm;
    if (had) Object.defineProperty(HTMLElement.prototype, "animate", had);
    else Reflect.deleteProperty(HTMLElement.prototype, "animate");
    vi.useRealTimers();
  }
});

it("shows the quick phrases first, then the field, and a tap sends one as a plain line", () => {
  const quick = host.querySelector(".chat-quick")!;
  expect(quick.getAttribute("aria-label")).toBe("Quick phrases");
  expect([...quick.querySelectorAll("button")].map((b) => b.textContent))
    .toEqual(["Hi!", "GG", "Nice!", "One more?", "Brb"]);
  // the row sits before the composer
  expect(quick.compareDocumentPosition(host.querySelector(".chat-input")!) & Node.DOCUMENT_POSITION_FOLLOWING)
    .toBeTruthy();
  act(() => quick.querySelectorAll<HTMLButtonElement>("button")[1].click());
  expect(send).toHaveBeenCalledExactlyOnceWith({ type: "table_chat", text: "GG" });
  // a waiting table's sheet sends through its own path
  const table = vi.fn();
  act(() => root.render(<ChatPanel messages={[]} you={0} open onClose={() => {}} onSend={table} />));
  act(() => host.querySelector<HTMLButtonElement>(".chat-quick button")!.click());
  expect(table).toHaveBeenCalledExactlyOnceWith("Hi!");
  expect(send).toHaveBeenCalledTimes(1);
});

it("keeps table chat open when Escape cancels IME composition", async () => {
  const { ChatRow } = await import("../queue/TablePanel");
  act(() => root.render(<ChatRow messages={[]} you={0} onSend={send} />));
  act(() => host.querySelector<HTMLButtonElement>(".tp-chat")!.click());
  const input = host.querySelector<HTMLInputElement>("input")!;
  act(() => input.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", isComposing: true, bubbles: true })));
  expect(host.querySelector('[role="dialog"]')).not.toBeNull();
  act(() => input.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })));
  expect(host.querySelector('[role="dialog"]')).toBeNull();
});

/** The declarations of the first rule whose selector is exactly `selector`. */
function rule(css: string, selector: string): string {
  const body = css.replace(/\/\*[\s\S]*?\*\//g, "");
  const at = body.search(new RegExp(`(^|})\\s*${selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\s*\\{`));
  expect(at, selector).toBeGreaterThanOrEqual(0);
  const start = body.indexOf("{", at) + 1;
  return body.slice(start, body.indexOf("}", start));
}

it("draws the chips and the field inside one opaque panel, the chips in one unwrapped row", () => {
  const panel = host.querySelector(".chat-panel")!;
  const quick = host.querySelector(".chat-quick")!;
  expect(panel.contains(quick)).toBe(true);
  expect(panel.contains(host.querySelector(".chat-input"))).toBe(true);
  expect(quick.parentElement).toBe(panel);
  const own = readFileSync(`${import.meta.dirname}/ChatPanel.css`, "utf8");
  const index = readFileSync(`${import.meta.dirname}/../index.css`, "utf8");
  // nothing in the panel paints past its edge, and its fill hides the table
  expect(rule(own, ".chat-panel")).toMatch(/overflow:\s*hidden/);
  const fill = rule(index, ".chat-panel").match(/background:\s*([^;]+);/)![1];
  expect(fill).not.toMatch(/rgba|transparent|hsla/);
  // one row: never wraps, scrolls sideways when narrower than the chips
  const row = rule(own, ".chat-quick");
  expect(row).toMatch(/flex-wrap:\s*nowrap/);
  expect(row).toMatch(/overflow-x:\s*auto/);
  expect(rule(own, ".chat-quick-btn")).toMatch(/white-space:\s*nowrap/);
  expect(rule(own, ".chat-quick-btn")).toMatch(/flex:\s*1 0 auto/);
});

it("measures the visible area above a keyboard", () => {
  const vv = (height: number, offsetTop = 0) => ({ height, offsetTop }) as VisualViewport;
  expect(visibleArea({ innerHeight: 390, visualViewport: null })).toBeNull();
  // the app's WebView shrinks with the keyboard: nothing of it is covered
  expect(visibleArea({ innerHeight: 180, visualViewport: vv(180) })).toEqual({ top: 0, height: 180, covered: 0 });
  // mobile Safari: the page stays tall and the keyboard covers its bottom
  expect(visibleArea({ innerHeight: 390, visualViewport: vv(180) })).toEqual({ top: 0, height: 180, covered: 210 });
  expect(visibleArea({ innerHeight: 390, visualViewport: vv(180, 60) })).toEqual({ top: 60, height: 180, covered: 150 });
});

it("fills the visible area when it is short, and not otherwise", () => {
  const had = Object.getOwnPropertyDescriptor(window, "visualViewport");
  const target = new EventTarget();
  let height = 390;
  Object.defineProperties(target, { height: { get: () => height }, offsetTop: { get: () => 0 } });
  Object.defineProperty(window, "visualViewport", { configurable: true, get: () => target });
  const innerHeight = Object.getOwnPropertyDescriptor(window, "innerHeight");
  Object.defineProperty(window, "innerHeight", { configurable: true, get: () => height });
  const panel = () => host.querySelector<HTMLElement>(".chat-panel")!;
  try {
    act(() => root.render(<ChatPanel messages={[]} you={0} open={false} onClose={() => {}} />));
    act(() => root.render(<ChatPanel messages={[]} you={0} open onClose={() => {}} />));
    expect(panel().classList.contains("chat-short")).toBe(false);
    act(() => { height = SHORT_VISIBLE_PX - 120; target.dispatchEvent(new Event("resize")); });
    expect(panel().classList.contains("chat-short")).toBe(true);
    expect(panel().style.getPropertyValue("--chat-vv-h")).toBe("180px");
    act(() => { height = 390; target.dispatchEvent(new Event("resize")); });
    expect(panel().classList.contains("chat-short")).toBe(false);
  } finally {
    if (had) Object.defineProperty(window, "visualViewport", had);
    else Reflect.deleteProperty(window, "visualViewport");
    if (innerHeight) Object.defineProperty(window, "innerHeight", innerHeight);
  }
});

it("leaves the keyboard down on a touch screen when chat opens", () => {
  const mm = window.matchMedia;
  window.matchMedia = ((q: string) => ({ matches: q.includes("coarse"), media: q })) as unknown as typeof window.matchMedia;
  try {
    act(() => root.render(<ChatPanel messages={[]} you={0} open={false} onClose={() => {}} />));
    act(() => root.render(<ChatPanel messages={[]} you={0} open onClose={() => {}} />));
    expect(document.activeElement).not.toBe(host.querySelector("input"));
  } finally {
    window.matchMedia = mm;
  }
});
