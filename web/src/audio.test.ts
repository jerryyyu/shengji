/**
 * Audio unlock regression tests.
 *
 * Every browser on iOS is WebKit, iPhone Chrome included, and WebKit does not
 * unlock an AudioContext on `pointerdown`. The previous implementation
 * registered exactly one `{ once: true }` pointerdown listener, so on iOS it
 * spent its only attempt on a gesture that never unlocks anything and then
 * removed itself: permanent silence for the life of the page, with no console
 * error and a mute button that still looked correct.
 *
 * Both tests below fail against that implementation.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

type Listener = () => void;

/** Records gesture listeners so tests can dispatch them by name. */
const listeners = new Map<string, Set<Listener>>();

class FakeAudioContext {
  static last: FakeAudioContext | null = null;
  /** Tests flip this to model "this gesture is allowed to unlock audio". */
  static allowResume = false;

  state: "suspended" | "running" | "interrupted" = "suspended";
  currentTime = 0;
  onstatechange: (() => void) | null = null;

  constructor() {
    FakeAudioContext.last = this;
  }

  /** Models WebKit's stuck context: resume never leaves "interrupted". */
  stuck = false;

  async resume(): Promise<void> {
    if (FakeAudioContext.allowResume && !this.stuck) this.state = "running";
  }

  async close(): Promise<void> {}
}

function dispatch(name: string): void {
  for (const fn of listeners.get(name) ?? []) fn();
}

const fakeWindow = {
  addEventListener(name: string, fn: Listener) {
    let set = listeners.get(name);
    if (!set) {
      set = new Set();
      listeners.set(name, set);
    }
    set.add(fn);
  },
  removeEventListener(name: string, fn: Listener) {
    listeners.get(name)?.delete(fn);
  },
  setTimeout: globalThis.setTimeout.bind(globalThis),
  clearTimeout: globalThis.clearTimeout.bind(globalThis),
  AudioContext: FakeAudioContext,
};

/** Minimal document stub: audio.ts re-arms unlock on visibilitychange. */
const docListeners = new Map<string, Set<Listener>>();
const fakeDocument = {
  visibilityState: "visible" as "visible" | "hidden",
  addEventListener(name: string, fn: Listener) {
    let set = docListeners.get(name);
    if (!set) {
      set = new Set();
      docListeners.set(name, set);
    }
    set.add(fn);
  },
  removeEventListener(name: string, fn: Listener) {
    docListeners.get(name)?.delete(fn);
  },
};

function dispatchDoc(name: string): void {
  for (const fn of docListeners.get(name) ?? []) fn();
}

const store = new Map<string, string>();
const fakeLocalStorage = {
  getItem: (k: string) => store.get(k) ?? null,
  setItem: (k: string, v: string) => void store.set(k, v),
};

// Installed before importing audio.ts, which reads localStorage and attaches
// its unlock listeners at module scope.
Object.assign(globalThis, {
  window: fakeWindow,
  document: fakeDocument,
  localStorage: fakeLocalStorage,
  AudioContext: FakeAudioContext,
});

async function freshModule() {
  listeners.clear();
  docListeners.clear();
  fakeDocument.visibilityState = "visible";
  store.clear();
  FakeAudioContext.last = null;
  FakeAudioContext.allowResume = false;
  // Re-import so module-scope listener registration runs again per test.
  vi.resetModules();
  return await import("./audio");
}

describe("audio unlock", () => {
  beforeEach(() => {
    listeners.clear();
  });

  it("unlocks on touchend, which is the gesture iOS actually honours", async () => {
    const audio = await freshModule();
    expect(audio.isMuted()).toBe(false);

    FakeAudioContext.allowResume = true;
    dispatch("touchend");
    await Promise.resolve();
    await Promise.resolve();

    expect(FakeAudioContext.last).not.toBeNull();
    expect(FakeAudioContext.last?.state).toBe("running");
  });

  it("keeps trying after a gesture fails to unlock", async () => {
    await freshModule();

    // First gesture does not unlock — exactly the iOS pointerdown case.
    FakeAudioContext.allowResume = false;
    dispatch("pointerdown");
    await Promise.resolve();
    await Promise.resolve();
    expect(FakeAudioContext.last?.state).toBe("suspended");

    // A later qualifying gesture must still be able to unlock. The old
    // `{ once: true }` listener had already removed itself by now.
    FakeAudioContext.allowResume = true;
    dispatch("click");
    await Promise.resolve();
    await Promise.resolve();

    expect(FakeAudioContext.last?.state).toBe("running");
  });

  it("re-arms unlock after returning from the background", async () => {
    await freshModule();

    FakeAudioContext.allowResume = true;
    dispatch("click");
    await Promise.resolve();
    await Promise.resolve();
    expect(FakeAudioContext.last?.state).toBe("running");

    // Backgrounding suspends the context. Unlock listeners were detached when
    // it started running, so without re-arming audio would never come back.
    FakeAudioContext.last!.state = "suspended";
    FakeAudioContext.allowResume = false;
    dispatchDoc("visibilitychange");
    await Promise.resolve();

    FakeAudioContext.allowResume = true;
    dispatch("touchend");
    await Promise.resolve();
    await Promise.resolve();

    expect(FakeAudioContext.last?.state).toBe("running");
  });

  it("re-arms unlock when iOS interrupts a running context without a visibility change", async () => {
    await freshModule();

    FakeAudioContext.allowResume = true;
    dispatch("click");
    await Promise.resolve();
    await Promise.resolve();
    expect(FakeAudioContext.last?.state).toBe("running");

    // The keyboard's dictation (or a call) interrupts audio while the page
    // stays visible; the first resume is refused until the next gesture.
    FakeAudioContext.allowResume = false;
    FakeAudioContext.last!.state = "interrupted";
    FakeAudioContext.last!.onstatechange?.();
    await Promise.resolve();
    expect(FakeAudioContext.last?.state).toBe("interrupted");

    FakeAudioContext.allowResume = true;
    dispatch("touchend");
    await Promise.resolve();
    await Promise.resolve();
    expect(FakeAudioContext.last?.state).toBe("running");
  });

  it("replaces a context iOS leaves stuck in interrupted on the next gesture", async () => {
    await freshModule();

    FakeAudioContext.allowResume = true;
    dispatch("click");
    await Promise.resolve();
    await Promise.resolve();
    const first = FakeAudioContext.last!;
    expect(first.state).toBe("running");

    // Reconnecting after a trip to the background: the context is
    // interrupted and no resume will ever bring it back.
    first.state = "interrupted";
    first.stuck = true;
    first.onstatechange?.();
    await Promise.resolve();

    dispatch("touchend");
    await Promise.resolve();
    await Promise.resolve();
    expect(FakeAudioContext.last).not.toBe(first);
    expect(FakeAudioContext.last?.state).toBe("running");
  });
});

describe("declaration clips", () => {
  const dealState = (over: Record<string, unknown> = {}) => ({
    phase: "deal", banker: null, levels: ["2", "2"], current_declaration: null,
    trump: null, trick: null, ...over,
  }) as unknown as import("./protocol").GameState;

  async function withFetch() {
    const audio = await freshModule();
    const urls: string[] = [];
    const net = { online: true };
    Object.assign(globalThis, {
      fetch: async (url: string) => {
        urls.push(url);
        if (!net.online) throw new TypeError("Load failed");
        return { ok: true, arrayBuffer: async () => new ArrayBuffer(0) };
      },
    });
    const started: number[] = [];
    const proto = FakeAudioContext.prototype as unknown as Record<string, unknown>;
    proto.decodeAudioData = async () => ({ duration: 0 });
    proto.createBufferSource = () => {
      const src = {
        buffer: null, onended: null as null | (() => void),
        connect() {},
        start() { started.push(1); setTimeout(() => src.onended?.(), 0); },
      };
      return src;
    };
    proto.destination = {};
    return { audio, net, started, names: () => urls.map((u) => u.replace(/^\/sounds\/|\.mp3\?.*$/g, "")) };
  }

  it("are fetched during the deal, before any declaration needs them", async () => {
    const { audio, names } = await withFetch();
    audio.announceState(dealState(), true);
    expect(names().sort()).toEqual(["C2", "D2", "H2", "S2", "nt", "pair"]);
    // every later frame of the deal reuses them
    audio.announceState(dealState());
    expect(names()).toHaveLength(6);
  });

  it("follow the banker's level, and stay unfetched while muted", async () => {
    const { audio, names } = await withFetch();
    audio.announceState(dealState({ banker: 1, levels: ["5", "10"] }), true);
    expect(names().sort()).toEqual(["C10", "D10", "H10", "S10", "nt", "pair"]);

    const muted = await withFetch();
    muted.audio.setMuted(true);
    muted.audio.announceState(dealState(), true);
    expect(muted.names()).toEqual([]);
  });

  it("retry a failed prefetch once when its declaration is played", async () => {
    const { audio, net, started, names } = await withFetch();
    FakeAudioContext.allowResume = true;
    net.online = false;
    audio.announceState(dealState(), true);
    await new Promise((r) => setTimeout(r, 0));
    expect(names()).toHaveLength(6);
    // the rest of the deal does not refetch the failed clips
    audio.announceState(dealState());
    await new Promise((r) => setTimeout(r, 0));
    expect(names()).toHaveLength(6);

    net.online = true;
    audio.announceState(dealState({ current_declaration: { seat: 1, cards: ["S2"] } }));
    for (let i = 0; i < 20 && started.length === 0; i++) await new Promise((r) => setTimeout(r, 0));
    expect(names().slice(6)).toEqual(["S2"]);
    expect(started).toHaveLength(1);
  });
});
