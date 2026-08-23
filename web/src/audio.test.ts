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

  state: "suspended" | "running" = "suspended";
  currentTime = 0;

  constructor() {
    FakeAudioContext.last = this;
  }

  async resume(): Promise<void> {
    if (FakeAudioContext.allowResume) this.state = "running";
  }
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

const store = new Map<string, string>();
const fakeLocalStorage = {
  getItem: (k: string) => store.get(k) ?? null,
  setItem: (k: string, v: string) => void store.set(k, v),
};

// Installed before importing audio.ts, which reads localStorage and attaches
// its unlock listeners at module scope.
Object.assign(globalThis, {
  window: fakeWindow,
  localStorage: fakeLocalStorage,
  AudioContext: FakeAudioContext,
});

async function freshModule() {
  listeners.clear();
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
});
