// Where the server counts the watcher against what the watch screen draws.
// The stubbed feed keeps the server's lease rules (spectate.py `admissible`,
// `admit`, `release`) and answers each read only when the test says, with a
// 200 or a 429, counting the watcher as it answers. After every sequence
// settles, the table drawn is the one table that counts the watcher, and no
// two reads are ever on their way at once.
import { act } from "react";
import { createRoot } from "react-dom/client";
import type { Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import fixture from "../replay/server-round-finished.fixture.json";
import WatchScreen, { FOLLOW_MS, RETRY_MS } from "./WatchScreen";
import { forgetWatcherToken } from "./api";
import { clearToast } from "../toast";

vi.mock("../companion/feature", () => ({ useCollection: () => false }));
vi.mock("../audio", () => ({ prewarmAudio: () => {}, isMuted: () => true, setMuted: () => {},
  subscribeMuted: () => () => {}, play: () => {}, resetAnnouncer: () => {}, announceState: () => {} }));
vi.mock("../queue/store", () => ({ queue: { setPlayMode: () => {}, join: () => {} } }));
vi.mock("../codeJoin", () => ({ codes: { open: () => true } }));
vi.mock("../roundTelemetry", () => ({ rounds: { noteEntry: () => {} } }));
vi.mock("../ws", () => ({ conn: { send: () => true, subscribe: () => () => {}, subscribeStatus: () => () => {},
  status: "open", generation: 1, chatHistory: () => [] } }));

const TABLES = ["aaa111", "bbb222", "ccc333"];
const banker = (fixture.events.find((e) => e.e === "trump") as { banker: number }).banker;
const docOf = (table: string, w: string) => ({
  table, watcher: w, mode: "ranked", live_round: 10, code: null, rerun: false, waiting: false,
  round: 3 + TABLES.indexOf(table), seat: banker, players: ["Mei", "Li", "Alice", "Lin"],
  finished: true, events: fixture.events,
});

/** The server's leases, one token. */
class Leases {
  table: string | null = null;
  epoch = -1;
  seq = 0;
  left = false;
  read(epoch: number, seq: number, table: string, follow: boolean): boolean {
    const ok = epoch > this.epoch
      || (epoch === this.epoch && !this.left && seq >= this.seq && (!follow || this.table === null || this.table === table));
    if (ok) Object.assign(this, { table, epoch, seq, left: false });
    return ok;
  }
  leave(epoch: number): void {
    if (epoch >= this.epoch) Object.assign(this, { table: null, epoch, seq: 0, left: true });
  }
}

interface Pending { url: string; answer: (status: 200 | 429) => void }

let L: Leases;
let pending: Pending[];
let most: number;
let roots: { root: Root; host: HTMLDivElement }[];

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "Date"] });
  sessionStorage.clear();
  forgetWatcherToken();
  L = new Leases();
  pending = [];
  most = 0;
  roots = [];
  Object.defineProperty(navigator, "sendBeacon", { configurable: true, value: (url: string) => {
    L.leave(Number(new URL(url, "http://x").searchParams.get("e")));
    return true;
  } });
  vi.stubGlobal("fetch", vi.fn((url: string) => new Promise<Response>((resolve) => {
    const answer = (status: 200 | 429) => {
      if (status === 429) { resolve(new Response("{}", { status: 429 })); return; }
      // counted as the server answers: a read held on its way arrives late
      const u = new URL(url, "http://x");
      const w = u.searchParams.get("w")!, e = Number(u.searchParams.get("e")), q = Number(u.searchParams.get("q"));
      if (u.pathname === "/api/watch") {
        const skip = u.searchParams.get("skip");
        const table = skip ? TABLES[(TABLES.indexOf(skip) + 1) % TABLES.length] : TABLES[0];
        L.read(e, q, table, false);
        resolve(new Response(JSON.stringify(docOf(table, w)), { status: 200 }));
      } else {
        const table = decodeURIComponent(u.pathname.split("/")[3]);
        L.read(e, q, table, true);
        resolve(new Response(JSON.stringify({ ...docOf(table, w), waiting: true, events: undefined }), { status: 200 }));
      }
    };
    pending.push({ url, answer });
    most = Math.max(most, pending.length);
  })));
});
afterEach(() => {
  for (const r of roots.splice(0)) { act(() => r.root.unmount()); r.host.remove(); }
  clearToast();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

const flush = async () => { for (let i = 0; i < 6; i++) await act(async () => { await Promise.resolve(); }); };
async function answer(status: 200 | 429 = 200, which: "oldest" | "newest" = "oldest") {
  const p = which === "oldest" ? pending.shift() : pending.pop();
  if (!p) return false;
  await act(async () => { p.answer(status); });
  await flush();
  return true;
}
async function wait(ms: number) {
  await act(async () => { vi.advanceTimersByTime(ms); });
  await flush();
}
async function mount() {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  roots.push({ root, host });
  await act(async () => { root.render(<WatchScreen mode="ranked" />); });
  await flush();
  return host;
}
function unmount() {
  const r = roots.pop()!;
  act(() => r.root.unmount());
  r.host.remove();
}
const btn = (h: HTMLElement, label: string) => h.querySelector<HTMLButtonElement>(`button[aria-label="${label}"]`);
async function next(h: HTMLElement) {
  const more = btn(h, "More");
  if (!more) return;
  await act(async () => { more.click(); });
  const row = h.querySelector<HTMLButtonElement>("[role=menuitem]");
  if (row) await act(async () => { row.click(); });
  await flush();
}
/** The table drawn, read from its round label; null with no table drawn. */
function drawn(h: HTMLElement | null): string | null {
  const m = h?.querySelector(".watch-round")?.textContent?.match(/Round (\d+)/);
  return m ? TABLES[Number(m[1]) - 3] ?? null : null;
}
/** Every read answered (200) and every timer up to a follow run out, until
 *  nothing more is asked. */
async function settle() {
  for (let i = 0; i < 20; i++) {
    while (await answer(200)) { /* each answer may send the next read */ }
    await wait(RETRY_MS);
    if (pending.length === 0) break;
  }
}
/** The invariant: once settled, the table drawn alone counts the watcher,
 *  and the screen never had two reads on their way. */
function expectDrawnHoldsTheLease(h: HTMLElement | null) {
  expect(pending).toEqual([]);
  expect(most).toBeLessThanOrEqual(1);
  expect(L.table).toBe(drawn(h));
}
async function opened() {
  const h = await mount();
  await answer(200);
  expect(drawn(h)).toBe("aaa111");
  await act(async () => { btn(h, "Pause")!.click(); });
  return h;
}

describe("the table drawn is the table counted", () => {
  it("a follow due while Next is on its way waits: the pick's table is drawn and counted", async () => {
    const h = await opened();
    await next(h);                         // the pick is on its way
    await wait(FOLLOW_MS * 2);             // the follow timer passes, twice
    expect(pending.map((p) => p.url.startsWith("/api/watch?"))).toEqual([true]);
    await answer(200);
    expect(drawn(h)).toBe("bbb222");
    await settle();
    await wait(FOLLOW_MS);
    await settle();
    expectDrawnHoldsTheLease(h);
  });

  it("a Next asked while one is on its way, refused twice, keeps the table the first drew", async () => {
    const h = await opened();
    await next(h);
    await next(h);                         // waits for the first
    expect(pending).toHaveLength(1);
    await answer(200);                     // bbb222 drawn; the second Next goes now
    expect(drawn(h)).toBe("bbb222");
    await answer(429);
    await wait(RETRY_MS);
    await answer(429);                     // and its retry
    await settle();
    expect(drawn(h)).toBe("bbb222");
    expectDrawnHoldsTheLease(h);
  });

  it("a Next refused twice keeps the table on screen, counted there again", async () => {
    const h = await opened();
    await next(h);
    await answer(429);
    await wait(RETRY_MS);
    await answer(429);
    await settle();
    expect(drawn(h)).toBe("aaa111");
    expectDrawnHoldsTheLease(h);
  });

  it("Nexts tapped while the first is held go on one at a time from the table it drew", async () => {
    const h = await opened();
    await next(h);
    await next(h);
    await next(h);
    expect(pending).toHaveLength(1);
    await settle();
    expect(drawn(h)).toBe("ccc333");
    expectDrawnHoldsTheLease(h);
  });

  it("closed while its first pick is held, reopened into two refusals: nothing counts", async () => {
    await mount();
    unmount();
    const h = await mount();               // its pick waits for nothing: the first screen's is its own
    const firstScreens = pending.shift()!;
    await answer(429);
    await wait(RETRY_MS);
    await answer(429);                     // the toast; the screen closes
    await act(async () => { firstScreens.answer(200); });
    await flush();
    unmount();
    await settle();
    expect(drawn(h.isConnected ? h : null)).toBeNull();
    expect(L.table).toBeNull();
  });

  it("closed while its first pick is held, reopened at the same table: it counts once, there", async () => {
    await mount();
    unmount();
    const h = await mount();
    const firstScreens = pending.shift()!;
    await answer(200);
    await act(async () => { firstScreens.answer(200); });
    await flush();
    await settle();
    expect(drawn(h)).toBe("aaa111");
    expect(L.table).toBe("aaa111");
  });

  it("any interleaving of Next, the follow timer, answers and refusals settles on the table drawn", async () => {
    for (let seed = 1; seed <= 200; seed++) {
      let x = seed * 2654435761 % 4294967296;
      const rand = (n: number) => { x = (x * 1664525 + 1013904223) % 4294967296; return x % n; };
      L = new Leases();
      pending = [];
      most = 0;
      sessionStorage.clear();
      forgetWatcherToken();
      const h = await opened();
      for (let step = 0; step < 24; step++) {
        const a = rand(5);
        if (a === 0) await next(h);
        else if (a === 1) await wait(rand(FOLLOW_MS + 1));
        else if (a === 2) await answer(200);
        else if (a === 3) await answer(429);
        else await wait(RETRY_MS);
        expect(most, `seed ${seed} step ${step}`).toBeLessThanOrEqual(1);
      }
      await settle();
      await wait(FOLLOW_MS);
      await settle();
      expect([seed, L.table], `seed ${seed}`).toEqual([seed, drawn(h)]);
      expect(pending).toEqual([]);
      unmount();
      await settle();
    }
  }, 120_000);
});
