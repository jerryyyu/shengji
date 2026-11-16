// Time for the local server, in seconds. The browser uses the real timers;
// the parity tests run the same server on a virtual clock that jumps to the
// next timer, so a whole game takes no wall time and its order is exact.

export interface Clock {
  now(): number;
  setTimeout(fn: () => void, seconds: number): void;
}

export const realClock: Clock = {
  now: () => performance.now() / 1000,
  setTimeout: (fn, seconds) => {
    globalThis.setTimeout(fn, seconds * 1000);
  },
};

export function sleep(clock: Clock, seconds: number): Promise<void> {
  return new Promise((resolve) => clock.setTimeout(resolve, seconds));
}

/**
 * Timers run in due order, ties in the order they were set. `run()` lets
 * pending promise continuations settle before each timer, the way an event
 * loop finishes ready work before it looks at the clock.
 */
export class VirtualClock implements Clock {
  private t = 0;
  private seq = 0;
  private timers: { when: number; seq: number; fn: () => void }[] = [];

  now(): number {
    return this.t;
  }

  setTimeout(fn: () => void, seconds: number): void {
    this.timers.push({ when: this.t + seconds, seq: this.seq++, fn });
  }

  /** Run timers until none are left or `done()` holds. */
  async run(done: () => boolean, maxTimers = 1_000_000): Promise<void> {
    for (let n = 0; n < maxTimers; n++) {
      await settle();
      if (done() || !this.timers.length) return;
      let k = 0;
      for (let i = 1; i < this.timers.length; i++) {
        const a = this.timers[i];
        const b = this.timers[k];
        if (a.when < b.when || (a.when === b.when && a.seq < b.seq)) k = i;
      }
      const [timer] = this.timers.splice(k, 1);
      if (timer.when > this.t) this.t = timer.when;
      timer.fn();
    }
    throw new Error(`VirtualClock: more than ${maxTimers} timers`);
  }
}

/** Resolves after every promise continuation queued so far has run. */
function settle(): Promise<void> {
  const immediate = (globalThis as { setImmediate?: (fn: () => void) => void }).setImmediate;
  return new Promise((resolve) => (immediate ? immediate(() => resolve()) : globalThis.setTimeout(resolve, 0)));
}
