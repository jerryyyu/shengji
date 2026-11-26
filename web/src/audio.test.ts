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
  // late-bound so fake timers reach the clock watchdog
  setInterval: (fn: () => void, ms: number) => globalThis.setInterval(fn, ms),
  clearInterval: (id: ReturnType<typeof setInterval>) => globalThis.clearInterval(id),
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

describe("no burst after a stall", () => {
  const playState = (plays: { seat: number; cards: string[] }[]) => ({
    phase: "play", banker: 0, levels: ["2", "2"], current_declaration: null,
    trump: { suit: "S", rank: "2" }, trick: { plays }, ...{},
  }) as unknown as import("./protocol").GameState;

  const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));

  /** iOS's interrupted context: resume() stays pending until the interruption
   *  ends, then every waiting promise resolves at once. */
  async function stalledTable() {
    const audio = await freshModule();
    Object.assign(globalThis, {
      fetch: async () => ({ ok: true, arrayBuffer: async () => new ArrayBuffer(0) }),
    });
    const started: string[] = [];
    const held: (() => void)[] = [];
    const proto = FakeAudioContext.prototype as unknown as Record<string, unknown>;
    proto.decodeAudioData = async () => ({ duration: 0.05 });
    proto.createBufferSource = () => {
      const src = {
        buffer: null, onended: null as null | (() => void),
        connect() {},
        start() { started.push("clip"); setTimeout(() => src.onended?.(), 50); },
      };
      return src;
    };
    const param = { value: 0, setValueAtTime() {}, exponentialRampToValueAtTime() {} };
    proto.createOscillator = () => ({
      frequency: param, connect() {}, start() { started.push("tick"); }, stop() {},
    });
    proto.createGain = () => ({ gain: param, connect() {} });
    proto.destination = {};

    FakeAudioContext.allowResume = true;
    dispatch("click");
    await wait(0);
    const c = FakeAudioContext.last!;
    expect(c.state).toBe("running");

    // the interruption: resume() now hangs instead of failing
    c.state = "interrupted";
    c.resume = () => new Promise<void>((res) => held.push(() => { c.state = "running"; res(); }));
    c.onstatechange?.();
    const end = () => { for (const r of held.splice(0)) r(); c.onstatechange?.(); };
    return { audio, c, started, held, end };
  }

  it("plays none of the sounds asked for while the context was held, on recovery", async () => {
    const { audio, started, held, end } = await stalledTable();
    // K requests over the stall: leads (queued clips) and follows (ticks)
    for (let k = 0; k < 6; k++) {
      audio.resetAnnouncer();
      audio.announceState(playState([
        { seat: 0, cards: ["H5"] }, { seat: 1, cards: ["H6"] }, { seat: 2, cards: ["H7"] },
      ]));
      audio.play(["pair", "H9"]);
      await wait(40);
    }
    await wait(300);
    expect(held.length).toBeGreaterThan(0);
    expect(started).toEqual([]);

    end(); // background and back: the pending resumes all resolve now
    await wait(300);
    expect(started).toEqual([]);

    // the next sound after recovery plays, alone
    audio.play(["H9"]);
    await wait(100);
    expect(started).toEqual(["clip"]);
  });

  it("drops a sound whose context does not run within 150 ms", async () => {
    const { audio, started, end } = await stalledTable();
    audio.play(["H9"]);
    await wait(200);
    end();
    await wait(100);
    expect(started).toEqual([]);
  });

  it("never has more than three voices live at once", async () => {
    const audio = await freshModule();
    const live = { now: 0, max: 0 };
    const proto = FakeAudioContext.prototype as unknown as Record<string, unknown>;
    const param = { value: 0, setValueAtTime() {}, exponentialRampToValueAtTime() {} };
    proto.createOscillator = () => ({
      frequency: param, connect() {},
      start() { live.now++; live.max = Math.max(live.max, live.now); setTimeout(() => live.now--, 70); },
      stop() {},
    });
    proto.createGain = () => ({ gain: param, connect() {} });
    proto.destination = {};
    FakeAudioContext.allowResume = true;
    dispatch("click");
    await wait(0);
    const seats = [0, 1, 2, 3].map((s) => ({ seat: s, cards: [`H${s + 3}`] }));
    for (let k = 0; k < 10; k++) {
      audio.resetAnnouncer();
      audio.announceState(playState(seats));
    }
    await wait(20);
    expect(live.max).toBe(3);
  });
});

describe("review recovery ordering and live sources", () => {
  const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
  const follows = [
    { seat: 0, cards: ["H5"] }, { seat: 1, cards: ["H6"] },
    { seat: 2, cards: ["H7"] }, { seat: 3, cards: ["H8"] },
  ];
  const state = ({
    phase: "play", banker: 0, levels: ["2", "2"], current_declaration: null,
    trump: { suit: "S", rank: "2" }, trick: { plays: follows },
  }) as unknown as import("./protocol").GameState;
  async function setup() {
    const audio = await freshModule();
    const proto = FakeAudioContext.prototype as unknown as Record<string, unknown>;
    const param = { value: 0, setValueAtTime() {}, exponentialRampToValueAtTime() {} };
    const nodes: { startCount: number; stopTimes: number[]; disconnects: number }[] = [];
    proto.createOscillator = () => {
      const node = { startCount: 0, stopTimes: [] as number[], disconnects: 0 };
      nodes.push(node);
      return {
        frequency: param, connect() {}, disconnect() { node.disconnects++; },
        start() { node.startCount++; }, stop(at?: number) { node.stopTimes.push(at ?? 0); },
      };
    };
    proto.createGain = () => ({ gain: param, connect() {} });
    proto.destination = {};
    Object.assign(globalThis, { fetch: async () => ({ ok: false }) });
    FakeAudioContext.allowResume = true;
    dispatch("click");
    await wait(0);
    const c = FakeAudioContext.last!;
    c.onstatechange?.();
    return { audio, c, nodes };
  }

  it("cancels already started oscillators immediately on interruption", async () => {
    const { audio, c, nodes } = await setup();
    audio.announceState(state);
    await wait(0);
    expect(nodes.map((node) => node.startCount)).toEqual([1, 1, 1]);
    expect(nodes.every((node) => node.stopTimes[0] > 0)).toBe(true);

    c.state = "interrupted";
    c.resume = () => new Promise<void>(() => {});
    c.onstatechange?.();
    await wait(90);

    // The audio clock did not advance while the context was held, so its
    // original playback-clock stop is still in the future.
    c.state = "running";
    c.onstatechange?.();
    audio.resetAnnouncer();
    audio.announceState(state);
    await wait(0);
    const liveAtAudioTime = nodes.filter((node) =>
      node.startCount > 0 && node.disconnects === 0 && Math.min(...node.stopTimes) > c.currentTime,
    );
    expect(liveAtAudioTime).toHaveLength(3);
  });

  it("rejects sounds requested during a short hold even if resume is observed before statechange", async () => {
    const { audio, c, nodes } = await setup();
    const held: (() => void)[] = [];
    c.state = "interrupted";
    c.resume = () => new Promise<void>((res) => held.push(res));
    c.onstatechange?.();
    audio.announceState(state);
    await wait(0);

    c.state = "running";
    for (const resolve of held) resolve();
    await wait(0);
    c.onstatechange?.();
    expect(nodes).toHaveLength(0);
  });
});

it("drops an announcement requested during an interruption", async () => {
  const audio = await freshModule();
  const started = vi.fn();
  const proto = FakeAudioContext.prototype as unknown as Record<string, unknown>;
  proto.decodeAudioData = async () => ({ duration: 0.05 });
  proto.createBufferSource = () => ({
    start: started, connect() {}, disconnect() {}, stop() {},
  });
  Object.assign(globalThis, { fetch: async () => ({ ok: true, arrayBuffer: async () => new ArrayBuffer(8) }) });
  FakeAudioContext.allowResume = true;
  dispatch("click");
  await new Promise(resolve => setTimeout(resolve, 0));
  const c = FakeAudioContext.last!;
  c.onstatechange?.();
  c.state = "interrupted";
  c.resume = () => new Promise<void>(() => {});
  c.onstatechange?.();
  audio.play(["pair"]);
  c.state = "running";
  await new Promise(resolve => setTimeout(resolve, 0));
  c.onstatechange?.();
  expect(started).toHaveBeenCalledTimes(0);
});

describe("a stuck context is revived", () => {
  const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));

  async function running() {
    const audio = await freshModule();
    Object.assign(globalThis, {
      fetch: async () => ({ ok: true, arrayBuffer: async () => new ArrayBuffer(8) }),
    });
    const started: FakeAudioContext[] = [];
    const proto = FakeAudioContext.prototype as unknown as Record<string, unknown>;
    proto.decodeAudioData = async () => ({ duration: 0.05 });
    proto.createBufferSource = function (this: FakeAudioContext) {
      const owner = this;
      const src = {
        buffer: null, onended: null as null | (() => void),
        connect() {}, disconnect() {}, stop() {},
        start() { started.push(owner); setTimeout(() => src.onended?.(), 50); },
      };
      return src;
    };
    proto.destination = {};
    FakeAudioContext.allowResume = true;
    dispatch("click");
    await wait(0);
    const c = FakeAudioContext.last!;
    expect(c.state).toBe("running");
    c.onstatechange?.();
    return { audio, c, started };
  }

  it("replaces a suspended context whose resume hangs on the next tap, and the next sound plays", async () => {
    const { audio, c, started } = await running();
    c.state = "suspended";
    c.resume = () => new Promise<void>(() => {});
    c.onstatechange?.();
    audio.play(["H9"]); // dropped: the context that ran is held
    await wait(RESUME_WAIT);
    expect(started).toEqual([]);

    dispatch("touchend");
    await wait(0);
    const fresh = FakeAudioContext.last!;
    expect(fresh).not.toBe(c);
    expect(fresh.state).toBe("running");

    audio.play(["H9"]);
    for (let i = 0; i < 20 && started.length === 0; i++) await wait(5);
    expect(started).toEqual([fresh]);
  });

  it("replaces a context the first gesture made when its resume hangs, on a later gesture", async () => {
    await freshModule();
    const proto = FakeAudioContext.prototype as unknown as { resume: () => Promise<void> };
    const resume = proto.resume;
    proto.resume = () => new Promise<void>(() => {});
    try {
      // cold: no prewarm ran, so this gesture creates the context
      dispatch("touchend");
      await wait(0);
      const first = FakeAudioContext.last!;
      expect(first.state).toBe("suspended");

      await wait(RESUME_WAIT);
      dispatch("touchend");
      expect(FakeAudioContext.last).not.toBe(first);
    } finally {
      proto.resume = resume;
    }
  });

  it("detects a running context whose clock froze and replaces it", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "performance"] });
    try {
      const { audio, c, started } = await running();
      const t0 = performance.now();
      let frozenAt: number | null = null;
      Object.defineProperty(c, "currentTime", {
        get: () => frozenAt ?? (performance.now() - t0) / 1000,
      });
      audio.play(["H9"]);
      for (let i = 0; i < 20 && started.length === 0; i++) await wait(5);
      expect(started).toEqual([c]);

      // a healthy clock is left alone
      vi.advanceTimersByTime(4000);
      expect(FakeAudioContext.last).toBe(c);

      frozenAt = c.currentTime;
      audio.play(["H9"]); // keeps the watchdog awake
      vi.advanceTimersByTime(4000);
      const fresh = FakeAudioContext.last!;
      expect(fresh).not.toBe(c);
      await wait(0);
      expect(fresh.state).toBe("running");

      started.length = 0;
      audio.play(["H9"]);
      for (let i = 0; i < 20 && started.length === 0; i++) await wait(5);
      expect(started).toEqual([fresh]);
    } finally {
      vi.useRealTimers();
    }
  });
});

const RESUME_WAIT = 350;
