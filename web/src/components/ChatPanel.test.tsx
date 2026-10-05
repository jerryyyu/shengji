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
