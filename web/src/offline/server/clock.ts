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

/** A beat this much later than its second is the page's own pause. */
export const PAUSE_SECONDS = 2;
const BEAT_SECONDS = 1;

/**
 * The page's own pauses on one clock: a JS freeze, or a trip to the
 * background, in which its timers and events wait and then all come due at
 * once. While someone holds the watch, a beat runs every second; a beat (or
 * any poll) that comes more than PAUSE_SECONDS after the last shows that the
 * page was stopped in between. Each pause is told once, as [from, to] in
 * clock time, to the listeners, by whichever timer polls first; a timer that
 * makes a liveness or deadline decision polls before it decides, so time the
 * page itself was stopped is never counted against someone else.
 */
export class PauseWatch {
  private users = 0;
  private gen = 0;
  private last = 0;
  private total = 0;
  private listeners = new Set<(from: number, to: number) => void>();

  private clock: Clock;

  constructor(clock: Clock) {
    this.clock = clock;
  }

  /** Starts the beat for this user; the returned call stops it once every user has. */
  hold(): () => void {
    if (this.users++ === 0) {
      this.last = this.clock.now();
      this.beat(++this.gen);
    }
    let held = true;
    return () => {
      if (!held) return;
      held = false;
      if (--this.users === 0) this.gen++;
    };
  }

  private beat(gen: number): void {
    this.clock.setTimeout(() => {
      if (gen !== this.gen) return;
      this.poll();
      this.beat(gen);
    }, BEAT_SECONDS);
  }

  /** Tells the listeners of a pause that has just ended, if there was one. */
  poll(): void {
    if (this.users === 0) return;
    const now = this.clock.now();
    const from = this.last;
    this.last = now;
    if (now - from <= BEAT_SECONDS + PAUSE_SECONDS) return;
    this.total += now - from;
    for (const fn of [...this.listeners]) fn(from, now);
  }

  /** `fn(from, to)` on each pause; the returned call removes it. */
  on(fn: (from: number, to: number) => void): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  /** Seconds of pause told so far. */
  paused(): number {
    this.poll();
    return this.total;
  }

  /** `fn` once `seconds` of the page's awake time have passed: a pause in
   *  between moves it on by the pause. */
  after(fn: () => void, seconds: number): void {
    const mark = this.paused();
    this.clock.setTimeout(() => {
      const more = this.paused() - mark;
      if (more > 1e-9) this.after(fn, more);
      else fn();
    }, seconds);
  }
}

const watches = new WeakMap<Clock, PauseWatch>();

/** The one pause watch of `clock` (so the host's room, its links and a
 *  joiner's socket on the same page agree on its pauses). */
export function pauseWatch(clock: Clock): PauseWatch {
  let w = watches.get(clock);
  if (!w) watches.set(clock, (w = new PauseWatch(clock)));
  return w;
}

/** The part of the pause [from, to] after `t`. */
export function pausedAfter(t: number, from: number, to: number): number {
  return Math.max(0, to - Math.max(from, t));
}
