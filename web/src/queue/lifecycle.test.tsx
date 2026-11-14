// Queue lifecycle against a mocked socket: focus while typing a pair code,
// account changes, and a join whose reply died with the socket.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { WIDE } from "../home/HomeShell";

class FakeWS {
  static OPEN = 1;
  static all: FakeWS[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  readyState = 1;
  sent: Record<string, unknown>[] = [];
  constructor() { FakeWS.all.push(this); }
  send(data: string) { this.sent.push(JSON.parse(data)); }
  close() { this.readyState = 3; this.onclose?.(); }
  deliver(msg: unknown) { this.onmessage?.({ data: JSON.stringify(msg) }); }
}

const ws = () => FakeWS.all[FakeWS.all.length - 1];
const say = (msg: unknown) => act(() => ws().deliver(msg));
const lastSent = () => { const all = FakeWS.all.flatMap((w) => w.sent); return all[all.length - 1]; };
const nowSecs = () => Date.now() / 1000;

let signedIn = true;
let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
const realMatchMedia = window.matchMedia;

function viewport(wide: boolean) {
  window.matchMedia = ((q: string) => ({
    matches: q === WIDE ? wide : false, media: q, addEventListener() {}, removeEventListener() {},
  })) as unknown as typeof window.matchMedia;
}

beforeEach(() => {
  FakeWS.all = [];
  signedIn = true;
  localStorage.clear();
  viewport(false);
  (globalThis as unknown as { WebSocket: unknown }).WebSocket = FakeWS;
  (window as unknown as { AudioContext: unknown }).AudioContext = class {
    state = "running";
    resume() { return Promise.resolve(); }
  };
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if ((url === "/api/me" || url.startsWith("/api/me/")) && !signedIn) {
      return { status: 401, json: async () => ({}) } as Response;
    }
    const body = url === "/api/auth/config" ? { google_client_id: "cid" }
      : url === "/api/me" ? { name: "Jerry Yu", email: "j@x", picture: null, display_name: null, name_shown: "Jerry" }
      : null;
    return { status: body ? 200 : 404, json: async () => body ?? {} } as Response;
  }) as typeof fetch;
  vi.resetModules();
});
afterEach(() => {
  vi.useRealTimers();
  act(() => root.unmount());
  host.remove();
  window.matchMedia = realMatchMedia;
  window.history.replaceState(null, "", "/");
});

const settle = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });

async function renderApp() {
  const { default: App } = await import("../App");
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => { root.render(<App />); });
  act(() => ws().onopen?.());
  await settle();
  await settle();
}

const q = (sel: string) => document.querySelector<HTMLElement>(sel);
const buttons = (scope: ParentNode = document) => [...scope.querySelectorAll<HTMLButtonElement>("button")];
const button = (text: string | RegExp, scope: ParentNode = document) => buttons(scope).find((b) => {
  const t = b.textContent ?? "";
  return typeof text === "string" ? t === text : text.test(t);
});
const click = (b: HTMLElement | null | undefined) => {
  if (!b) throw new Error("no such button");
  act(() => b.click());
};
const findBtn = () => q(".q-find")!;

/** Fake clock from here on; the app is already rendered and settled. */
function fakeClock() {
  vi.useFakeTimers({ toFake: ["Date", "setTimeout", "clearTimeout", "setInterval", "clearInterval"] });
}
const tick = (ms: number) => act(() => { vi.advanceTimersByTime(ms); });


it("entering a pair code keeps keyboard focus after each character", async () => {
  await renderApp();
  click(button("Duo"));
  const input = q("#q-join-code") as HTMLInputElement;
  input.focus();
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
  act(() => { setter.call(input, "a"); input.dispatchEvent(new Event("input", { bubbles: true })); });
  expect(input.value).toBe("A");
  expect(document.activeElement).toBe(input);
});

it("a private party is cleared when the account signs out", async () => {
  await renderApp();
  say({type:"party",party_id:"old-user-party",code:"AB12",you_lead:true,members:[{name:"Jerry",leader:true,you:true},{name:"Private Friend",leader:false,you:false}],expires_at:nowSecs()+300});
  const { auth } = await import("../auth");
  signedIn = false;
  await act(async () => { auth.deleted(); });
  const { queue } = await import("./store");
  await act(async () => { auth.signedIn({name:"Other User",email:"other@example.invalid",picture:null,display_name:null,name_shown:"Other"}); });
  expect(q(".q-party-chip")?.textContent ?? "").not.toContain("Private Friend");
  expect(queue.view.party).toBeNull();
});

it("a lost join reply recovers after reconnect without server entry", async () => {
  await renderApp();
  fakeClock();
  click(findBtn());
  expect(lastSent()).toEqual({type:"queue_join"});
  act(() => ws().close());
  tick(2000);
  act(() => ws().onopen?.());
  tick(3000);
  expect((findBtn() as HTMLButtonElement).disabled).toBe(false);
});

it("typing a whole pair code keeps focus on the input for every character", async () => {
  await renderApp();
  click(button("Duo"));
  const input = q("#q-join-code") as HTMLInputElement;
  input.focus();
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
  for (const typed of ["a", "ab", "ab1", "ab12"]) {
    act(() => { setter.call(input, typed); input.dispatchEvent(new Event("input", { bubbles: true })); });
    expect(document.activeElement).toBe(input);
  }
  expect(input.value).toBe("AB12");
  say({ type: "queue_count", count: 5 });
  expect(document.activeElement).toBe(input);
});

it("the next account's pair action carries no stale party id", async () => {
  await renderApp();
  say({type:"party",party_id:"old-user-party",code:"AB12",you_lead:true,members:[{name:"Jerry",leader:true,you:true},{name:"Private Friend",leader:false,you:false}],expires_at:nowSecs()+300});
  const { auth } = await import("../auth");
  await act(async () => { auth.signedIn({name:"Other User",email:"other@example.invalid",picture:null,display_name:null,name_shown:"Other"}); });
  act(() => ws().onopen?.());
  click(findBtn());
  expect(lastSent()).toEqual({ type: "queue_join" });
  expect(q(".q-party-chip")).toBeNull();
});

it("a reply to a join is applied when it lands before sign-in is known", async () => {
  const { queue } = await import("./store");
  await renderApp();
  say({ type: "queue_state", queued: true, count: 2, since: nowSecs(), front: false, party_id: null, leader: true, bots_at: nowSecs() + 60 });
  expect(queue.view.queued).toBe(true);
});
