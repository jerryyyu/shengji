// Offline is a state of the Play tab: Casual only, Ranked, Duo and the code
// box disabled, a grey "Offline" line, and a Play that opens your table with
// three bots on this device, through the real in-page server. An offline game
// stays offline until you leave it; then Play is online again if the network is up.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

let host: HTMLDivElement;
let assign: ReturnType<typeof vi.fn>;
let root: ReturnType<typeof createRoot>;
let netUp = true;
const realLocation = window.location;
const realFetch = globalThis.fetch;
let fetched: string[];
function at(search: string, protocol = "http:") {
  Object.defineProperty(window, "location", { configurable: true,
    value: { ...realLocation, search, protocol, pathname: "/", assign: (assign = vi.fn()), reload: vi.fn() } });
}
beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  netUp = true;
  Object.defineProperty(navigator, "onLine", { configurable: true, get: () => netUp });
  (window as unknown as { AudioContext: unknown }).AudioContext = class {
    state = "running";
    resume() { return Promise.resolve(); }
  };
  at("?offline=1&table=1");
  fetched = [];
  globalThis.fetch = vi.fn((input: RequestInfo | URL) => {
    fetched.push(String(input));
    return Promise.reject(new Error("no network in this test"));
  }) as typeof fetch;
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", { configurable: true, value() { (this as HTMLDialogElement).setAttribute("open", ""); } });
  Object.defineProperty(HTMLDialogElement.prototype, "close", { configurable: true, value() { (this as HTMLDialogElement).removeAttribute("open"); } });
  vi.resetModules();
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  Object.defineProperty(window, "location", { configurable: true, value: realLocation });
  Reflect.deleteProperty(navigator, "onLine");
  globalThis.fetch = realFetch;
  sessionStorage.clear();
});

async function until(check: () => boolean, ms = 5000): Promise<void> {
  const end = Date.now() + ms;
  while (!check()) {
    if (Date.now() > end) throw new Error("timed out");
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
  }
}

async function mount(name = "Cheerful Tractor") {
  const { OFFLINE, saveName } = await import("./ws");
  expect(OFFLINE).toBe(true);
  saveName(name);
  const { default: App } = await import("./App");
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  act(() => root.render(<App />));
}

const button = (label: string) =>
  [...host.querySelectorAll<HTMLButtonElement>("button")].find((b) => b.textContent === label);
const panel = () => host.querySelector(".tp-offline");

async function startGame() {
  await until(() => panel() !== null && button("Start")?.disabled === false);
  act(() => button("Start")!.click());
  await until(() => host.querySelector(".table-screen") !== null);
}

async function leaveGame() {
  act(() => host.querySelector<HTMLButtonElement>(".hud-more-btn")!.click());
  act(() => host.querySelector<HTMLButtonElement>(".hud-menu-row.leave")!.click());
  act(() => host.querySelector<HTMLButtonElement>(".leave-alert-leave")!.click());
  await until(() => host.querySelector(".table-screen") === null);
}

function expectOfflinePlayTab() {
  expect(host.querySelector(".play-offline")).not.toBeNull();
  expect(button("Ranked")!.disabled).toBe(true);
  expect(button("Casual")!.getAttribute("aria-pressed")).toBe("true");
  expect(button("Duo")!.disabled).toBe(true);
  expect(button("Join")!.disabled).toBe(true);
  expect(host.querySelector<HTMLInputElement>(".room-input")!.disabled).toBe(true);
  expect(host.querySelector(".play-presence.offline")!.textContent).toBe("Offline");
}

it("in the app with no network at launch, Play shows its offline state and deals nothing by itself", async () => {
  at("", "capacitor:");
  netUp = false;
  await mount();
  await until(() => host.querySelector(".play-offline") !== null);
  expectOfflinePlayTab();
  await act(async () => { await new Promise((r) => setTimeout(r, 300)); });
  expect(host.querySelector(".table-screen, .room-screen")).toBeNull();
  expect(panel()).toBeNull();
  expect(assign).not.toHaveBeenCalled();
});

it("Play opens your table with three bots, marked Offline, and Start deals under the saved name", async () => {
  at("", "capacitor:");
  netUp = false;
  await mount();
  await until(() => host.querySelector(".play-offline") !== null);
  act(() => button("Play")!.click());
  expect(panel()!.querySelector(".tp-line")!.textContent).toBe("Offline");
  expect(panel()!.querySelector(".tp-title")!.textContent).toBe("You and 3 bots");
  expect(panel()!.querySelectorAll(".tp-seat.bot").length).toBe(3);
  await startGame();
  expect(host.querySelector(".lobby-screen, .room-screen")).toBeNull();
  expect(host.querySelector(".hud-bar .mode-chip")!.textContent).toBe("Offline");
  expect(host.textContent).toContain("Cheerful Tractor");
  expect(host.querySelectorAll(".opponent").length).toBe(3);
  expect(assign).not.toHaveBeenCalled();
});

it("a browser sent to play offline opens straight at the offline table", async () => {
  await mount();
  await until(() => panel() !== null);
  expect(host.querySelector(".table-screen")).toBeNull();
  expect(assign).not.toHaveBeenCalled();
});

it("the network coming back mid-game changes nothing, and ⋯ has no Play online", async () => {
  at("", "capacitor:");
  netUp = false;
  await mount();
  await until(() => host.querySelector(".play-offline") !== null);
  act(() => button("Play")!.click());
  await startGame();
  netUp = true;
  await act(async () => { window.dispatchEvent(new Event("online")); });
  await act(async () => { await new Promise((r) => setTimeout(r, 200)); });
  expect(host.querySelector(".table-screen")).not.toBeNull();
  expect(assign).not.toHaveBeenCalled();
  act(() => host.querySelector<HTMLButtonElement>(".hud-more-btn")!.click());
  expect([...host.querySelectorAll(".hud-menu-row")].map((r) => r.textContent)).not.toContain("Play online");
});

it("leaving the offline game in the app with the network up goes back to the online Play tab", async () => {
  at("", "capacitor:");
  await mount();
  await until(() => host.querySelector(".play-offline") !== null);
  // a launch whose live site did not load stays here: the shell would only bring this page back
  expect(assign).not.toHaveBeenCalled();
  act(() => button("Play")!.click());
  await startGame();
  await leaveGame();
  await until(() => assign.mock.calls.length > 0);
  expect(assign).toHaveBeenCalledWith("https://shengji.fly.dev/");
  expect(assign).toHaveBeenCalledTimes(1);
});

it("leaving the offline game in a browser goes back to the online Play tab and deals no new game", async () => {
  await mount();
  await startGame();
  await leaveGame();
  await until(() => assign.mock.calls.length > 0);
  expect(assign).toHaveBeenCalledWith("?offline=0");
  await act(async () => { await new Promise((r) => setTimeout(r, 300)); });
  expect(host.querySelector(".table-screen")).toBeNull();
  expect(assign).toHaveBeenCalledTimes(1);
});

it("with no network, leaving keeps the offline Play tab until the network is back", async () => {
  at("", "capacitor:");
  netUp = false;
  await mount();
  await until(() => host.querySelector(".play-offline") !== null);
  act(() => button("Play")!.click());
  await startGame();
  await leaveGame();
  await until(() => host.querySelector(".play-offline") !== null);
  expectOfflinePlayTab();
  expect(panel()).toBeNull();
  expect(assign).not.toHaveBeenCalled();
  netUp = true;
  await act(async () => { window.dispatchEvent(new Event("online")); });
  expect(assign).toHaveBeenCalledWith("https://shengji.fly.dev/");
});

it("Leave on the offline table before Start puts Play back, online when the network is up", async () => {
  await mount();
  await until(() => panel() !== null);
  act(() => button("Leave")!.click());
  expect(panel()).toBeNull();
  expect(assign).toHaveBeenCalledWith("?offline=0");
});

it("an offline game never reaches the server, so Me's stats (server-only) do not count it", async () => {
  await mount();
  await startGame();
  await leaveGame();
  await until(() => assign.mock.calls.length > 0);
  // stats, saved games and telemetry all go through /api; offline mode calls none of them
  expect(fetched.filter((u) => u.includes("/api/"))).toEqual([]);
});
