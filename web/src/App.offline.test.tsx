// Offline mode has nothing to choose: it opens straight into a game against
// bots under the saved name, with no landing page, through the real in-page
// server. Leaving that game goes to the home Play tab; it never deals again.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

let host: HTMLDivElement;
let assign: ReturnType<typeof vi.fn>;
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
    value: { ...realLocation, search: "?offline=1", protocol: "http:", assign: (assign = vi.fn()), reload: vi.fn() } });
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

it("Leave goes to the home Play tab and starts no new game", async () => {
  const { saveName } = await import("./ws");
  saveName("Cheerful Tractor");
  const { default: App } = await import("./App");
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  act(() => root.render(<App />));
  await until(() => host.querySelector(".table-screen") !== null);
  act(() => host.querySelector<HTMLButtonElement>(".hud-more-btn")!.click());
  act(() => host.querySelector<HTMLButtonElement>(".hud-menu-row.leave")!.click());
  const alert = host.querySelector("[role='alertdialog']")!;
  expect(alert.querySelector("p")!.textContent).toBe("This practice game ends.");
  act(() => alert.querySelector<HTMLButtonElement>(".leave-alert-leave")!.click());
  // home is the online page; this test's location stands still, so watch for a redeal
  await until(() => host.querySelector(".table-screen") === null);
  expect(assign).toHaveBeenCalledWith("?offline=0");
  await act(async () => { await new Promise((r) => setTimeout(r, 300)); });
  expect(host.querySelector(".table-screen")).toBeNull();
  expect(assign).toHaveBeenCalledTimes(1);
});

it("in the app with no network, Leave shows the Play tab's no-connection state, and Play bots reloads for a fresh game", async () => {
  Object.defineProperty(window, "location", { configurable: true,
    value: { ...realLocation, search: "", protocol: "capacitor:", assign: (assign = vi.fn()), reload: vi.fn() } });
  Object.defineProperty(navigator, "onLine", { configurable: true, get: () => false });
  vi.useFakeTimers({ shouldAdvanceTime: true });
  try {
    const { default: App } = await import("./App");
    host = document.createElement("div");
    document.body.appendChild(host);
    root = createRoot(host);
    act(() => root.render(<App />));
    await until(() => host.querySelector(".table-screen") !== null);
    act(() => host.querySelector<HTMLButtonElement>(".hud-more-btn")!.click());
    expect([...host.querySelectorAll(".hud-menu-row")].map((r) => r.textContent)).not.toContain("Play online");
    act(() => host.querySelector<HTMLButtonElement>(".hud-menu-row.leave")!.click());
    act(() => host.querySelector<HTMLButtonElement>(".leave-alert-leave")!.click());
    await until(() => host.querySelector(".play-tab") !== null);
    expect(host.querySelector(".table-screen")).toBeNull();
    expect(assign).not.toHaveBeenCalled();
    await act(async () => { vi.advanceTimersByTime(5000); });
    expect(host.textContent).toContain("No connection");
    const bots = [...host.querySelectorAll<HTMLElement>("button, [role='button']")].find((b) => /Play bots/.test(b.textContent ?? ""));
    expect(bots).toBeTruthy();
    act(() => bots!.click());
    expect(assign).toHaveBeenCalledWith("?offline=1");
  } finally {
    vi.useRealTimers();
    Reflect.deleteProperty(navigator, "onLine");
  }
});
