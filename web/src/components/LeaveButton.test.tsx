import { readFileSync } from "node:fs";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import LeaveButton from "./LeaveButton";

const sent: unknown[] = [];
vi.mock("../ws", () => ({ conn: { send: (m: unknown) => { sent.push(m); } } }));

let root: ReturnType<typeof createRoot>;
let host: HTMLDivElement;
const originalShow = Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, "showModal");
const originalClose = Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, "close");
beforeEach(() => {
  sent.length = 0;
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", { configurable: true, value: function (this: HTMLDialogElement) {
    this.setAttribute("open", "");
  } });
  Object.defineProperty(HTMLDialogElement.prototype, "close", { configurable: true, value: function (this: HTMLDialogElement) {
    this.removeAttribute("open");
  } });
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.restoreAllMocks();
  for (const [name, descriptor] of [["showModal", originalShow], ["close", originalClose]] as const) {
    if (descriptor) Object.defineProperty(HTMLDialogElement.prototype, name, descriptor);
    else Reflect.deleteProperty(HTMLDialogElement.prototype, name);
  }
});

const pill = () => host.querySelector<HTMLButtonElement>(".leave-btn")!;
const alert = () => host.querySelector<HTMLDialogElement>("[role='alertdialog']");
const keep = () => alert()!.querySelector<HTMLButtonElement>(".leave-sheet-stay")!;

function tap(el: HTMLElement) {
  act(() => {
    el.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
    el.click();
  });
}

function press(el: HTMLElement, key: string) {
  act(() => {
    el.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true }));
    el.click();                        // Enter or Space on a button clicks it
  });
}

describe("the HUD Leave pill in a ranked round in play", () => {
  it("still warns what leaving does to the result", () => {
    act(() => root.render(<LeaveButton ranked practice={false} />));
    tap(pill());
    expect(alert()!.querySelector("h2")!.textContent).toBe("Leave the game?");
    expect(alert()!.querySelector("p")!.textContent)
      .toBe("A bot takes your seat. This round counts as at best a draw for you.");
    expect(sent).toEqual([]);
  });
});

describe("the leave sheet's first focus", () => {
  it("opened by a tap: focus is inside the dialog, with no focus ring", () => {
    const focus = vi.spyOn(HTMLElement.prototype, "focus");
    act(() => root.render(<LeaveButton ranked practice={false} />));
    tap(pill());
    expect(document.activeElement).toBe(keep());
    expect(alert()!.contains(document.activeElement)).toBe(true);
    expect(focus).toHaveBeenCalledWith({ focusVisible: false });
    expect(alert()!.hasAttribute("data-pointer-open")).toBe(true);
  });

  it("a key pressed inside a tapped-open alert brings the ring back", () => {
    act(() => root.render(<LeaveButton ranked practice={false} />));
    tap(pill());
    act(() => { keep().dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", bubbles: true })); });
    expect(alert()!.hasAttribute("data-pointer-open")).toBe(false);
  });

  it("opened from the keyboard: the ring shows from the start", () => {
    const focus = vi.spyOn(HTMLElement.prototype, "focus");
    act(() => root.render(<LeaveButton ranked practice={false} />));
    press(pill(), "Enter");
    expect(document.activeElement).toBe(keep());
    expect(focus).toHaveBeenCalledWith({ focusVisible: true });
    expect(alert()!.hasAttribute("data-pointer-open")).toBe(false);
  });

  it("the stylesheet drops the ring only while the alert is marked tap-opened", () => {
    const css = readFileSync(`${import.meta.dirname}/../index.css`, "utf8");
    expect(css).toContain(
      ".leave-sheet-backdrop[data-pointer-open] .leave-sheet-actions button:focus-visible { outline: none; }");
    expect(css).toContain(".leave-sheet-actions button:focus-visible { outline: 2px solid var(--gold);");
  });
});
