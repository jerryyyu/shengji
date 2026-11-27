import { act } from "react";
import { createRoot } from "react-dom/client";
import type { Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import Toast from "./Toast";
import { TOAST_MS, clearToast, currentToast, heldToastKey, hideHeldToast, holdToast, releaseHeldToast, releaseToast, showToast } from "../toast";

let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  vi.useFakeTimers();
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});
afterEach(() => {
  act(() => clearToast());
  act(() => root.unmount());
  host.remove();
  vi.useRealTimers();
});

const shown = () => [...host.querySelectorAll<HTMLElement>(".toast")];

describe("the one toast", () => {
  it("shows one toast at a time, and the newest wins", () => {
    act(() => root.render(<Toast />));
    expect(shown()).toHaveLength(0);
    act(() => { showToast("That game has ended."); });
    act(() => { showToast("Alice left the table.", { info: true }); });
    expect(shown()).toHaveLength(1);
    expect(shown()[0].textContent).toBe("Alice left the table.");
  });

  it("reads an error at once and a notice politely, both as a status", () => {
    act(() => root.render(<Toast />));
    act(() => { showToast("No game or pair has that code."); });
    const err = shown()[0];
    expect([err.getAttribute("role"), err.getAttribute("aria-live")]).toEqual(["status", "assertive"]);
    expect(err.classList.contains("toast-info")).toBe(false);
    act(() => { showToast("Coach on", { info: true }); });
    const info = shown()[0];
    expect([info.getAttribute("role"), info.getAttribute("aria-live")]).toEqual(["status", "polite"]);
    expect(info.classList.contains("toast-info")).toBe(true);
  });

  it("goes by itself after TOAST_MS, and a newer toast gets its full time", () => {
    act(() => root.render(<Toast />));
    act(() => { showToast("First"); });
    act(() => { vi.advanceTimersByTime(TOAST_MS - 100); });
    act(() => { showToast("Second"); });
    act(() => { vi.advanceTimersByTime(200); });
    expect(shown()[0]?.textContent).toBe("Second");
    act(() => { vi.advanceTimersByTime(TOAST_MS); });
    expect(shown()).toHaveLength(0);
    expect(currentToast()).toBeNull();
  });

  it("remounts for each showing, so the same words again fade in again", () => {
    act(() => root.render(<Toast />));
    act(() => { showToast("Same"); });
    const first = shown()[0];
    act(() => { showToast("Same"); });
    expect(shown()[0]).not.toBe(first);
    expect(shown()[0].style.getPropertyValue("--toast-ms")).toBe(`${TOAST_MS}ms`);
  });

  it("draws a second line and a team's dot, and marks the table's spot", () => {
    act(() => root.render(<Toast place="table" />));
    act(() => { showToast("That seat was just taken.", { info: true, sub: "Pick another." }); });
    expect(shown()[0].textContent).toBe("That seat was just taken.Pick another.");
    expect(shown()[0].querySelector("small")?.textContent).toBe("Pick another.");
    expect(shown()[0].classList.contains("at-table")).toBe(true);
    act(() => { showToast("Mei joins next trick", { info: true, dot: 1 }); });
    expect(shown()[0].querySelector(".toast-dot.team1")).not.toBeNull();
  });
});

describe("a held toast", () => {
  it("has no timer until released, then fades over the time it has left", () => {
    act(() => root.render(<Toast place="table" />));
    let id = 0;
    act(() => { id = showToast("You took Bot 2's seat", { info: true, hold: true }).id; });
    expect(shown()[0].classList.contains("held")).toBe(true);
    act(() => { vi.advanceTimersByTime(TOAST_MS * 3); });
    expect(shown()).toHaveLength(1);
    act(() => releaseToast(id));
    const el = shown()[0];
    expect(el.classList.contains("leaving")).toBe(true);
    // up long enough already: only the fade's own 0.4 s is left
    expect(el.style.getPropertyValue("--toast-ms")).toBe("400ms");
    act(() => { vi.advanceTimersByTime(400); });
    expect(shown()).toHaveLength(0);
  });

  it("is replaced by a newer toast, and a stale release leaves the newer one alone", () => {
    act(() => root.render(<Toast />));
    let id = 0;
    act(() => { id = showToast("held", { hold: true }).id; });
    act(() => { showToast("newer", { info: true }); });
    act(() => releaseToast(id));
    expect(currentToast()?.text).toBe("newer");
    expect(currentToast()?.leaving).toBeUndefined();
    act(() => { vi.advanceTimersByTime(TOAST_MS); });
    expect(shown()).toHaveLength(0);
  });

  it("held by key in the store: hidden and shown again keeps its first showing's time, and a release ends it", () => {
    act(() => root.render(<Toast />));
    act(() => holdToast("R:Bot 2", "line"));
    act(() => { vi.advanceTimersByTime(1000); });
    act(() => hideHeldToast());
    expect(shown()).toHaveLength(0);
    expect(heldToastKey()).toBe("R:Bot 2");
    act(() => { vi.advanceTimersByTime(1000); });
    act(() => holdToast("R:Bot 2", "line"));
    expect(shown()[0].classList.contains("held")).toBe(true);
    // shown again while on screen: nothing new
    const id = currentToast()!.id;
    act(() => holdToast("R:Bot 2", "line"));
    expect(currentToast()!.id).toBe(id);
    // a release for another key leaves it
    act(() => releaseHeldToast("R:Mei"));
    expect(heldToastKey()).toBe("R:Bot 2");
    act(() => releaseHeldToast());
    expect(heldToastKey()).toBeNull();
    expect(currentToast()?.leaving).toBe(TOAST_MS - 2000);
  });

  it("hidden with the slot left empty, it is shown again on return", () => {
    act(() => root.render(<Toast />));
    act(() => holdToast("R:Bot 2", "line"));
    act(() => hideHeldToast());
    act(() => { vi.advanceTimersByTime(TOAST_MS * 2); });
    act(() => holdToast("R:Bot 2", "line"));
    expect(shown().map((e) => e.textContent)).toEqual(["line"]);
    expect(currentToast()?.held).toBe(true);
  });

  it("a newer toast supersedes it: a return keeps the newer one, or the empty slot once that is gone", () => {
    act(() => root.render(<Toast />));
    act(() => holdToast("R:Bot 2", "line"));
    act(() => hideHeldToast());
    act(() => { showToast("That game has ended."); });
    act(() => holdToast("R:Bot 2", "line"));
    expect(shown().map((e) => e.textContent)).toEqual(["That game has ended."]);
    expect(heldToastKey()).toBeNull();
    act(() => { vi.advanceTimersByTime(TOAST_MS); });
    act(() => holdToast("R:Bot 2", "line"));
    // superseded once is not held again under the same key
    expect(currentToast()).toBeNull();
  });

  it("a newer toast over it while it shows supersedes it too", () => {
    act(() => root.render(<Toast />));
    act(() => holdToast("R:Bot 2", "line"));
    act(() => { showToast("Alice joins next trick", { info: true }); });
    expect(heldToastKey()).toBeNull();
    act(() => hideHeldToast());
    expect(shown().map((e) => e.textContent)).toEqual(["Alice joins next trick"]);
  });
});
