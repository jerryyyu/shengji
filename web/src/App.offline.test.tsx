// Offline mode has nothing to choose: it opens straight into a game against
// bots under the saved name, with no landing page, through the real in-page
// server.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
const realLocation = window.location;
beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  (window as unknown as { AudioContext: unknown }).AudioContext = class {
    state = "running";
    resume() { return Promise.resolve(); }
  };
  Object.defineProperty(window, "location", { configurable: true,
    value: { ...realLocation, search: "?offline=1", protocol: "http:", assign: vi.fn(), reload: vi.fn() } });
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", { configurable: true, value() { (this as HTMLDialogElement).setAttribute("open", ""); } });
  Object.defineProperty(HTMLDialogElement.prototype, "close", { configurable: true, value() { (this as HTMLDialogElement).removeAttribute("open"); } });
  vi.resetModules();
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  Object.defineProperty(window, "location", { configurable: true, value: realLocation });
  sessionStorage.clear();
});

async function until(check: () => boolean, ms = 5000): Promise<void> {
  const end = Date.now() + ms;
  while (!check()) {
    if (Date.now() > end) throw new Error("timed out");
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
  }
}

it("starts a game vs bots at once under the saved name, with no landing page", async () => {
  const { OFFLINE, saveName } = await import("./ws");
  expect(OFFLINE).toBe(true);
  saveName("Cheerful Tractor");
  const { default: App } = await import("./App");
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  act(() => root.render(<App />));
  // no lobby, no offline landing: nothing to tap before the table
  expect(host.querySelector(".lobby-screen")).toBeNull();
  expect(host.textContent).not.toContain("Play offline vs bots");
  await until(() => host.querySelector(".table-screen") !== null);
  expect(host.querySelector(".lobby-screen, .room-screen")).toBeNull();
  expect(host.querySelector(".hud-bar .mode-chip")!.textContent).toBe("Practice");
  // three bots took the other seats; you sit under your saved name
  expect(host.textContent).toContain("Cheerful Tractor");
  expect(host.querySelectorAll(".opponent").length).toBe(3);
});
