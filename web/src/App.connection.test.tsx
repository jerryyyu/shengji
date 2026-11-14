// One connection surface: a dropped socket shows the same pill in the lobby
// and at the table, Retry joins it after RETRY_AFTER_MS, one full screen
// takes over after LOST_AFTER_MS, and a reconnect clears all of it while the
// saved seat is resumed exactly as before.
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
  sent: { type: string; room?: string; token?: string }[] = [];
  readyState = 0;
  constructor() { FakeWS.all.push(this); }
  send(raw: string) { this.sent.push(JSON.parse(raw)); }
  open() { this.readyState = 1; this.onopen?.(); }
  close() { this.readyState = 3; this.onclose?.(); }
  deliver(msg: unknown) { this.onmessage?.({ data: JSON.stringify(msg) }); }
}

const player = (seat: number) => ({
  seat, name: seat ? `Bot ${seat}` : "Me", is_bot: seat !== 0, connected: true, team: seat % 2,
  cards_left: 25, is_banker: seat === 1, takeover_in: null, controller: seat ? "bot" : "human",
  reserved_for: null, reserved_secs: null,
});
const playing = {
  type: "state", room: "ABCD", you: 0, phase: "play",
  players: [0, 1, 2, 3].map(player),
  hand: [{ id: 1, code: "S6" }, { id: 2, code: "D9" }], levels: ["2", "2"], games_won: [0, 0], banker: 1,
  trump: { suit: "H", rank: "2", declarer: 1 }, turn: 0, declare_options: [],
  current_declaration: null, passed: [], trick: { leader: 1, plays: [{ seat: 1, cards: ["DA"] }] },
  last_trick: null, attacker_points: 0, kitty_count: 8, message: null, notice: null, round_result: null,
};

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
const realLocation = window.location;
const assign = vi.fn();
beforeEach(() => {
  vi.useFakeTimers();
  FakeWS.all = [];
  assign.mockReset();
  localStorage.clear();
  (globalThis as unknown as { WebSocket: unknown }).WebSocket = FakeWS;
  (window as unknown as { AudioContext: unknown }).AudioContext = class {
    state = "running";
    resume() { return Promise.resolve(); }
  };
  Object.defineProperty(window, "location", { configurable: true, value: { ...realLocation, assign, search: "" } });
  vi.resetModules();
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  Object.defineProperty(window, "location", { configurable: true, value: realLocation });
  vi.useRealTimers();
});

async function mount() {
  const { default: App } = await import("./App");
  const ws = await import("./ws");
  const pill = await import("./components/ConnectionPill");
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  act(() => root.render(<App />));
  return { ws, ...pill };
}
const latest = () => FakeWS.all[FakeWS.all.length - 1];
const banner = () => host.querySelector<HTMLElement>(".reconnect-banner");
const retryIn = () => host.querySelector<HTMLButtonElement>(".reconnect-banner .reconnect-retry");
const lost = () => host.querySelector<HTMLElement>(".conn-lost");

it("at the table a drop shows the pill, Retry at 10 s, the full screen at 60 s, and a reconnect resumes the seat and clears it", async () => {
  const { ws, RETRY_AFTER_MS, LOST_AFTER_MS } = await mount();
  ws.saveName("Me");
  act(() => latest().open());
  act(() => latest().deliver({ type: "resume", room: "ABCD", token: "tok-1" }));
  act(() => latest().deliver(playing));
  ws.saveRoom("ABCD");
  expect(host.querySelector(".table-screen")).not.toBeNull();
  expect(banner()).toBeNull();

  act(() => latest().close());
  expect(banner()?.textContent).toBe("Reconnecting…");
  expect(retryIn()).toBeNull();
  expect(host.querySelectorAll(".reconnect-banner, .table-stalled, .play-conn")).toHaveLength(1);
  // the socket's own backoff keeps trying underneath; none of those tries opens
  act(() => { vi.advanceTimersByTime(RETRY_AFTER_MS - 1); });
  expect(retryIn()).toBeNull();
  act(() => { vi.advanceTimersByTime(1); });
  expect(retryIn()?.textContent).toBe("Retry");
  expect(host.querySelector(".table-screen")).not.toBeNull();

  // Retry opens a new socket at once and starts the wait over
  const before = FakeWS.all.length;
  act(() => retryIn()!.click());
  act(() => { vi.advanceTimersByTime(0); });
  expect(FakeWS.all.length).toBeGreaterThan(before);
  expect(retryIn()).toBeNull();
  expect(banner()?.textContent).toBe("Reconnecting…");

  act(() => { vi.advanceTimersByTime(LOST_AFTER_MS); });
  expect(banner()).toBeNull();
  expect(lost()?.querySelector("h1")?.textContent).toBe("No connection");
  expect(lost()?.textContent).toContain("a bot in your seat");
  // in a game, the full screen offers no way out of it
  expect(host.querySelector(".conn-lost-bots")).toBeNull();
  expect(host.querySelector(".conn-lost-retry")?.textContent).toBe("Retry");

  // back online: the saved seat is asked for by its token, and every surface clears
  const back = latest();
  act(() => back.open());
  expect(back.sent).toEqual([expect.objectContaining({ type: "join_room", room: "ABCD", token: "tok-1" })]);
  expect(lost()).toBeNull();
  expect(banner()).toBeNull();
  act(() => back.deliver(playing));
  expect(host.querySelector(".table-screen")).not.toBeNull();
});

it("in the lobby the same pill shows, and the full screen offers Retry and bots on this device", async () => {
  const { LOST_AFTER_MS, RETRY_AFTER_MS } = await mount();
  // the first connect of a page is not a drop
  expect(banner()?.textContent).toBe("Connecting…");
  expect(banner()?.classList.contains("at-home")).toBe(true);
  act(() => latest().open());
  expect(banner()).toBeNull();
  expect(host.querySelector(".play-tab")).not.toBeNull();

  act(() => latest().close());
  expect(banner()?.textContent).toBe("Reconnecting…");
  expect(host.querySelector(".play-conn")).toBeNull();          // no second status row in the lobby
  act(() => { vi.advanceTimersByTime(RETRY_AFTER_MS); });
  expect(retryIn()).not.toBeNull();
  act(() => { vi.advanceTimersByTime(LOST_AFTER_MS - RETRY_AFTER_MS); });
  expect(lost()).not.toBeNull();
  expect(lost()?.textContent).not.toContain("bot in your seat");

  // Retry from the full screen goes back to the pill and starts the wait over
  act(() => host.querySelector<HTMLButtonElement>(".conn-lost-retry")!.click());
  expect(lost()).toBeNull();
  expect(banner()?.textContent).toBe("Reconnecting…");
  act(() => { vi.advanceTimersByTime(LOST_AFTER_MS); });
  act(() => host.querySelector<HTMLButtonElement>(".conn-lost-bots")!.click());
  expect(assign).toHaveBeenCalledWith("?offline=1");

  act(() => latest().open());
  expect(lost()).toBeNull();
  expect(banner()).toBeNull();
});

it("a short blip clears before Retry ever shows", async () => {
  const { RETRY_AFTER_MS } = await mount();
  act(() => latest().open());
  act(() => latest().close());
  act(() => { vi.advanceTimersByTime(600); });
  act(() => latest().open());
  expect(banner()).toBeNull();
  act(() => { vi.advanceTimersByTime(RETRY_AFTER_MS * 7); });
  expect(banner()).toBeNull();
  expect(lost()).toBeNull();
});

const tab = (shift = false) => act(() => {
  (document.activeElement ?? document.body).dispatchEvent(
    new KeyboardEvent("keydown", { key: "Tab", shiftKey: shift, bubbles: true, cancelable: true }));
});
const focusables = () => [...host.querySelectorAll<HTMLElement>("button:not([disabled]), input:not([disabled]), a[href]")];

it("the full screen is modal: Retry has focus, Tab stays inside, the page behind is inert, and recovery gives focus back", async () => {
  const { LOST_AFTER_MS } = await mount();
  act(() => latest().open());
  const howto = [...host.querySelectorAll<HTMLButtonElement>("button")].find((b) => b.textContent === "How to play")!;
  act(() => howto.focus());
  act(() => latest().close());
  act(() => { vi.advanceTimersByTime(LOST_AFTER_MS); });

  const modal = lost()!;
  const retry = modal.querySelector<HTMLButtonElement>(".conn-lost-retry")!;
  const bots = modal.querySelector<HTMLButtonElement>(".conn-lost-bots")!;
  expect(modal.tagName).toBe("DIALOG");
  expect(modal.hasAttribute("open")).toBe(true);
  expect(document.activeElement).toBe(retry);
  // Tab and Shift+Tab wrap at its ends (between them the browser moves focus)
  tab(true);
  expect(document.activeElement).toBe(bots);
  tab();
  expect(document.activeElement).toBe(retry);
  // every control outside it sits under an inert ancestor
  const outside = focusables().filter((el) => !modal.contains(el));
  expect(outside.length).toBeGreaterThan(0);
  expect(outside.every((el) => el.closest("[inert]") !== null)).toBe(true);
  expect(modal.closest("[inert]")).toBeNull();
  // Escape does not dismiss it
  act(() => { document.activeElement!.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true })); });
  expect(lost()).not.toBeNull();

  act(() => latest().open());
  expect(lost()).toBeNull();
  expect(host.querySelector("[inert]")).toBeNull();
  expect(document.activeElement).toBe(howto);
});

it("Retry from the full screen gives focus back too, and a modal at the table holds a single Tab stop", async () => {
  const { ws, LOST_AFTER_MS } = await mount();
  ws.saveName("Me");
  act(() => latest().open());
  act(() => latest().deliver(playing));
  const more = host.querySelector<HTMLButtonElement>(".hud-more-btn")!;
  act(() => more.focus());
  act(() => latest().close());
  act(() => { vi.advanceTimersByTime(LOST_AFTER_MS); });
  const retry = lost()!.querySelector<HTMLButtonElement>(".conn-lost-retry")!;
  expect(document.activeElement).toBe(retry);
  tab();
  expect(document.activeElement).toBe(retry);
  tab(true);
  expect(document.activeElement).toBe(retry);
  act(() => retry.click());
  expect(lost()).toBeNull();
  expect(document.activeElement).toBe(more);
});

it("with a sheet already open, the full screen sits above it and Retry is reachable", async () => {
  const { LOST_AFTER_MS } = await mount();
  act(() => latest().open());
  act(() => host.querySelector<HTMLButtonElement>(".guest-pill")!.click());
  const sheet = host.querySelector<HTMLElement>(".q-sheet")!;
  expect(sheet).not.toBeNull();
  expect(sheet.contains(document.activeElement)).toBe(true);
  act(() => latest().close());
  act(() => { vi.advanceTimersByTime(LOST_AFTER_MS); });

  const modal = lost()!;
  const retry = modal.querySelector<HTMLButtonElement>(".conn-lost-retry")!;
  expect(document.activeElement).toBe(retry);
  expect(sheet.closest("[inert]")).not.toBeNull();
  // the sheet's own Tab trap and Escape never see keys pressed in the modal
  tab();
  expect(modal.contains(document.activeElement)).toBe(true);
  tab();
  expect(document.activeElement).toBe(retry);
  act(() => { retry.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true })); });
  expect(host.querySelector(".q-sheet")).not.toBeNull();
  expect(document.activeElement).toBe(retry);

  act(() => latest().open());
  expect(lost()).toBeNull();
  expect(sheet.closest("[inert]")).toBeNull();
  expect(sheet.contains(document.activeElement)).toBe(true);
});

it("with the leave alert open at the table, the full screen still takes focus", async () => {
  const { ws, LOST_AFTER_MS } = await mount();
  ws.saveName("Me");
  act(() => latest().open());
  act(() => latest().deliver(playing));
  act(() => host.querySelector<HTMLButtonElement>(".hud-more-btn")!.click());
  act(() => host.querySelector<HTMLButtonElement>(".hud-menu-row.leave")!.click());
  const alert = host.querySelector<HTMLElement>(".leave-alert-backdrop")!;
  expect(alert.contains(document.activeElement)).toBe(true);
  act(() => latest().close());
  act(() => { vi.advanceTimersByTime(LOST_AFTER_MS); });
  const retry = lost()!.querySelector<HTMLButtonElement>(".conn-lost-retry")!;
  expect(document.activeElement).toBe(retry);
  expect(alert.closest("[inert]")).not.toBeNull();
});
