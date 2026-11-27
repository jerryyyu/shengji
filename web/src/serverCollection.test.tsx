// The Collection's off switch reaches a page already open: each socket's
// heartbeat_ready says whether its account is shown the Collection, and the
// page follows it with no reload, over what /api/auth/config said at load.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { GameState } from "./protocol";

class FakeWS {
  static all: FakeWS[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  readyState = 1;
  constructor() { FakeWS.all.push(this); }
  send() {}
  close() { this.readyState = 3; this.onclose?.(); }
  deliver(msg: unknown) { this.onmessage?.({ data: JSON.stringify(msg) }); }
}

const player = (seat: number) => ({
  seat, name: `P${seat}`, is_bot: false, look: "bun/plain", connected: true, team: seat % 2, cards_left: 25,
  is_banker: false, takeover_in: null, controller: "human", reserved_for: null, reserved_secs: null,
});
const table = {
  room: "ABCD", you: 0, phase: "play", levels: ["2", "2"], players: [0, 1, 2, 3].map(player),
  trick: { leader: 1, plays: [] }, last_trick: null, round_result: null,
} as unknown as GameState;

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
const reload = vi.fn();
const realLocation = window.location;

beforeEach(() => {
  FakeWS.all = [];
  localStorage.clear();
  sessionStorage.clear();
  reload.mockReset();
  (globalThis as unknown as { WebSocket: unknown }).WebSocket = FakeWS;
  Object.defineProperty(window, "location", { configurable: true, value: { ...realLocation, reload } });
  // the page loaded while the Collection was on for everyone
  vi.stubGlobal("fetch", vi.fn(async (path: string) => new Response(
    JSON.stringify(path === "/api/auth/config" ? { google_client_id: null, collection: true } : {}),
    { status: path === "/api/auth/config" ? 200 : 404 })));
  vi.resetModules();
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
  Object.defineProperty(window, "location", { configurable: true, value: realLocation });
});

async function open() {
  const { auth } = await import("./auth");
  const { conn } = await import("./ws");
  const { TabBar } = await import("./home/HomeShell");
  const { default: TableCompanions } = await import("./companion/TableCompanions");
  await act(async () => { await auth.init(); });
  act(() => conn.start());
  const ws = FakeWS.all[FakeWS.all.length - 1];
  act(() => ws.onopen?.());
  await act(async () => {
    root.render(<>
      <TabBar active="play" />
      <div className="felt"><TableCompanions state={table} /></div>
    </>);
  });
  return ws;
}

const tabs = () => [...host.querySelectorAll(".tabbar-item")].map((b) => b.textContent);
const drawn = () => host.querySelector(".table-companions") !== null;

it("a heartbeat_ready saying off hides the table's companions and the Collection tab, with no reload", async () => {
  const ws = await open();
  expect(drawn()).toBe(true);
  expect(tabs()).toContain("Collection");
  // an older server, which names no Collection, changes nothing
  act(() => ws.deliver({ type: "heartbeat_ready" }));
  expect(drawn()).toBe(true);
  expect(tabs()).toContain("Collection");
  act(() => ws.deliver({ type: "heartbeat_ready", collection: false }));
  expect(drawn()).toBe(false);
  expect(tabs()).not.toContain("Collection");
  expect(reload).not.toHaveBeenCalled();
});

it("a heartbeat_ready saying on shows them again", async () => {
  const ws = await open();
  act(() => ws.deliver({ type: "heartbeat_ready", collection: false }));
  expect(drawn()).toBe(false);
  act(() => ws.deliver({ type: "heartbeat_ready", collection: true }));
  expect(drawn()).toBe(true);
  expect(tabs()).toContain("Collection");
});

it("a page that loaded with the Collection off shows it once a socket says on", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ google_client_id: null }), { status: 200 })));
  const ws = await open();
  expect(drawn()).toBe(false);
  expect(tabs()).not.toContain("Collection");
  act(() => ws.deliver({ type: "heartbeat_ready", collection: true }));
  expect(drawn()).toBe(true);
  expect(tabs()).toContain("Collection");
});
