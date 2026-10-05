import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import ChatPanel from "./ChatPanel";

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
  expect(send).toHaveBeenCalledExactlyOnceWith({ type: "chat", text: "你好" });
  expect(input.value).toBe("");
});
