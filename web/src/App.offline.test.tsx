// Offline is a state of the Play tab: Casual only, Ranked, Duo and the code
// box disabled, a grey "Offline" line, and a Play that opens your table with
// three bots on this device, through the real in-page server. The page goes
// offline and back in place: the socket swaps servers, nothing reloads or
// navigates (the app's bundled page, which has no game server, loads the live
// site to go online). An offline game stays offline until you leave it; then
// Play is online again if the network is up.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

class FakeWS {
  static OPEN = 1;
  static all: FakeWS[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  sent: { type: string }[] = [];
  readyState = 0;
  constructor() { FakeWS.all.push(this); }
  send(raw: string) { this.sent.push(JSON.parse(raw)); }
  open() { this.readyState = 1; this.onopen?.(); }
  close() { this.readyState = 3; this.onclose?.(); }
}
const latestWS = () => FakeWS.all[FakeWS.all.length - 1];

let host: HTMLDivElement;
let assign: ReturnType<typeof vi.fn>;
let reload: ReturnType<typeof vi.fn>;
let pushState: ReturnType<typeof vi.spyOn>;
let root: ReturnType<typeof createRoot>;
let netUp = true;
const realLocation = window.location;
const realFetch = globalThis.fetch;
let fetched: string[];
function at(search: string, protocol = "http:") {
  Object.defineProperty(window, "location", { configurable: true,
    value: { ...realLocation, search, protocol, pathname: "/", hash: "", assign: (assign = vi.fn()), reload: (reload = vi.fn()) } });
}
beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  netUp = true;
  FakeWS.all = [];
  (globalThis as unknown as { WebSocket: unknown }).WebSocket = FakeWS;
  pushState = vi.spyOn(window.history, "pushState");
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
  pushState.mockRestore();
});

/** Nothing reloaded or navigated the page. */
function expectNoReload() {
  expect(assign).not.toHaveBeenCalled();
  expect(reload).not.toHaveBeenCalled();
  expect(pushState).not.toHaveBeenCalled();
}

async function until(check: () => boolean, ms = 5000): Promise<void> {
  const end = Date.now() + ms;
  while (!check()) {
    if (Date.now() > end) throw new Error("timed out");
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
  }
}

async function mount(name = "Cheerful Tractor", offline = true) {
  const { OFFLINE, saveName } = await import("./ws");
  expect(OFFLINE).toBe(offline);
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
  act(() => host.querySelector<HTMLButtonElement>(".leave-sheet-leave")!.click());
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
  expect(host.querySelector(".table-screen")).toBeNull();
  expect(panel()).toBeNull();
  expect(assign).not.toHaveBeenCalled();
});

it("Play opens your table with three bots, marked Offline, and Start deals under the saved name", async () => {
  at("", "capacitor:");
  netUp = false;
  await mount();
  await until(() => host.querySelector(".play-offline") !== null);
  act(() => button("Play")!.click());
  // Offline is the mode tag above the title, not a status line
  expect(panel()!.querySelector(".tp-tag")!.textContent).toBe("Offline");
  expect(panel()!.querySelector(".tp-tag + .tp-title")).not.toBeNull();
  expect(panel()!.querySelector(".tp-line")).toBeNull();
  expect(panel()!.querySelector(".tp-title")!.textContent).toBe("You and 3 bots");
  expect(panel()!.querySelectorAll(".tp-seat.bot").length).toBe(3);
  // the table's chat row is in its place, greyed: chat needs the server
  const chat = panel()!.querySelector<HTMLButtonElement>(".tp-chat")!;
  expect(chat.disabled).toBe(true);
  expect(chat.getAttribute("aria-label")).toBe("Chat needs a connection");
  await startGame();
  expect(host.querySelector(".lobby-screen")).toBeNull();
  // offline is plain from the screen: no mode in the header, none in ⋯
  expect(host.querySelector(".hud-bar")!.textContent).not.toMatch(/Ranked|Casual/);
  expect(host.querySelector(".hud-menu-mode")).toBeNull();
  expect(host.textContent).toContain("Cheerful Tractor");
  expect(host.querySelectorAll(".opponent").length).toBe(3);
  expect(assign).not.toHaveBeenCalled();
});

it("Start sends one create_room with start, and the local server deals it", async () => {
  await mount();
  const { conn } = await import("./ws");
  const send = vi.spyOn(conn, "send");
  await startGame();
  const sent = send.mock.calls.map(([m]) => m).filter((m) => m.type !== "ping");
  expect(sent).toEqual([{ type: "create_room", name: "Cheerful Tractor", start: true }]);
  expect(host.querySelectorAll(".opponent").length).toBe(3);
  send.mockRestore();
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

/** An online page's Play tab, its socket to the game server open. */
async function mountOnline() {
  at("");
  await mount("Cheerful Tractor", false);
  act(() => latestWS().open());
  await until(() => host.querySelector(".play-tab") !== null);
  expect(host.querySelector(".play-offline")).toBeNull();
}

const playOfflineLink = () =>
  [...host.querySelectorAll<HTMLButtonElement>(".howto-entry button")].find((b) => b.textContent === "Play offline");

it("Play offline on an online page opens the same Play page with the offline panel, with no reload", async () => {
  await mountOnline();
  const playTab = host.querySelector(".play-tab");
  const network = latestWS();
  act(() => playOfflineLink()!.click());
  await until(() => panel() !== null && button("Start")?.disabled === false);
  // the same Play page, not a page of its own: its screen element stayed mounted
  expect(host.querySelector(".play-tab")).toBe(playTab);
  expect(host.querySelector(".play-tab.play-offline")).not.toBeNull();
  expect(host.querySelector(".app.offline")).not.toBeNull();
  expect(button("Ranked")!.disabled).toBe(true);
  expect(playOfflineLink()).toBeUndefined();
  expectNoReload();
  // the game server's socket was closed and hears nothing from the offline table
  expect(network.readyState).toBe(3);
  const sentBefore = network.sent.length;
  await startGame();
  expect(host.querySelectorAll(".opponent").length).toBe(3);
  expect(network.sent.length).toBe(sentBefore);
  expect(FakeWS.all.length).toBe(1);
  expectNoReload();
});

it("on a page that went offline, the network coming back mid-game changes nothing", async () => {
  await mountOnline();
  act(() => playOfflineLink()!.click());
  await startGame();
  netUp = true;
  await act(async () => {
    window.dispatchEvent(new Event("online"));
    window.dispatchEvent(new Event("pageshow"));
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await act(async () => { await new Promise((r) => setTimeout(r, 300)); });
  expect(host.querySelector(".table-screen")).not.toBeNull();
  expect(FakeWS.all.length).toBe(1);
  expectNoReload();
});

it("leaving the offline game goes back to the online Play tab in place and reconnects to the game server", async () => {
  await mountOnline();
  act(() => playOfflineLink()!.click());
  await startGame();
  await leaveGame();
  await until(() => FakeWS.all.length === 2);
  expectNoReload();
  act(() => latestWS().open());
  await until(() => host.querySelector(".play-tab") !== null && host.querySelector(".play-offline") === null);
  expect(host.querySelector(".app.offline")).toBeNull();
  expect(panel()).toBeNull();
  expect(playOfflineLink()).not.toBeUndefined();
  // a fresh online socket: no room to resume, nothing of the offline game sent
  expect(latestWS().sent.filter((m) => m.type !== "ping")).toEqual([]);
  await act(async () => { await new Promise((r) => setTimeout(r, 300)); });
  expect(host.querySelector(".table-screen")).toBeNull();
  expectNoReload();
});

it("Leave on the offline table before Start puts online Play back in place", async () => {
  await mountOnline();
  act(() => playOfflineLink()!.click());
  await until(() => panel() !== null);
  act(() => button("Leave")!.click());
  expect(panel()).toBeNull();
  await until(() => FakeWS.all.length === 2);
  act(() => latestWS().open());
  await until(() => host.querySelector(".play-offline") === null);
  expectNoReload();
});

it("cancelling Start before its local room reply sends nothing to a later online room", async () => {
  await mountOnline();
  act(() => playOfflineLink()!.click());
  await until(() => panel() !== null && button("Start")?.disabled === false);
  // The local server answers create_room on a timer. Leave while that reply
  // is still pending, then return to the remote transport.
  act(() => button("Start")!.click());
  act(() => button("Leave")!.click());
  await until(() => FakeWS.all.length === 2);
  const remote = latestWS();
  act(() => remote.open());
  await until(() => host.querySelector(".play-offline") === null);

  act(() => remote.onmessage?.({ data: JSON.stringify({
    type: "room", room: "WXYZ", you: 0, host: 0, start_level: "2",
    players: [{ seat: 0, name: "Cheerful Tractor", is_bot: false, connected: true }],
  }) }));
  expect(remote.sent.filter((m) => m.type === "add_bot" || m.type === "start_game")).toEqual([]);
});

it("a page opened offline in a browser goes online in place once its table is left", async () => {
  await mount();
  await until(() => panel() !== null);
  act(() => button("Leave")!.click());
  await until(() => FakeWS.all.length === 1);
  act(() => latestWS().open());
  await until(() => host.querySelector(".play-offline") === null);
  expectNoReload();
});

it("an offline game never reaches the server, so Me's stats (server-only) do not count it", async () => {
  await mountOnline();
  const network = latestWS();
  act(() => playOfflineLink()!.click());
  const fetchedBefore = fetched.length;
  await startGame();
  await leaveGame();
  await until(() => FakeWS.all.length === 2);
  // stats, saved games and telemetry all go through /api or the game server's
  // socket; the offline game reached neither
  expect(fetched.slice(fetchedBefore).filter((u) => u.includes("/api/"))).toEqual([]);
  expect(network.sent.map((m) => m.type)).not.toContain("create_room");
  expect(latestWS().sent).toEqual([]);
});

it("when the network is lost on the Play tab, Play there opens the offline table in place", async () => {
  await mountOnline();
  const playTab = host.querySelector(".play-tab");
  netUp = false;
  act(() => latestWS().close());
  // the Play tab greys in place once the connection has stayed down
  await until(() => host.querySelector(".play-offline") !== null, 8000);
  expect(host.querySelector(".play-presence.offline")!.textContent).toBe("Offline");
  const sockets = FakeWS.all.length;
  act(() => button("Play")!.click());
  await until(() => panel() !== null && button("Start")?.disabled === false);
  expect(host.querySelector(".play-tab")).toBe(playTab);
  expectNoReload();
  await startGame();
  expect(FakeWS.all.length).toBe(sockets);
}, 15000);

it("cancelling Start before its room comes back, with no network, deals no game", async () => {
  at("", "capacitor:");
  netUp = false;
  await mount();
  await until(() => host.querySelector(".play-offline") !== null);
  act(() => button("Play")!.click());
  await until(() => panel() !== null && button("Start")?.disabled === false);
  act(() => button("Start")!.click());
  act(() => button("Leave")!.click());
  expect(panel()).toBeNull();
  await act(async () => { await new Promise((r) => setTimeout(r, 500)); });
  expect(host.querySelector(".table-screen")).toBeNull();
  expectOfflinePlayTab();
  // Play opens a fresh table, and its Start still deals
  act(() => button("Play")!.click());
  await startGame();
});
