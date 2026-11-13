// Opening the app resumes the room this browser was last in. When that room is gone (it expired, or
// a deploy restarted the server) the player did not ask to join anything, so no error is shown; a
// join they start themselves still reports it.
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
  readyState = 1;
  constructor() { FakeWS.all.push(this); }
  send(raw: string) { this.sent.push(JSON.parse(raw)); }
  close() { this.readyState = 3; this.onclose?.(); }
  deliver(msg: unknown) { this.onmessage?.({ data: JSON.stringify(msg) }); }
}

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
const reload = vi.fn();
const realLocation = window.location;
beforeEach(() => {
  FakeWS.all = [];
  localStorage.clear();
  (globalThis as unknown as { WebSocket: unknown }).WebSocket = FakeWS;
  // The audio module unlocks on the first click; jsdom has no Web Audio.
  (window as unknown as { AudioContext: unknown }).AudioContext = class {
    state = "running";
    resume() { return Promise.resolve(); }
  };
  Object.defineProperty(window, "location", { configurable: true, value: { ...realLocation, reload, search: "" } });
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", { configurable: true, value() { (this as HTMLDialogElement).setAttribute("open", ""); } });
  Object.defineProperty(HTMLDialogElement.prototype, "close", { configurable: true, value() { (this as HTMLDialogElement).removeAttribute("open"); } });
  vi.resetModules();
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  Object.defineProperty(window, "location", { configurable: true, value: realLocation });
});

it("a failed automatic resume returns to the lobby without an error", async () => {
  const { default: App } = await import("./App");
  const { saveRoom, saveName, getSavedRoom } = await import("./ws");
  saveName("Me");
  saveRoom("ABCD");
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  act(() => root.render(<App />));
  const ws = FakeWS.all[0];
  act(() => ws.onopen?.());
  expect(ws.sent.map((m) => m.type)).toEqual(["join_room"]);
  act(() => ws.deliver({ type: "error", code: "room_not_found", message: "Room not found" }));
  expect(getSavedRoom()).toBeNull();
  expect(host.querySelector(".lobby-panel")).not.toBeNull();
  expect(host.textContent).not.toContain("That game has ended.");
});

it("a join the player starts still reports a room that has ended", async () => {
  const { default: App } = await import("./App");
  const { saveName } = await import("./ws");
  saveName("Me");
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  act(() => root.render(<App />));
  const ws = FakeWS.all[0];
  act(() => ws.onopen?.());
  expect(ws.sent).toEqual([]);   // nothing saved, nothing resumed
  act(() => ws.deliver({ type: "error", code: "room_not_found", message: "Room not found" }));
  expect(host.textContent).toContain("That game has ended.");
});

it("reports an explicit missing-room join after an automatic resume was refused", async () => {
  const { default: App } = await import("./App");
  const { saveRoom, saveName } = await import("./ws");
  saveName("Me");
  saveRoom("ABCD");
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  act(() => root.render(<App />));
  const ws = FakeWS.all[0];
  act(() => ws.onopen?.());
  act(() => ws.deliver({ type: "error", code: "room_full", message: "Room is full" }));
  const input = host.querySelector<HTMLInputElement>(".room-input")!;
  act(() => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, "WXYZ");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  act(() => host.querySelector<HTMLButtonElement>(".join-row button")!.click());
  expect(ws.sent.at(-1)).toEqual({ type: "code_lookup", code: "WXYZ" });
  act(() => ws.deliver({ type: "code_kind", code: "WXYZ", kind: "room" }));
  expect(ws.sent.at(-1)).toMatchObject({ type: "peek_room", room: "WXYZ" });
  act(() => ws.deliver({ type: "error", code: "room_not_found", message: "Room not found" }));
  expect(host.textContent).toContain("That game has ended.");
});

it("a signed-out player's saved ranked seat asks them to sign in again and keeps the room", async () => {
  const { default: App } = await import("./App");
  const { saveRoom, saveName, getSavedRoom } = await import("./ws");
  saveName("Me");
  saveRoom("ABCD");
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  act(() => root.render(<App />));
  const ws = FakeWS.all[0];
  act(() => ws.onopen?.());
  act(() => ws.deliver({ type: "error", code: "ranked_queue_only", message: "Ranked games are joined through the queue." }));
  expect(host.textContent).toContain("Sign in again to return to your game.");
  expect(getSavedRoom()).toBe("ABCD");
});
